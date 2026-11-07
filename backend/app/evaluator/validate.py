"""Детерминированная проверка ответа модели. Чистые функции: без LLM, сети и I/O.

Проверяется структура. Смысл ответа проверяют эталон и апелляции.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Any

from ..contracts import Checklist, Criterion, CriterionResult, Evidence, Turn
from . import errors as E
from .errors import CriterionError
from .render import unescape

ANSWER_KEYS = frozenset({"answer", "scale_value", "explanation", "evidence", "na_condition_ref"})
EVIDENCE_KEYS = frozenset({"kind", "turn_index", "quote", "range_start", "range_end"})

_QUOTES = dict.fromkeys("«»“”„‟\"‹›‘’‚‛'`", '"')
_DASHES = dict.fromkeys("-‐‑‒–—―−", "-")
_ARROWS = dict.fromkeys("→➔➜➞➝➡⟶⇒", "->")


def collapse_ws(text: str) -> str:
    return " ".join(text.split())


def normalize_with_map(text: str) -> tuple[str, list[tuple[int, int]]]:
    """Нормализация для поиска цитат: NFKC, пробелы, кавычки, тире, стрелки, ё/е, casefold.

    Возвращает нормализованную строку и для каждого её символа диапазон в исходном тексте.
    """
    norm: list[str] = []
    origins: list[tuple[int, int]] = []
    prev_space = False
    i, n = 0, len(text)
    while i < n:
        j = i + 1
        while j < n and unicodedata.combining(text[j]):
            j += 1
        chunk = unicodedata.normalize("NFKC", text[i:j])
        if chunk.isspace():
            if prev_space:
                origins[-1] = (origins[-1][0], j)
            else:
                norm.append(" ")
                origins.append((i, j))
                prev_space = True
        else:
            prev_space = False
            for ch in chunk:
                ch = _ARROWS.get(ch) or _QUOTES.get(ch) or _DASHES.get(ch) or ch
                for c in ch.casefold().replace("ё", "е"):
                    norm.append(c)
                    origins.append((i, j))
        i = j
    return "".join(norm), origins


def find_quote(text: str, quote: str) -> str | None:
    """Точный срез оригинала `text`, которому соответствует `quote`, или None."""
    needle = normalize_with_map(quote)[0].strip()
    if not needle:
        return None
    haystack, origins = normalize_with_map(text)
    pos = haystack.find(needle)
    if pos < 0:
        return None
    return text[origins[pos][0] : origins[pos + len(needle) - 1][1]]


def has_cyrillic(text: str) -> bool:
    return any("Ѐ" <= ch <= "ӿ" for ch in text)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


@dataclass
class _Ctx:
    criterion: Criterion
    turns: list[Turn]
    errors: list[CriterionError]

    def fail(self, code: str, message: str) -> None:
        self.errors.append(CriterionError(self.criterion.id, code, message))


def _check_turn_index(ctx: _Ctx, value: Any) -> bool:
    if not _is_int(value) or not any(t.index == value for t in ctx.turns):
        ctx.fail(E.TURN_INDEX_OUT_OF_RANGE, "turn_index вне диапазона реплик диалога.")
        return False
    return True


def _check_range(ctx: _Ctx, start: Any, end: Any) -> bool:
    if not (_is_int(start) and _is_int(end) and 0 <= start <= end <= len(ctx.turns) - 1):
        ctx.fail(E.RANGE_INVALID, "Нужно 0 <= range_start <= range_end <= последний индекс реплики.")
        return False
    return True


def _check_evidence(ctx: _Ctx, raw: Any) -> Evidence | None:
    if not isinstance(raw, dict) or not set(raw) <= EVIDENCE_KEYS:
        ctx.fail(E.BAD_SHAPE, "Доказательство должно быть объектом с полями схемы.")
        return None
    kind = raw.get("kind")
    ti, quote = raw.get("turn_index"), raw.get("quote")
    rs, re_ = raw.get("range_start"), raw.get("range_end")
    if kind == "quote":
        if rs is not None or re_ is not None:
            ctx.fail(E.EVIDENCE_FIELDS_INVALID, "У цитаты поля range_start и range_end должны быть null.")
            return None
        if not _check_turn_index(ctx, ti):
            return None
        if not isinstance(quote, str) or not quote.strip():
            ctx.fail(E.QUOTE_REQUIRED, "У цитаты нужен непустой текст quote.")
            return None
        turn = next(t for t in ctx.turns if t.index == ti)
        exact = find_quote(turn.text, quote)
        if exact is None and (unescaped := unescape(quote)) != quote:
            exact = find_quote(turn.text, unescaped)
        if exact is None:
            if "…" in quote or "..." in quote:
                ctx.fail(
                    E.QUOTE_ELLIPSIS, "Цитата с многоточием недопустима: цитируйте один цельный фрагмент."
                )
            else:
                ctx.fail(
                    E.QUOTE_NOT_FOUND, "Цитаты нет дословно в указанной реплике (без перефраза и перевода)."
                )
            return None
        return Evidence(kind="quote", turn_index=ti, quote=exact)
    if kind == "checked_range":
        if ti is not None or quote is not None:
            ctx.fail(E.EVIDENCE_FIELDS_INVALID, "У checked_range turn_index и quote должны быть null.")
            return None
        if not _check_range(ctx, rs, re_):
            return None
        return Evidence(kind="checked_range", range_start=rs, range_end=re_)
    if kind == "na_reason":
        if quote is not None:
            ctx.fail(E.EVIDENCE_FIELDS_INVALID, "У na_reason поле quote должно быть null.")
            return None
        if ti is None and rs is None and re_ is None:
            ctx.fail(E.NA_REASON_MISSING, "na_reason должен указывать реплику или диапазон.")
            return None
        if ti is not None and not _check_turn_index(ctx, ti):
            return None
        if (rs is not None or re_ is not None) and not _check_range(ctx, rs, re_):
            return None
        return Evidence(kind="na_reason", turn_index=ti, range_start=rs, range_end=re_)
    ctx.fail(E.EVIDENCE_KIND_INVALID, "kind доказательства: quote, checked_range или na_reason.")
    return None


def allowed_answers(criterion: Criterion) -> list[str]:
    base = ["scale"] if criterion.answer_type == "scale" else ["yes", "no"]
    return base + (["na"] if criterion.allow_na else [])


def check_answer(
    criterion: Criterion, raw: Any, turns: list[Turn]
) -> tuple[CriterionResult | None, list[CriterionError]]:
    """Проверяет один критерий. Возвращает результат с точными цитатами или список ошибок."""
    errors: list[CriterionError] = []
    ctx = _Ctx(criterion, turns, errors)
    if not isinstance(raw, dict) or set(raw) != ANSWER_KEYS:
        ctx.fail(E.BAD_SHAPE, "Ответ по критерию не соответствует схеме: нужны ровно поля из схемы.")
        return None, errors

    answer = raw["answer"]
    if answer == "na" and not criterion.allow_na:
        ctx.fail(E.NA_NOT_ALLOWED, "N/A для этого критерия недопустим.")
    elif answer not in allowed_answers(criterion):
        ctx.fail(E.ANSWER_INVALID, f"answer допустим из: {', '.join(allowed_answers(criterion))}.")

    scale_value = raw["scale_value"]
    if answer == "scale":
        steps = {s.value for s in criterion.scale or []}
        if not _is_int(scale_value) or scale_value not in steps:
            ctx.fail(E.SCALE_STEP_INVALID, f"scale_value должен быть шагом шкалы: {sorted(steps)}.")
    elif scale_value is not None:
        ctx.fail(E.SCALE_VALUE_NOT_ALLOWED, "scale_value должен быть null, если answer не scale.")

    explanation = raw["explanation"]
    if not isinstance(explanation, str) or not explanation.strip():
        ctx.fail(E.EXPLANATION_EMPTY, "explanation не должен быть пустым.")

    raw_evidence = raw["evidence"]
    evidence: list[Evidence] = []
    if not isinstance(raw_evidence, list):
        ctx.fail(E.BAD_SHAPE, "evidence должен быть массивом.")
    else:
        for item in raw_evidence:
            ev = _check_evidence(ctx, item)
            if ev is not None:
                evidence.append(ev)

    has_bad_evidence = isinstance(raw_evidence, list) and len(evidence) != len(raw_evidence)
    if answer == "na":
        ref = raw["na_condition_ref"]
        expected = collapse_ws(criterion.na_condition or "")
        if not isinstance(ref, str) or collapse_ws(ref) != expected:
            ctx.fail(E.NA_CONDITION_MISMATCH, "na_condition_ref должен совпадать с условием N/A критерия.")
        if not any(e.kind == "na_reason" for e in evidence) and not has_bad_evidence:
            ctx.fail(E.NA_REASON_MISSING, "Для N/A нужен na_reason с указанием реплики или диапазона.")
    elif answer in allowed_answers(criterion):
        if any(e.kind == "na_reason" for e in evidence):
            ctx.fail(E.NA_REASON_UNEXPECTED, "na_reason допустим только при answer = na.")
        if not any(e.kind in ("quote", "checked_range") for e in evidence) and not has_bad_evidence:
            ctx.fail(E.EVIDENCE_MISSING, "Нужно хотя бы одно доказательство: quote или checked_range.")
        elif answer == "yes" and not any(e.kind == "quote" for e in evidence) and not has_bad_evidence:
            ctx.fail(E.QUOTE_REQUIRED, "Ответ yes подтверждается цитатой (quote), а не только участком.")

    if errors:
        return None, errors
    return (
        CriterionResult(
            criterion_id=criterion.id,
            answer=answer,
            scale_value=scale_value if answer == "scale" else None,
            explanation=explanation.strip(),
            evidence=evidence,
        ),
        [],
    )


def validate_complete(
    results: list[CriterionResult], checklist: Checklist, turns: list[Turn]
) -> list[CriterionError]:
    """Полная проверка объединённого результата: порядок, ровно один раз, каждый критерий валиден."""
    errors: list[CriterionError] = []
    known = {c.id: c for c in checklist.criteria}
    seen: dict[str, int] = {}
    for r in results:
        seen[r.criterion_id] = seen.get(r.criterion_id, 0) + 1
        if r.criterion_id not in known:
            errors.append(CriterionError(r.criterion_id, E.UNKNOWN_CRITERION, "Критерия нет в чек-листе."))
    for cid, count in seen.items():
        if count > 1 and cid in known:
            errors.append(CriterionError(cid, E.DUPLICATE, "Критерий встречается больше одного раза."))
    for cid in known:
        if cid not in seen:
            errors.append(CriterionError(cid, E.MISSING, "Критерий пропущен."))
    if errors:
        return errors
    if [r.criterion_id for r in results] != [c.id for c in checklist.criteria]:
        return [CriterionError("", E.BAD_SHAPE, "Порядок результатов не совпадает с чек-листом.")]
    for r in results:
        criterion = known[r.criterion_id]
        raw = {
            "answer": r.answer,
            "scale_value": r.scale_value,
            "explanation": r.explanation,
            "evidence": [e.model_dump() for e in r.evidence],
            "na_condition_ref": criterion.na_condition if r.answer == "na" else None,
        }
        errors.extend(check_answer(criterion, raw, turns)[1])
    return errors
