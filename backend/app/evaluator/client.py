"""LLM-клиенты: протокол, MockClient для разработки без ключа и AnthropicClient."""

from __future__ import annotations

import copy
import os
import re
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from .errors import LLMUnavailableError
from .render import unescape
from .wire import TOOL_DESCRIPTION, TOOL_NAME


@dataclass(frozen=True)
class LLMResponse:
    tool_input: dict[str, Any] | None  # None, если модель не вернула tool-блок
    input_tokens: int
    output_tokens: int
    model: str


class LLMClient(Protocol):
    def complete(self, system: str, user: str, tool_schema: dict[str, Any]) -> LLMResponse: ...


# ---------- Mock ----------

FaultKind = Literal[
    "bad_scale_step",
    "fake_quote",
    "illegal_na",
    "missing_criterion",
    "duplicate_criterion",
    "no_tool_block",
]
_TURN_LINE = re.compile(r"^\[(\d+)\] (client|operator|bot|system): (.*)$")


@dataclass(frozen=True)
class Fault:
    """Порча ответа для тестов. calls: номера вызовов (с 1), None означает каждый вызов."""

    kind: FaultKind
    criterion_id: str | None = None  # None: первый подходящий критерий вызова
    calls: tuple[int, ...] | None = None


class MockClient:
    """Строит валидный ответ по схеме и транскрипту из user message, без знания конкретных критериев.

    Проверяет программный поток, а не точность оценок LLM.
    """

    def __init__(
        self, faults: tuple[Fault, ...] | list[Fault] = (), na_criteria: frozenset[str] = frozenset()
    ):
        self.faults = tuple(faults)
        self.na_criteria = na_criteria
        self.requested: list[list[str]] = []  # id критериев по каждому вызову
        self.calls = 0

    def complete(self, system: str, user: str, tool_schema: dict[str, Any]) -> LLMResponse:
        self.calls += 1
        props: dict[str, Any] = tool_schema["properties"]
        self.requested.append(list(props))
        turns = self._parse_turns(user)
        answers = {cid: self._valid_answer(cid, spec, turns) for cid, spec in props.items()}
        tool_input: dict[str, Any] | None = answers
        for fault in self.faults:
            if fault.calls is None or self.calls in fault.calls:
                tool_input = self._apply(fault, props, answers) if tool_input is not None else None
        return LLMResponse(tool_input=tool_input, input_tokens=0, output_tokens=0, model="mock")

    @staticmethod
    def _parse_turns(user: str) -> list[tuple[int, str, str]]:
        return [
            (int(m[1]), m[2], unescape(m[3])) for line in user.splitlines() if (m := _TURN_LINE.match(line))
        ]

    def _valid_answer(
        self, cid: str, spec: dict[str, Any], turns: list[tuple[int, str, str]]
    ) -> dict[str, Any]:
        enum = spec["properties"]["answer"]["enum"]
        scale_enum = spec["properties"]["scale_value"].get("enum")
        na_ref = spec["properties"]["na_condition_ref"].get("enum", [None])[0]
        first_op = next(((i, t) for i, s, t in turns if s == "operator" and t.strip()), None)
        anchor = first_op[0] if first_op else (turns[0][0] if turns else 0)
        if cid in self.na_criteria and "na" in enum:
            return {
                "answer": "na",
                "scale_value": None,
                "explanation": "Mock: условие неприменимости задано тестом.",
                "evidence": [_evidence("na_reason", turn_index=anchor)],
                "na_condition_ref": na_ref,
            }
        if first_op:
            text = first_op[1].strip()
            chunk = text[:60].rsplit(" ", 1)[0] if len(text) > 60 and " " in text[:60] else text[:60]
            evidence = [_evidence("quote", turn_index=first_op[0], quote=chunk)]
        else:
            last = turns[-1][0] if turns else 0
            evidence = [_evidence("checked_range", range_start=0, range_end=last)]
        return {
            "answer": enum[0],
            "scale_value": next((v for v in scale_enum or [] if v is not None), None),
            "explanation": "Mock: ответ собран для проверки программного потока.",
            "evidence": evidence,
            "na_condition_ref": None,
        }

    @staticmethod
    def _apply(fault: Fault, props: dict[str, Any], answers: dict[str, Any]) -> dict[str, Any] | None:
        if fault.kind == "no_tool_block":
            return None

        def eligible(cid: str) -> bool:
            spec = props[cid]["properties"]
            if fault.kind == "bad_scale_step":
                return spec["scale_value"].get("enum") is not None
            if fault.kind == "illegal_na":
                return "na" not in spec["answer"]["enum"]
            return True

        candidates = [c for c in props if eligible(c)]
        target = fault.criterion_id if fault.criterion_id in candidates else None
        if target is None and fault.criterion_id is None and candidates:
            target = candidates[0]
        if target is None:
            return answers
        broken = copy.deepcopy(answers)
        item = broken[target]
        if fault.kind == "bad_scale_step":
            item["scale_value"] = (
                max(v for v in props[target]["properties"]["scale_value"]["enum"] if v is not None) + 1
            )
        elif fault.kind == "fake_quote":
            item["evidence"] = [
                _evidence("quote", turn_index=0, quote="выдуманная цитата, которой нет в диалоге")
            ]
        elif fault.kind == "illegal_na":
            item.update(answer="na", scale_value=None, na_condition_ref="любое условие")
            item["evidence"] = [_evidence("na_reason", turn_index=0)]
        elif fault.kind == "missing_criterion":
            del broken[target]
        elif fault.kind == "duplicate_criterion":
            broken[f"{target}__dup"] = copy.deepcopy(item)
        return broken


