"""Оркестрация оценки: промпт, вызов, валидация, ограниченный repair."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from ..contracts import Checklist, CriterionResult, Dialog, EvaluatorOutput, Usage
from .client import LLMClient, Prices, make_client
from .errors import CriterionError, LLMUnavailableError, NoOperatorTurnsError, ValidationFailedError
from .prompt import build_repair_message, build_system_prompt, build_user_message
from .validate import has_cyrillic, validate_complete
from .wire import build_tool_schema, parse_tool_input

log = logging.getLogger("cqa.evaluator")

MAX_REPAIR_ROUNDS = 2


def _usage(model: str, calls: int, tokens_in: int, tokens_out: int, prices: Prices) -> Usage:
    cost = (tokens_in * prices.input_per_mtok + tokens_out * prices.output_per_mtok) / 1_000_000
    return Usage(
        model=model, llm_calls=calls, input_tokens=tokens_in, output_tokens=tokens_out, cost_usd=cost
    )


def _codes(errs: list[CriterionError]) -> str:
    return ",".join(f"{e.criterion_id or '-'}:{e.code}" for e in errs) or "-"


def _log_done(dialog: Dialog, status: str, usage: Usage, detail: str) -> None:
    """Итог оценки: только id диалога, статус, коды и расход. Реплик, цитат и ответа модели здесь нет."""
    log.info(
        "evaluator_done conversation_id=%s status=%s model=%s calls=%d input_tokens=%d output_tokens=%d "
        "cost_usd=%.6f detail=%s",
        dialog.conversation_id,
        status,
        usage.model,
        usage.llm_calls,
        usage.input_tokens,
        usage.output_tokens,
        usage.cost_usd,
        detail,
    )


def evaluate(
    dialog: Dialog,
    checklist: Checklist,
    *,
    client: LLMClient | None = None,
    prices: Prices | None = None,
    max_repair_rounds: int = MAX_REPAIR_ROUNDS,
) -> EvaluatorOutput:
    """Оценивает оператора по чек-листу. Либо полный валидный результат, либо исключение."""
    turns = dialog.transcript
    if not any(t.speaker == "operator" for t in turns):
        raise NoOperatorTurnsError(dialog.conversation_id)

    client = client if client is not None else make_client()
    prices = prices if prices is not None else Prices.from_env()
    system = build_system_prompt(checklist)

    valid: dict[str, CriterionResult] = {}
    pending = list(checklist.criteria)
    errors: dict[str, list[CriterionError]] = {}
    calls = tokens_in = tokens_out = 0
    model = "mock"

    for attempt in range(max_repair_rounds + 1):
        user = build_user_message(dialog) if attempt == 0 else build_repair_message(dialog, errors)
        started = time.perf_counter()
        try:
            resp = client.complete(system, user, build_tool_schema(pending))
        except LLMUnavailableError as exc:
            exc.usage = _usage(model, calls, tokens_in, tokens_out, prices)
            _log_done(dialog, "llm_unavailable", exc.usage, f"upstream_status={exc.upstream_status or '-'}")
            raise
        latency_ms = int((time.perf_counter() - started) * 1000)
        calls += 1
        tokens_in += resp.input_tokens
        tokens_out += resp.output_tokens
        model = resp.model or model

        outcome = parse_tool_input(resp.tool_input, pending, turns)
        valid.update(outcome.ok)
        errors = outcome.errors
        log.info(
            "evaluator_call conversation_id=%s attempt=%d criteria=%s error_codes=%s "
            "input_tokens=%d output_tokens=%d latency_ms=%d",
            dialog.conversation_id,
            attempt,
            ",".join(c.id for c in pending),
            _codes([e for errs in errors.values() for e in errs]),
            resp.input_tokens,
            resp.output_tokens,
            latency_ms,
        )
        pending = [c for c in pending if c.id in errors]
        if not pending:
            break

    usage = _usage(model, calls, tokens_in, tokens_out, prices)
    if pending:
        failed = [e for errs in errors.values() for e in errs]
        _log_done(dialog, "failed", usage, _codes(failed))
        raise ValidationFailedError(failed, usage)

    results = [valid[c.id] for c in checklist.criteria]
    final_errors = validate_complete(results, checklist, turns)
    if final_errors:
        _log_done(dialog, "failed", usage, _codes(final_errors))
        raise ValidationFailedError(final_errors, usage)
    for r in results:
        if not has_cyrillic(r.explanation):  # мягкая проверка: RU требуется промптом, результат не режем
            log.warning(
                "evaluator_soft_check conversation_id=%s criterion=%s code=explanation_not_cyrillic",
                dialog.conversation_id,
                r.criterion_id,
            )
    _log_done(dialog, "ok", usage, "-")
    return EvaluatorOutput(results=results, usage=usage)


@dataclass(frozen=True)
class LlmEvaluator:
    """Настоящая модель за интерфейсом Evaluator. Состояния нет: пакет зовёт её из нескольких потоков."""

    client: LLMClient
    prices: Prices

    def evaluate(self, dialog: Dialog, checklist: Checklist) -> EvaluatorOutput:
        return evaluate(dialog, checklist, client=self.client, prices=self.prices)
