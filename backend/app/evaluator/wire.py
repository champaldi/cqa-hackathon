"""Внутренний wire-формат tool'а модели: схема из Checklist и разбор ответа."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..contracts import Criterion, CriterionResult, Turn
from . import errors as E
from .errors import CriterionError
from .validate import ANSWER_KEYS, check_answer

TOOL_NAME = "submit_evaluation"
TOOL_DESCRIPTION = "Отправить оценку оператора по критериям чек-листа."

_NULLABLE_INT = {"type": ["integer", "null"]}
_EVIDENCE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["kind", "turn_index", "quote", "range_start", "range_end"],
    "properties": {
        "kind": {"type": "string", "enum": ["quote", "checked_range", "na_reason"]},
        "turn_index": _NULLABLE_INT,
        "quote": {"type": ["string", "null"]},
        "range_start": _NULLABLE_INT,
        "range_end": _NULLABLE_INT,
    },
}


def criterion_schema(criterion: Criterion) -> dict[str, Any]:
    # Порядок enum: первым идёт безопасный ответ по умолчанию (для flag это "no").
    answers = (
        ["scale"]
        if criterion.answer_type == "scale"
        else (["no", "yes"] if criterion.answer_type == "flag" else ["yes", "no"])
    )
    if criterion.allow_na:
        answers.append("na")
    scale_schema: dict[str, Any] = (
        {"enum": [s.value for s in criterion.scale or []] + [None]}
        if criterion.answer_type == "scale"
        else {"type": "null"}
    )
    na_ref: dict[str, Any] = (
        {"enum": [criterion.na_condition, None]} if criterion.allow_na else {"type": "null"}
    )
    return {
        "type": "object",
        "title": criterion.title,
        "additionalProperties": False,
        "required": sorted(ANSWER_KEYS),
        "properties": {
            "answer": {"type": "string", "enum": answers},
            "scale_value": scale_schema,
            "explanation": {"type": "string", "minLength": 1},
            "evidence": {"type": "array", "items": _EVIDENCE_SCHEMA},
            "na_condition_ref": na_ref,
        },
    }


def build_tool_schema(criteria: list[Criterion]) -> dict[str, Any]:
    """Схема input_schema tool'а: объект с ключами по criterion.id, все обязательные."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [c.id for c in criteria],
        "properties": {c.id: criterion_schema(c) for c in criteria},
    }


@dataclass
class ParseOutcome:
    ok: dict[str, CriterionResult] = field(default_factory=dict)
    errors: dict[str, list[CriterionError]] = field(default_factory=dict)


def parse_tool_input(tool_input: Any, criteria: list[Criterion], turns: list[Turn]) -> ParseOutcome:
    """Разбор ответа в CriterionResult. Каждый запрошенный критерий попадает в ok или в errors.

    Нет tool-блока или объект не по схеме: ошибка всех запрошенных критериев.
    """
    out = ParseOutcome()
    ids = {c.id for c in criteria}
    if tool_input is None:
        code, msg = E.NO_TOOL_BLOCK, "Ответ без вызова инструмента: верните оценку через tool."
    elif not isinstance(tool_input, dict) or not set(tool_input) <= ids:
        code, msg = E.BAD_SHAPE, "Ответ не по схеме: лишние или некорректные ключи верхнего уровня."
    else:
        for c in criteria:
            if c.id not in tool_input:
                out.errors[c.id] = [CriterionError(c.id, E.MISSING, "Критерий пропущен в ответе.")]
                continue
            result, errs = check_answer(c, tool_input[c.id], turns)
            if result is not None:
                out.ok[c.id] = result
            else:
                out.errors[c.id] = errs
        return out
    for c in criteria:
        out.errors[c.id] = [CriterionError(c.id, code, msg)]
    return out
