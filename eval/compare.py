"""Сравнение оценок модели с ручным эталоном. Модель не вызывается: читаются уже готовые оценки.

Запуск:
    python -m eval.compare --gold data/gold/gold.json --api http://127.0.0.1:8000 \
        --save-model data/gold/model.json
    python -m eval.compare --gold data/gold/gold.json --model data/gold/model.json

Форматы входа описаны в eval/README.md. Эталон и выгрузка модели содержат id диалогов,
поэтому лежат только в data/ и в git не попадают.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from backend.app.contracts import Checklist, CriterionResult
from backend.app.scoring.engine import score

ANSWER_ALIASES = {"yes": "yes", "no": "no", "na": "na", "n/a": "na", "да": "yes", "нет": "no"}

# Виды расхождений по одному критерию
MATCH = "match"
MISSING = "missing"  # у модели нет результата по критерию эталона
NA_MISSED = "na_missed"  # в эталоне N/A, модель поставила ответ
NA_FALSE = "na_false"  # модель поставила N/A, в эталоне ответ
SCALE_STEP = "scale_step"  # обе шкалы, ступени разные
ANSWER = "answer"  # да/нет перепутаны или ответ другого вида


@dataclass(frozen=True)
class Answer:
    answer: str  # yes, no, na, scale
    scale_value: int | None = None

    def label(self) -> str:
        return str(self.scale_value) if self.answer == "scale" else self.answer


@dataclass(frozen=True)
class GoldDialog:
    conversation_id: str
    language: str
    channel: str
    answers: dict[str, Answer]
    doubtful: frozenset[str]  # критерии со спорной разметкой
    total: float | None = None
    gross_error: bool | None = None


@dataclass(frozen=True)
class ModelDialog:
    conversation_id: str
    answers: dict[str, Answer]
    total: float | None
    gross_error: bool
    checklist: Checklist | None = None


@dataclass
class Tally:
    match: int = 0
    total: int = 0

    def add(self, ok: bool) -> None:
        self.match += ok
        self.total += 1

    @property
    def rate(self) -> float | None:
        return round(100 * self.match / self.total, 1) if self.total else None


@dataclass
class Row:
    conversation_id: str
    language: str
    channel: str
    criterion_id: str
    gold: str
    model: str | None
    kind: str
    doubtful: bool


@dataclass
class Report:
    rows: list[Row] = field(default_factory=list)
    overall: Tally = field(default_factory=Tally)
    doubtful: Tally = field(default_factory=Tally)
    by_criterion: dict[str, Tally] = field(default_factory=dict)
    by_language: dict[str, Tally] = field(default_factory=dict)
    by_channel: dict[str, Tally] = field(default_factory=dict)
    kinds: dict[str, int] = field(default_factory=dict)
    totals: list[dict[str, Any]] = field(default_factory=list)
    gross: Tally = field(default_factory=Tally)
    missing_dialogs: list[str] = field(default_factory=list)
    checklist_mismatch: list[str] = field(
        default_factory=list
    )  # модель оценивала по другому набору критериев


# ---------- Разбор входа ----------


def parse_answer(value: Any, where: str) -> Answer:
    """Ответ эталона: "yes"/"no"/"na", число ступени или {"answer": ..., "scale_value": ...}."""
    if isinstance(value, dict):
        if value.get("answer") == "scale":
            return parse_answer(value.get("scale_value"), where)
        return parse_answer(value.get("answer"), where)
    if isinstance(value, bool):
        raise ValueError(f"{where}: ответ должен быть yes, no, na или ступенью шкалы")
    if isinstance(value, int):
        if value < 0:
            raise ValueError(f"{where}: ступень шкалы не может быть отрицательной")
        return Answer("scale", value)
    if isinstance(value, str) and value.strip().lower() in ANSWER_ALIASES:
        return Answer(ANSWER_ALIASES[value.strip().lower()])
    raise ValueError(f"{where}: непонятный ответ {value!r}")


def load_gold(data: dict[str, Any]) -> list[GoldDialog]:
    dialogs = data.get("dialogs")
    if not isinstance(dialogs, list) or not dialogs:
        raise ValueError("В эталоне нет списка dialogs")
    result: list[GoldDialog] = []
    seen: set[str] = set()
    for index, raw in enumerate(dialogs):
        cid = raw.get("conversation_id")
        if not cid:
            raise ValueError(f"Эталон, запись {index}: нет conversation_id")
        if cid in seen:
            raise ValueError(f"Эталон: диалог {cid} размечен дважды")
        seen.add(cid)
        criteria = raw.get("criteria") or {}
        if not criteria:
            raise ValueError(f"Эталон, {cid}: нет ответов по критериям")
        answers = {crit: parse_answer(value, f"{cid}/{crit}") for crit, value in criteria.items()}
        doubtful = {
            crit for crit, value in criteria.items() if isinstance(value, dict) and value.get("doubtful")
        }
        if raw.get("doubtful") is True:
            doubtful = set(criteria)
        doubtful |= set(raw.get("doubtful_criteria") or [])
        result.append(
            GoldDialog(
                conversation_id=cid,
                language=raw.get("language") or "?",
                channel=raw.get("channel") or "?",
                answers=answers,
                doubtful=frozenset(doubtful),
                total=raw.get("total"),
                gross_error=raw.get("gross_error"),
            )
        )
    return result


def _answer_of(result: CriterionResult) -> Answer:
    return Answer(result.answer, result.scale_value if result.answer == "scale" else None)


def model_from_card(card: dict[str, Any]) -> ModelDialog:
    """Карточка из GET /api/evaluations/{id}. Берётся исходная оценка модели, без решений по апелляциям."""
    evaluation = card["evaluation"]
    results = [CriterionResult.model_validate(item) for item in evaluation["results"]]
    summary = evaluation["score"]
    return ModelDialog(
        conversation_id=evaluation["conversation_id"],
        answers={result.criterion_id: _answer_of(result) for result in results},
        total=summary.get("total"),
        gross_error=bool(summary.get("gross_error")),
        checklist=Checklist.model_validate(card["checklist"]) if card.get("checklist") else None,
    )


def load_model(cards: Iterable[dict[str, Any]]) -> dict[str, ModelDialog]:
    dialogs: dict[str, ModelDialog] = {}
    for card in cards:
        dialog = model_from_card(card)
        dialogs[dialog.conversation_id] = dialog
    return dialogs


# ---------- Сравнение ----------


def classify(gold: Answer, model: Answer | None) -> str:
    if model is None:
        return MISSING
    if gold == model:
        return MATCH
    if gold.answer == "na":
        return NA_MISSED
    if model.answer == "na":
        return NA_FALSE
    if gold.answer == "scale" and model.answer == "scale":
        return SCALE_STEP
    return ANSWER


def gold_total(gold: GoldDialog, checklist: Checklist | None) -> float | None:
    """Итог эталона тем же движком подсчёта. Если чек-лист не подходит, берётся total из файла."""
    if checklist is None or {c.id for c in checklist.criteria} != set(gold.answers):
        return gold.total
    results = [
        CriterionResult(
            criterion_id=crit,
            answer=answer.answer,  # type: ignore[arg-type]
            scale_value=answer.scale_value,
            explanation="Эталон",
        )
        for crit, answer in gold.answers.items()
    ]
    return score(checklist, results).total


def _gold_gross(gold: GoldDialog, checklist: Checklist | None) -> bool | None:
    if gold.gross_error is not None:
        return gold.gross_error
    if checklist is None:
        return None
    flags = [c.id for c in checklist.criteria if c.answer_type == "flag"]
    return any(gold.answers.get(flag) == Answer("yes") for flag in flags)


def compare(
    gold: list[GoldDialog], model: dict[str, ModelDialog], checklist: Checklist | None = None
) -> Report:
    report = Report()
    for item in gold:
        found = model.get(item.conversation_id)
        if found is None:
            report.missing_dialogs.append(item.conversation_id)
            continue
        dialog_checklist = found.checklist or checklist
        if found.checklist and {c.id for c in found.checklist.criteria} != set(item.answers):
            report.checklist_mismatch.append(item.conversation_id)
        for crit, expected in item.answers.items():
            actual = found.answers.get(crit)
            kind = classify(expected, actual)
            is_doubtful = crit in item.doubtful
            report.rows.append(
                Row(
                    conversation_id=item.conversation_id,
                    language=item.language,
                    channel=item.channel,
                    criterion_id=crit,
                    gold=expected.label(),
                    model=actual.label() if actual else None,
                    kind=kind,
                    doubtful=is_doubtful,
                )
            )
            ok = kind == MATCH
            if is_doubtful:
                report.doubtful.add(ok)
                continue
            report.overall.add(ok)
            report.by_criterion.setdefault(crit, Tally()).add(ok)
            report.by_language.setdefault(item.language, Tally()).add(ok)
            report.by_channel.setdefault(item.channel, Tally()).add(ok)
            if not ok:
                report.kinds[kind] = report.kinds.get(kind, 0) + 1

        expected_total = gold_total(item, dialog_checklist)
        diff = (
            round(found.total - expected_total, 2)
            if found.total is not None and expected_total is not None
            else None
        )
        report.totals.append(
            {
                "conversation_id": item.conversation_id,
                "gold": expected_total,
                "model": found.total,
                "diff": diff,
            }
        )
        expected_gross = _gold_gross(item, dialog_checklist)
        if expected_gross is not None:
            report.gross.add(expected_gross == found.gross_error)
    return report


# ---------- Вывод ----------

KIND_TITLES = {
    NA_MISSED: "в эталоне N/A, модель ответила",
    NA_FALSE: "модель поставила N/A без причины",
    SCALE_STEP: "другая ступень шкалы",
    ANSWER: "да и нет перепутаны",
    MISSING: "нет результата модели",
}


def _rate(tally: Tally) -> str:
    return f"{tally.match}/{tally.total} ({tally.rate}%)" if tally.total else "нет данных"


def render(report: Report) -> str:
    lines = ["Сравнение модели с эталоном", ""]
    lines.append(f"Совпадение по критериям (без спорных): {_rate(report.overall)}")
    lines.append(f"Спорные случаи (doubtful), отдельно: {_rate(report.doubtful)}")
    lines.append(f"Грубая ошибка определена верно: {_rate(report.gross)}")
    diffs = [abs(row["diff"]) for row in report.totals if row["diff"] is not None]
    if diffs:
        lines.append(
            f"Итоговый балл: средняя разница {sum(diffs) / len(diffs):.2f}, "
            f"максимальная {max(diffs):.2f}, совпало точно {sum(d == 0 for d in diffs)}/{len(diffs)}"
        )
    if report.missing_dialogs:
        lines.append(f"Нет оценки модели для {len(report.missing_dialogs)} диалогов эталона")
    if report.checklist_mismatch:
        lines.append(
            "Внимание: критерии чек-листа модели не совпадают с эталоном у "
            f"{', '.join(report.checklist_mismatch)}. Оцените эти диалоги заново по нужной версии."
        )

    for title, groups in (
        ("По критериям", report.by_criterion),
        ("По языкам", report.by_language),
        ("По каналам", report.by_channel),
    ):
        lines += ["", title]
        lines += [f"  {key}: {_rate(tally)}" for key, tally in sorted(groups.items())]

    if report.kinds:
        lines += ["", "Виды расхождений"]
        lines += [f"  {KIND_TITLES[kind]}: {count}" for kind, count in sorted(report.kinds.items())]

    mismatches = [row for row in report.rows if row.kind != MATCH]
    if mismatches:
        lines += ["", "Расхождения (эталон → модель)"]
        for row in mismatches:
            mark = " [спорный]" if row.doubtful else ""
            lines.append(f"  {row.conversation_id} {row.criterion_id}: {row.gold} → {row.model or '—'}{mark}")
    return "\n".join(lines)


def to_json(report: Report) -> dict[str, Any]:
    data = asdict(report)
    for key in ("overall", "doubtful", "gross"):
        data[key]["rate"] = getattr(report, key).rate
    for key in ("by_criterion", "by_language", "by_channel"):
        for name, tally in getattr(report, key).items():
            data[key][name]["rate"] = tally.rate
    return data


# ---------- Источники оценок модели ----------


def _get_json(url: str) -> Any:
    with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310 - адрес задаёт пользователь
        envelope = json.loads(response.read())
    if not envelope.get("success"):
        raise RuntimeError(f"{url}: {envelope.get('error')}")
    return envelope["data"]


def fetch_cards(api: str, conversation_ids: Iterable[str]) -> list[dict[str, Any]]:
    """Последние сохранённые оценки из запущенного приложения. Новых оценок не создаёт."""
    base = api.rstrip("/")
    summaries = {row["conversation_id"]: row for row in _get_json(f"{base}/api/dialogs")}
    cards = []
    for cid in conversation_ids:
        evaluation_id = (summaries.get(cid) or {}).get("evaluation_id")
        if evaluation_id:
            cards.append(_get_json(f"{base}/api/evaluations/{evaluation_id}"))
    return cards


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Сравнение оценок модели с ручным эталоном")
    parser.add_argument("--gold", required=True, type=Path, help="Файл эталона, например data/gold/gold.json")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--model", type=Path, help="Сохранённые карточки оценок (JSON-список)")
    source.add_argument("--api", help="Адрес запущенного приложения, например http://127.0.0.1:8000")
    parser.add_argument("--save-model", type=Path, help="Сохранить полученные из --api карточки в файл")
    parser.add_argument("--checklist", type=Path, help="Чек-лист для итога эталона, если в карточках его нет")
    parser.add_argument("--json", type=Path, help="Записать отчёт в JSON")
    args = parser.parse_args(argv)

    gold = load_gold(json.loads(args.gold.read_text(encoding="utf-8")))
    if args.api:
        cards = fetch_cards(args.api, [item.conversation_id for item in gold])
        if args.save_model:
            args.save_model.parent.mkdir(parents=True, exist_ok=True)
            args.save_model.write_text(json.dumps(cards, ensure_ascii=False, indent=1), encoding="utf-8")
    else:
        cards = json.loads(args.model.read_text(encoding="utf-8"))
    checklist = None
    if args.checklist:
        raw = json.loads(args.checklist.read_text(encoding="utf-8"))
        checklist = Checklist.model_validate({"id": "file", "version": 0, **raw})

    report = compare(gold, load_model(cards), checklist)
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    print(render(report))
    if args.json:
        args.json.write_text(json.dumps(to_json(report), ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
