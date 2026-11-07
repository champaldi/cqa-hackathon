"""Клиенты модели: протокол, MockClient для тестов и AnthropicClient.

Скрытых умолчаний нет: клиент и цены передаются явно (см. factory.py).
"""

from __future__ import annotations

import copy
import json
import re
import threading
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from ..contracts import Checklist, Criterion
from .errors import LLMRejectedError, LLMUnavailableError
from .render import unescape


@dataclass(frozen=True)
class LLMResponse:
    text: str  # текст ответа модели, ожидается JSON по схеме
    input_tokens: int
    output_tokens: int
    stop_reason: str | None  # end_turn, max_tokens, refusal и т.д.


class LLMClient(Protocol):
    def complete(self, system: str, user: str, schema: dict[str, Any]) -> LLMResponse: ...


@dataclass(frozen=True)
class Prices:
    """USD за 1 млн токенов. Цена плоская: кеш промпта не учитывается."""

    input_per_mtok: float = 0.0
    output_per_mtok: float = 0.0


# ---------- Mock ----------

FaultKind = Literal[
    "bad_scale_step",
    "fake_quote",
    "illegal_na",
    "missing_criterion",
    "duplicate_criterion",
    "bad_json",
    "max_tokens",
    "refusal",
]
_TURN_LINE = re.compile(r"^\[(\d+)\] (client|operator|bot|system) \([^)]*\): (.*)$")
_REPAIR_LINE = re.compile(r"^Критерии для исправления: (.*)\.$", re.MULTILINE)


@dataclass(frozen=True)
class Fault:
    """Порча ответа для тестов. calls: номера вызовов (с 1), None означает каждый вызов."""

    kind: FaultKind
    criterion_id: str | None = None  # None: первый подходящий критерий вызова
    calls: tuple[int, ...] | None = None


def _evidence(kind: str, **fields: Any) -> dict[str, Any]:
    base = {"kind": kind, "turn_index": None, "quote": None, "range_start": None, "range_end": None}
    return base | fields