def _evidence(kind: str, **fields: Any) -> dict[str, Any]:
    base = {"kind": kind, "turn_index": None, "quote": None, "range_start": None, "range_end": None}
    return base | fields


# ---------- Anthropic ----------

DEFAULT_TIMEOUT_SEC = 60.0
MAX_TOKENS = 8192


class AnthropicClient:
    """Реальная модель. Включается только при CQA_EVALUATOR=llm. Не проверялся на живом API."""

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        timeout: float = DEFAULT_TIMEOUT_SEC,
        sdk_client: Any = None,
    ) -> None:
        if not model:
            raise ValueError("CQA_LLM_MODEL не задан: модель по умолчанию не выбрана до сравнения на эталоне")
        if sdk_client is None:
            import anthropic

            sdk_client = anthropic.Anthropic(api_key=api_key, max_retries=2, timeout=timeout)
        self._sdk = sdk_client
        self.model = model

    @classmethod
    def from_env(cls) -> AnthropicClient:
        return cls(
            model=os.environ.get("CQA_LLM_MODEL", ""),
            api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
            timeout=float(os.environ.get("CQA_LLM_TIMEOUT_SEC") or DEFAULT_TIMEOUT_SEC),
        )

    def complete(self, system: str, user: str, tool_schema: dict[str, Any]) -> LLMResponse:
        import anthropic

        try:
            resp = self._sdk.messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                temperature=0,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user}],
                tools=[{"name": TOOL_NAME, "description": TOOL_DESCRIPTION, "input_schema": tool_schema}],
                tool_choice={"type": "tool", "name": TOOL_NAME},
            )
        except anthropic.APIError as exc:
            # Текст исключения может содержать тело запроса, поэтому в сообщение идёт только тип.
            raise LLMUnavailableError(f"вызов модели не удался: {type(exc).__name__}") from exc
        tool_input = next(
            (b.input for b in resp.content if getattr(b, "type", None) == "tool_use" and b.name == TOOL_NAME),
            None,
        )
        u = resp.usage
        cached = (getattr(u, "cache_creation_input_tokens", 0) or 0) + (
            getattr(u, "cache_read_input_tokens", 0) or 0
        )
        return LLMResponse(
            tool_input=tool_input if isinstance(tool_input, dict) else None,
            input_tokens=(u.input_tokens or 0) + cached,
            output_tokens=u.output_tokens or 0,
            model=getattr(resp, "model", None) or self.model,
        )


def make_client() -> LLMClient:
    mode = os.environ.get("CQA_EVALUATOR", "mock")
    if mode == "mock":
        return MockClient()
    if mode == "llm":
        return AnthropicClient.from_env()
    raise ValueError(f"CQA_EVALUATOR: ожидается mock или llm, получено {mode!r}")


@dataclass(frozen=True)
class Prices:
    input_per_mtok: float = 0.0
    output_per_mtok: float = 0.0

    @classmethod
    def from_env(cls) -> Prices:
        return cls(
            input_per_mtok=float(os.environ.get("CQA_PRICE_INPUT_PER_MTOK") or 0),
            output_per_mtok=float(os.environ.get("CQA_PRICE_OUTPUT_PER_MTOK") or 0),
        )
