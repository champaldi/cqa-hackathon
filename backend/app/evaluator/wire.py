"""Wire-формат ответа модели: единая JSON-схема элемента и разбор текста в CriterionResult."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from ..contracts import Checklist, Criterion, CriterionResult, Turn
from . import errors as E
from .errors import CriterionError
from .validate import check_answer

_FENCE = re.compile(r"^```[a-zA-Z]*\s*\n?(.*?)\n?```$", re.DOTALL)


def _nullable(kind: str) -> dict[str, Any]:
    return {"anyOf": [{"type": kind}, {"type": "null"}]}


_EVIDENCE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["kind", "turn_index", "quote", "range_start", "range_end"],
    "properties": {
        "kind": {"type": "string", "enum": ["quote", "checked_range", "na_reason"]},
        "turn_index": _nullable("integer"),
        "quote": _nullable("string"),
        "range_start": _nullable("integer"),
        "range_end": _nullable("integer"),
    },
}


def build_output_schema(checklist: Checklist) -> dict[str, Any]:
    """Схема для output_config: {"results": [элемент]}, одна схема элемента на все критерии.

    Порядок полей важен: сначала основание (evidence, explanation), потом ответ. Допустимость
    answer, шагов шкалы и N/A проверяет validate.py, а не схема: схема остаётся неизменной
    между попытками (кеш) и укладывается в лимиты structured outputs (6 nullable-полей, без minLength).
    """
    item: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["criterion_id", "evidence", "explanation", "answer", "scale_value", "na_condition_ref"],
        "properties": {
            "criterion_id": {"type": "string", "enum": [c.id for c in checklist.criteria]},
            "evidence": {"type": "array", "items": _EVIDENCE_SCHEMA},
            "explanation": {"type": "string"},
            "answer": {"type": "string", "enum": ["yes", "no", "scale", "na"]},
            "scale_value": _nullable("integer"),
            "na_condition_ref": _nullable("string"),
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["results"],
        "properties": {"results": {"type": "array", "items": item}},
    }


def load_results(text: str) -> list[Any] | None:
    """Текст ответа в список элементов results. Снимает ограду ```json. None: JSON битый или не по форме."""
    body = text.strip()
    if (m := _FENCE.match(body)) is not None:
        body = m.group(1).strip()
    try:
        data = json.loads(body)
    except ValueError:
        return None
    if not isinstance(data, dict) or set(data) != {"results"} or not isinstance(data["results"], list):
        return None
    return data["results"]


@dataclass
class ParseOutcome:
    ok: dict[str, CriterionResult] = field(default_factory=dict)
    errors: dict[str, list[CriterionError]] = field(default_factory=dict)


_STOP_MESSAGES = {
    "max_tokens": "Ответ оборван по лимиту токенов: верните компактный JSON без лишнего текста.",
    "refusal": "Предыдущий ответ был отклонён: оцените только оператора по данным диалога.",
}


def parse_reply(
    text: str,
    stop_reason: str | None,
    criteria: list[Criterion],
    turns: list[Turn],
    *,
    known_ids: frozenset[str],
) -> ParseOutcome:
    """Разбор ответа в CriterionResult. Каждый запрошенный критерий попадает в ok или в errors.

    stop_reason, отличный от end_turn, битый JSON, элемент без criterion_id и criterion_id вне
    чек-листа (known_ids) дают ошибку всех запрошенных критериев: такой ответ нельзя привязать к критерию.
    Элементы про критерии чек-листа вне текущего запроса (уже валидные) игнорируются, повтор их не трогает.
    """
    out = ParseOutcome()
    items: list[Any] | None = None
    if stop_reason != "end_turn":
        code, msg = (
            E.STOP_REASON,
            _STOP_MESSAGES.get(stop_reason or "", "Ответ завершён нештатно: повторите."),
        )
    elif (items := load_results(text)) is None:
        code, msg = E.BAD_JSON, 'Ответ не является JSON вида {"results": [...]}: верните только JSON.'
    elif any(not isinstance(i, dict) or not isinstance(i.get("criterion_id"), str) for i in items):
        code, msg = E.BAD_SHAPE, "Каждый элемент results должен быть объектом со строковым criterion_id."
    elif any(i["criterion_id"] not in known_ids for i in items):
        code, msg = (
            E.UNKNOWN_CRITERION,
            "В ответе есть criterion_id вне чек-листа: используйте только id из схемы.",
        )
    else:
        by_id: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            by_id.setdefault(item["criterion_id"], []).append(item)
        for c in criteria:
            found = by_id.get(c.id, [])
            if not found:
                out.errors[c.id] = [CriterionError(c.id, E.MISSING, "Критерий пропущен в ответе.")]
            elif len(found) > 1:
                out.errors[c.id] = [
                    CriterionError(c.id, E.DUPLICATE, "Критерий встречается больше одного раза.")
                ]
            else:
                raw = {k: v for k, v in found[0].items() if k != "criterion_id"}
                result, errs = check_answer(c, raw, turns)
                if result is not None:
                    out.ok[c.id] = result
                else:
                    out.errors[c.id] = errs
        return out
    for c in criteria:
        out.errors[c.id] = [CriterionError(c.id, code, msg)]
    return out