class MockClient:
    """Строит валидный ответ по чек-листу и транскрипту из user message.

    Проверяет программный поток, а не точность оценок LLM. Счётчики защищены локом.
    """

    def __init__(
        self,
        checklist: Checklist,
        faults: tuple[Fault, ...] | list[Fault] = (),
        na_criteria: frozenset[str] = frozenset(),
    ) -> None:
        self.checklist = checklist
        self.faults = tuple(faults)
        self.na_criteria = na_criteria
        self.requested: list[list[str]] = []  # id критериев по каждому вызову
        self.calls = 0
        self._lock = threading.Lock()

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> LLMResponse:
        with self._lock:
            self.calls += 1
            n = self.calls
            m = _REPAIR_LINE.search(user)
            wanted = [x.strip() for x in m[1].split(",")] if m else [c.id for c in self.checklist.criteria]
            self.requested.append(wanted)
        turns = [
            (int(t[1]), t[2], unescape(t[3])) for line in user.splitlines() if (t := _TURN_LINE.match(line))
        ]
        results = [self._valid(c, turns) for c in self.checklist.criteria if c.id in wanted]
        text, stop = None, "end_turn"
        for fault in self.faults:
            if fault.calls is None or n in fault.calls:
                if fault.kind == "bad_json":
                    text = "это не JSON"
                elif fault.kind in ("max_tokens", "refusal"):
                    stop = fault.kind
                else:
                    results = self._apply(fault, results)
        if text is None:
            text = json.dumps({"results": results}, ensure_ascii=False)
        return LLMResponse(text=text, input_tokens=0, output_tokens=0, stop_reason=stop)

    def _valid(self, c: Criterion, turns: list[tuple[int, str, str]]) -> dict[str, Any]:
        quotable = next(((i, t) for i, s, t in turns if s == "operator" and t.strip()), None) or next(
            ((i, t) for i, _, t in turns if t.strip()), None
        )
        anchor = quotable[0] if quotable else (turns[0][0] if turns else 0)
        head = {"criterion_id": c.id}
        if c.id in self.na_criteria and c.allow_na:
            return head | {
                "evidence": [_evidence("na_reason", turn_index=anchor)],
                "explanation": "Mock: условие неприменимости задано тестом.",
                "answer": "na",
                "scale_value": None,
                "na_condition_ref": c.na_condition,
            }
        if quotable:
            text = quotable[1].strip()
            chunk = text[:60].rsplit(" ", 1)[0] if len(text) > 60 and " " in text[:60] else text[:60]
            evidence = [_evidence("quote", turn_index=quotable[0], quote=chunk)]
        else:  # цитировать нечего: yes без цитаты невалиден, поэтому no по участку
            evidence = [_evidence("checked_range", range_start=0, range_end=turns[-1][0] if turns else 0)]
        if c.answer_type == "scale":
            answer = "scale"
        elif c.answer_type == "flag" or not quotable:
            answer = "no"
        else:
            answer = "yes"
        return head | {
            "evidence": evidence,
            "explanation": "Mock: ответ собран для проверки программного потока.",
            "answer": answer,
            "scale_value": c.scale[0].value if answer == "scale" and c.scale else None,
            "na_condition_ref": None,
        }

    def _apply(self, fault: Fault, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_id = {c.id: c for c in self.checklist.criteria}

        def eligible(item: dict[str, Any]) -> bool:
            c = by_id[item["criterion_id"]]
            if fault.kind == "bad_scale_step":
                return bool(c.scale)
            if fault.kind == "illegal_na":
                return not c.allow_na
            return True

        candidates = [r["criterion_id"] for r in results if eligible(r)]
        target = fault.criterion_id if fault.criterion_id in candidates else None
        if target is None and fault.criterion_id is None and candidates:
            target = candidates[0]
        if target is None:
            return results
        broken = copy.deepcopy(results)
        item = next(r for r in broken if r["criterion_id"] == target)
        if fault.kind == "bad_scale_step":
            item["scale_value"] = max(s.value for s in by_id[target].scale or []) + 1
        elif fault.kind == "fake_quote":
            item["evidence"] = [
                _evidence("quote", turn_index=0, quote="выдуманная цитата, которой нет в диалоге")
            ]
        elif fault.kind == "illegal_na":
            item.update(answer="na", scale_value=None, na_condition_ref="любое условие")
            item["evidence"] = [_evidence("na_reason", turn_index=0)]
        elif fault.kind == "missing_criterion":
            broken.remove(item)
        elif fault.kind == "duplicate_criterion":
            broken.append(copy.deepcopy(item))
        return broken


# ---------- Anthropic ----------

DEFAULT_TIMEOUT_SEC = 120.0
MAX_TOKENS = 8192  # thinking на Opus 5.5 не выключается и входит в max_tokens
_REJECTED_STATUSES = frozenset({400, 401, 403, 404})


class AnthropicClient:
    """Реальная модель. Не проверялся на живом API.

    Параметры вызова ограничены сигнатурой anthropic==2.6.0: нет temperature, нет tool_choice,
    структура ответа задаётся через output_config. cache_control не используется: цена плоская.
    SDK сам повторяет 429 и 5xx (max_retries=2). В llm_calls (считает core) попадают только вызовы
    с полученным ответом, исчерпанные транспортные попытки не считаются.
    """

    def __init__(
        self,
        model: str,
        api_key: str,
        timeout: float = DEFAULT_TIMEOUT_SEC,
        sdk_client: Any = None,
    ) -> None:
        if not model:
            raise ValueError("модель не задана: выбор модели делается по сравнению на эталоне")
        if sdk_client is None:
            if not api_key:
                raise ValueError("ключ API не задан")
            import anthropic

            sdk_client = anthropic.Anthropic(api_key=api_key, max_retries=2, timeout=timeout)
        self._sdk = sdk_client
        self.model = model

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> LLMResponse:
        import anthropic

        try:
            resp = self._sdk.messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config={"format": {"type": "json_schema", "schema": schema}},
            )
        except anthropic.APIError as exc:
            # Текст исключения может содержать тело запроса: в сообщение идёт только тип и код статуса.
            status = getattr(exc, "status_code", None)
            suffix = f", HTTP {status}" if status else ""
            message = f"вызов модели не удался: {type(exc).__name__}{suffix}"
            transient = isinstance(exc, anthropic.APIConnectionError) or (
                status is not None and (status == 429 or status >= 500)
            )
            if transient:
                raise LLMUnavailableError(message, upstream_status=status) from exc
            raise LLMRejectedError(message, upstream_status=status) from exc
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        u = resp.usage
        cached = (getattr(u, "cache_creation_input_tokens", 0) or 0) + (
            getattr(u, "cache_read_input_tokens", 0) or 0
        )
        return LLMResponse(
            text=text,
            input_tokens=(u.input_tokens or 0) + cached,
            output_tokens=u.output_tokens or 0,
            stop_reason=resp.stop_reason,
        )
