"""Подсчёт баллов. ЗАГЛУШКА, форма результата настоящая, формулы упрощены.

Задача qa/scoring-engine добавляет правила из docs/BRIEF.md: перераспределение веса N/A
между применимыми критериями, максимум 100 баллов и точное округление. Сейчас N/A просто
исключается и итог не приводится к 100. Сигнатуры функций менять нельзя: на них опирается
backend/app/services.py.
"""

from backend.app.contracts import (
    Appeal,
    Checklist,
    Criterion,
    CriterionResult,
    CriterionScore,
    Decision,
    ScoreSummary,
    SectionScore,
)


def score(checklist: Checklist, results: list[CriterionResult]) -> ScoreSummary:
    by_id = {result.criterion_id: result for result in results}
    rows = [_score_criterion(criterion, by_id.get(criterion.id)) for criterion in checklist.criteria]
    applicable = [row for row in rows if row.applicable]
    gross_errors = [
        criterion.id
        for criterion in checklist.criteria
        if criterion.answer_type == "flag" and _answer(by_id.get(criterion.id)) == "yes"
    ]
    return ScoreSummary(
        total=round(sum(row.points for row in applicable), 2) if applicable else None,
        criteria=rows,
        sections=_score_sections(checklist, rows),
        gross_error=bool(gross_errors),
        gross_error_criteria=gross_errors,
    )


def apply_decisions(results: list[CriterionResult], appeals: list[Appeal]) -> list[CriterionResult]:
    """Возвращает финальные результаты. Исходный список не меняется."""
    changes = {a.criterion_id: a.decision for a in appeals if a.status == "changed" and a.decision}
    return [
        _with_decision(result, changes[result.criterion_id]) if result.criterion_id in changes else result
        for result in results
    ]


def _answer(result: CriterionResult | None) -> str | None:
    return result.answer if result else None


def _score_criterion(criterion: Criterion, result: CriterionResult | None) -> CriterionScore:
    applicable = result is not None and result.answer != "na" and criterion.weight > 0
    return CriterionScore(
        criterion_id=criterion.id,
        applicable=applicable,
        base_weight=criterion.weight,
        effective_weight=criterion.weight if applicable else 0,
        points=_points(criterion, result) if applicable else 0,
    )


def _points(criterion: Criterion, result: CriterionResult) -> float:
    if result.answer == "yes":
        return criterion.weight
    if result.answer != "scale" or not criterion.scale or result.scale_value is None:
        return 0
    top = max(step.value for step in criterion.scale)
    return criterion.weight * result.scale_value / top if top else 0


def _score_sections(checklist: Checklist, rows: list[CriterionScore]) -> list[SectionScore]:
    section_of = {criterion.id: criterion.section_id for criterion in checklist.criteria}
    summaries = []
    for section in checklist.sections:
        members = [row for row in rows if section_of[row.criterion_id] == section.id]
        summaries.append(
            SectionScore(
                section_id=section.id,
                title=section.title,
                points=round(sum(row.points for row in members), 2),
                max_points=round(sum(row.effective_weight for row in members), 2),
            )
        )
    return summaries


def _with_decision(result: CriterionResult, decision: Decision) -> CriterionResult:
    return result.model_copy(
        update={
            "answer": decision.answer,
            "scale_value": decision.scale_value if decision.answer == "scale" else None,
            "explanation": f"Изменено проверяющим: {decision.reason}",
        }
    )
