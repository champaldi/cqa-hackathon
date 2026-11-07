"""Подсчёт баллов по правилам из docs/BRIEF.md, раздел «Порядок расчёта баллов».

1. Применим критерий с весом больше нуля и ответом не N/A. Флаги грубых ошибок весят 0.
2. «Да» даёт полный вес, «Нет» ноль, ступень шкалы пропорциональна верхней ступени.
3. Вес применимых приводится к 100: новый вес = вес * 100 / S, где S — сумма весов применимых.
   Так любой чек-лист, в том числе с суммой весов не 100, даёт максимум 100.
4. Считается точно (Fraction), итог округляется один раз до двух знаков, половина вверх.
   Секции округляются только для показа, итог из них не складывается.

Веса, шкалы и id берутся из чек-листа, в коде их нет. Сигнатуры score() и apply_decisions()
используются в backend/app/services.py.
"""

from decimal import ROUND_HALF_UP, Decimal, localcontext
from fractions import Fraction

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

HUNDRED = Fraction(100)
CENT = Decimal("0.01")


def score(checklist: Checklist, results: list[CriterionResult]) -> ScoreSummary:
    by_id = _index_results(checklist, results)
    raw = {c.id: _raw_points(c, by_id[c.id]) for c in checklist.criteria}
    applicable_weight = sum(
        (Fraction(str(c.weight)) for c in checklist.criteria if raw[c.id] is not None), Fraction(0)
    )
    factor = HUNDRED / applicable_weight if applicable_weight else Fraction(0)

    exact = {c.id: _exact_row(c, raw[c.id], factor) for c in checklist.criteria}
    rows = [
        CriterionScore(
            criterion_id=c.id,
            applicable=raw[c.id] is not None,
            base_weight=c.weight,
            effective_weight=float(exact[c.id][0]),
            points=float(exact[c.id][1]),
        )
        for c in checklist.criteria
    ]
    total = sum((points for _, points in exact.values()), Fraction(0)) if applicable_weight else None
    gross_errors = [
        c.id for c in checklist.criteria if c.answer_type == "flag" and by_id[c.id].answer == "yes"
    ]
    return ScoreSummary(
        total=_round(total) if total is not None else None,
        criteria=rows,
        sections=_score_sections(checklist, exact),
        gross_error=bool(gross_errors),
        gross_error_criteria=gross_errors,
    )


def apply_decisions(results: list[CriterionResult], appeals: list[Appeal]) -> list[CriterionResult]:
    """Возвращает финальные результаты. Исходный список и его объекты не меняются.

    Учитываются только решения «изменить». Если по критерию их несколько, берётся самое позднее.
    """
    latest: dict[str, Decision] = {}
    for appeal in appeals:
        decision = appeal.decision
        if appeal.status != "changed" or decision is None:
            continue
        current = latest.get(appeal.criterion_id)
        if current is None or decision.decided_at > current.decided_at:
            latest[appeal.criterion_id] = decision
    return [
        _with_decision(result, latest[result.criterion_id]) if result.criterion_id in latest else result
        for result in results
    ]


def _index_results(checklist: Checklist, results: list[CriterionResult]) -> dict[str, CriterionResult]:
    known = {c.id for c in checklist.criteria}
    by_id: dict[str, CriterionResult] = {}
    for result in results:
        if result.criterion_id not in known:
            raise ValueError(f"Результат для неизвестного критерия {result.criterion_id}")
        if result.criterion_id in by_id:
            raise ValueError(f"Повторный результат для критерия {result.criterion_id}")
        by_id[result.criterion_id] = result
    missing = [c.id for c in checklist.criteria if c.id not in by_id]
    if missing:
        raise ValueError(f"Нет результата для критериев: {', '.join(missing)}")
    return by_id


def _raw_points(criterion: Criterion, result: CriterionResult) -> Fraction | None:
    """Баллы до перераспределения или None, если критерий не участвует в итоге."""
    if result.answer == "scale" and result.scale_value is None:
        raise ValueError(f"Критерий {criterion.id}: ответ по шкале без ступени")
    weight = Fraction(str(criterion.weight))
    if result.answer == "na" or weight <= 0:
        return None
    if result.answer == "yes":
        return weight
    if result.answer == "no":
        return Fraction(0)
    if not criterion.scale:
        raise ValueError(f"Критерий {criterion.id}: ответ по шкале, а шкалы у критерия нет")
    top = max(step.value for step in criterion.scale)
    return weight * result.scale_value / top if top else Fraction(0)


def _exact_row(criterion: Criterion, raw: Fraction | None, factor: Fraction) -> tuple[Fraction, Fraction]:
    """Точные (вес после перераспределения, баллы) одного критерия."""
    if raw is None:
        return Fraction(0), Fraction(0)
    return Fraction(str(criterion.weight)) * factor, raw * factor


def _round(value: Fraction) -> float:
    """Два знака, точная половина вверх. Без float и встроенного round()."""
    with localcontext() as ctx:
        ctx.prec = 50
        exact = Decimal(value.numerator) / Decimal(value.denominator)
        return float(exact.quantize(CENT, rounding=ROUND_HALF_UP))


def _score_sections(checklist: Checklist, exact: dict[str, tuple[Fraction, Fraction]]) -> list[SectionScore]:
    summaries = []
    for section in checklist.sections:
        members = [exact[c.id] for c in checklist.criteria if c.section_id == section.id]
        summaries.append(
            SectionScore(
                section_id=section.id,
                title=section.title,
                points=_round(sum((points for _, points in members), Fraction(0))),
                max_points=_round(sum((weight for weight, _ in members), Fraction(0))),
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
