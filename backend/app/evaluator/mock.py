"""Оценщик-заглушка: без модели, ключа и затрат.

Ответ зависит только от id диалога и критерия, поэтому повторный запуск даёт тот же
результат. Решения принимаются по настройкам критерия, а не по его названию: любой
новый критерий работает без правки кода. Смысл диалога заглушка не анализирует.
"""

import hashlib

from backend.app.contracts import (
    Checklist,
    Criterion,
    CriterionResult,
    Dialog,
    EvaluatorOutput,
    Evidence,
    Turn,
    Usage,
)

NOTE = "Заглушка, диалог не анализировался"
QUOTE_LIMIT = 120
NA_EVERY = 4
YES_EVERY = 2
GROSS_ERROR_EVERY = 16


class MockEvaluator:
    def evaluate(self, dialog: Dialog, checklist: Checklist) -> EvaluatorOutput:
        operator_turns = [turn for turn in dialog.transcript if turn.speaker == "operator"]
        results = [_judge(dialog, operator_turns, criterion) for criterion in checklist.criteria]
        return EvaluatorOutput(results=results, usage=Usage(model="mock"))


def _stable_number(conversation_id: str, criterion_id: str) -> int:
    digest = hashlib.sha256(f"{conversation_id}:{criterion_id}".encode()).digest()
    return int.from_bytes(digest[:4], "big")


def _judge(dialog: Dialog, operator_turns: list[Turn], criterion: Criterion) -> CriterionResult:
    number = _stable_number(dialog.conversation_id, criterion.id)
    if criterion.allow_na and (not operator_turns or number % NA_EVERY == 0):
        return _not_applicable(criterion)

    checked = [_checked_range(dialog)]
    quoted = [_quote(operator_turns[number % len(operator_turns)])] if operator_turns else checked
    if criterion.answer_type == "scale":
        return _on_scale(criterion, number if operator_turns else 0, quoted)

    every = GROSS_ERROR_EVERY if criterion.answer_type == "flag" else YES_EVERY
    if operator_turns and number % every == 0:
        return _answered(criterion, "yes", quoted)
    return _answered(criterion, "no", checked)


def _quote(turn: Turn) -> Evidence:
    return Evidence(kind="quote", turn_index=turn.index, quote=turn.text[:QUOTE_LIMIT])


def _checked_range(dialog: Dialog) -> Evidence:
    return Evidence(kind="checked_range", range_start=0, range_end=max(len(dialog.transcript) - 1, 0))


def _not_applicable(criterion: Criterion) -> CriterionResult:
    return CriterionResult(
        criterion_id=criterion.id,
        answer="na",
        explanation=f"{NOTE}. Условие N/A: {criterion.na_condition}",
        evidence=[Evidence(kind="na_reason")],
    )


def _on_scale(criterion: Criterion, number: int, evidence: list[Evidence]) -> CriterionResult:
    steps = sorted(step.value for step in criterion.scale or [])
    value = steps[number % len(steps)]
    return CriterionResult(
        criterion_id=criterion.id,
        answer="scale",
        scale_value=value,
        explanation=f"{NOTE}. Выбрана ступень {value}.",
        evidence=evidence,
    )


def _answered(criterion: Criterion, answer: str, evidence: list[Evidence]) -> CriterionResult:
    return CriterionResult(
        criterion_id=criterion.id,
        answer=answer,
        explanation=f"{NOTE}. Ответ: {'да' if answer == 'yes' else 'нет'}.",
        evidence=evidence,
    )
