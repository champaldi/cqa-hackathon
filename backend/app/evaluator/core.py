"""Оркестрация оценки: промпт, вызов, валидация, ограниченный repair."""

from __future__ import annotations

import logging
import time

from ..contracts import Checklist, CriterionResult, Dialog, EvaluatorOutput, Usage
from .client import LLMClient, Prices, make_client
from .errors import CriterionError, NoOperatorTurnsError, ValidationFailedError
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
        resp = client.complete(system, user, build_tool_schema(pending))  # LLMUnavailableError идёт наверх
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
            ",".join(f"{cid}:{e.code}" for cid, errs in errors.items() for e in errs) or "-",
            resp.input_tokens,
            resp.output_tokens,
            latency_ms,
        )
        pending = [c for c in pending if c.id in errors]
        if not pending:
            break

    usage = _usage(model, calls, tokens_in, tokens_out, prices)
    if pending:
        raise ValidationFailedError([e for errs in errors.values() for e in errs], usage)

    results = [valid[c.id] for c in checklist.criteria]
    final_errors = validate_complete(results, checklist, turns)
    if final_errors:
        raise ValidationFailedError(final_errors, usage)
    for r in results:
        if not has_cyrillic(r.explanation):  # мягкая проверка: RU требуется промптом, результат не режем
            log.warning(
                "evaluator_soft_check conversation_id=%s criterion=%s code=explanation_not_cyrillic",
                dialog.conversation_id,
                r.criterion_id,
            )
    return EvaluatorOutput(results=results, usage=usage)
