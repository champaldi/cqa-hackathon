"""Сценарии с одним смыслом на RU и KZ, разные формулировки. Модель заменяет ScriptedClient.

Проверяется поток, а не точность оценок модели: одинаковые ответы на двух языках дают одинаковые результаты,
цитаты на казахском проходят нормализацию и сохраняются точным срезом оригинала, реплики оператора коллеге
на удержании доходят до модели и могут быть доказательством, балл и грубая ошибка считаются одинаково.

Диалоги синтетические. Казахский текст требует проверки человеком, который читает по-казахски.
"""

import json
from typing import Any

import pytest

from backend.app.contracts import Checklist, CriterionResult, Dialog, Turn
from backend.app.evaluator import evaluate
from backend.app.evaluator.client import LLMResponse, Prices
from backend.app.evaluator.prompt import build_system_prompt, build_user_message
from backend.app.scoring.engine import score

LANGS = ("RU", "KZ")

# Реплики: (speaker, RU, KZ). Оператор отвечает коллеге на удержании тоже как speaker=operator.
SCENARIOS: dict[str, list[tuple[str, str, str]]] = {
    "hold_consultation": [
        (
            "client",
            "Какая комиссия за внебиржевую сделку?",
            "Биржадан тыс мәміле үшін комиссия қанша болады?",
        ),
        ("operator", "Минуту, уточню у коллеги.", "Бір минут күте тұрыңыз, әріптесімнен нақтылап көремін."),
        (
            "operator",
            "Коллега, клиент спрашивает комиссию за внебиржевую сделку, у нас какая?",
            "Әріптес, клиент биржадан тыс мәміленің комиссиясын сұрап тұр, бізде қанша?",
        ),
        (
            "operator",
            "Зависит от суммы, всё в разделе тарифов.",
            "Сомаға байланысты, тарифтер бөлімінде жазылған.",
        ),
        (
            "operator",
            "Спасибо, что подождали. Комиссия зависит от суммы сделки, полная таблица в разделе «Тарифы».",
            "Күткеніңіз үшін рахмет. Комиссия мәміле сомасына байланысты, толық кесте «Тарифтер» бөлімінде.",
        ),
        ("client", "Спасибо, понятно.", "Рахмет, түсінікті."),
    ],
    "hold_violation": [
        ("client", "Почему не проходит перевод?", "Аударым неге өтпейді?"),
        ("operator", "Минуту, посмотрю у коллеги.", "Бір минут күте тұрыңыз, әріптесіме қарап көремін."),
        (
            "operator",
            "Коллега, этот клиент ничего не понимает, надоел уже.",
            "Әріптес, бұл клиент ештеңе түсінбейді, мазасын алды.",
        ),
        (
            "operator",
            "Спасибо за ожидание. Перевод задержан из-за проверки, она займёт до часа.",
            "Күткеніңіз үшін рахмет. Аударым тексеруге байланысты кешікті, бір сағатқа дейін созылады.",
        ),
        ("client", "Хорошо, подожду.", "Жақсы, күтемін."),
    ],
    "clear_but_incomplete": [
        (
            "client",
            "Как вывести деньги и что делать с остатком на D-счёте?",
            "Қаражатты қалай шығаруға болады, D-шоттағы қалдықпен не істеймін?",
        ),
        (
            "operator",
            "Откройте раздел «Поручения» и выберите «Вывод средств».",
            "«Тапсырмалар» бөлімін ашып, «Қаражатты шығару» тармағын таңдаңыз.",
        ),
        ("client", "Спасибо.", "Рахмет."),
    ],
}

# Ответы сценария: id критерия -> (answer, scale_value, evidence).
# Остальные критерии получают ответ по умолчанию.
# evidence: ("quote", индекс реплики, {язык: цитата}) или ("range", начало, конец).
QUOTES_FINAL = {
    "RU": "Комиссия зависит от суммы сделки",
    "KZ": "КОМИССИЯ МӘМІЛЕ СОМАСЫНА БАЙЛАНЫСТЫ",  # другой регистр: проверка нормализации
}
SPECS: dict[str, dict[str, tuple[str, int | None, tuple]]] = {
    "hold_consultation": {
        "c04": ("scale", 15, ("quote", 4, QUOTES_FINAL)),
        "c06": ("scale", 10, ("quote", 4, QUOTES_FINAL)),
        "c08": ("no", None, ("range", 1, 3)),  # проверен участок с репликами коллеге
    },
    "hold_violation": {
        "c04": (
            "scale",
            15,
            ("quote", 3, {"RU": "Перевод задержан из-за проверки", "KZ": "Аударым тексеруге байланысты"}),
        ),
        "c08": (
            "yes",
            None,
            ("quote", 2, {"RU": "этот клиент ничего не понимает", "KZ": "бұл клиент ештеңе түсінбейді"}),
        ),
    },
    "clear_but_incomplete": {
        "c04": (
            "scale",
            10,
            ("quote", 1, {"RU": "Откройте раздел «Поручения»", "KZ": "«Тапсырмалар» бөлімін ашып"}),
        ),
        "c06": (
            "scale",
            10,
            ("quote", 1, {"RU": "Откройте раздел «Поручения»", "KZ": "«Тапсырмалар» бөлімін ашып"}),
        ),
    },
}


def build_dialog(name: str, lang: str) -> Dialog:
    column = 1 if lang == "RU" else 2
    turns = [
        Turn(index=i, timestamp=f"2026-01-01T10:00:{i:02d}+05:00", speaker=row[0], text=row[column])
        for i, row in enumerate(SCENARIOS[name])
    ]
    return Dialog(
        conversation_id=f"scenario-{name}-{lang.lower()}",
        dataset_group_id="TEST",
        channel="voice call",
        language=lang,  # type: ignore[arg-type]
        transcript=turns,
    )


def evidence_json(spec: tuple, lang: str) -> dict[str, Any]:
    base: dict[str, Any] = {
        "kind": None,
        "turn_index": None,
        "quote": None,
        "range_start": None,
        "range_end": None,
    }
    if spec[0] == "quote":
        return base | {"kind": "quote", "turn_index": spec[1], "quote": spec[2][lang]}
    return base | {"kind": "checked_range", "range_start": spec[1], "range_end": spec[2]}


class ScriptedClient:
    """Отвечает заранее заданными ответами сценария. Запоминает запросы."""

    def __init__(self, checklist: Checklist, name: str, lang: str, last_index: int) -> None:
        self.checklist, self.spec, self.lang, self.last = checklist, SPECS[name], lang, last_index
        self.requests: list[tuple[str, str]] = []

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> LLMResponse:
        self.requests.append((system, user))
        items = []
        for c in self.checklist.criteria:
            answer, step, ev = self.spec.get(c.id) or self._default(c)
            items.append(
                {
                    "criterion_id": c.id,
                    "evidence": [evidence_json(ev, self.lang)],
                    "explanation": "Пояснение по сценарию.",
                    "answer": answer,
                    "scale_value": step,
                    "na_condition_ref": None,
                }
            )
        return LLMResponse(json.dumps({"results": items}, ensure_ascii=False), 100, 50, "end_turn")

    def _default(self, criterion: Any) -> tuple[str, int | None, tuple]:
        rng = ("range", 0, self.last)
        if criterion.answer_type == "scale":
            return "scale", criterion.scale[0].value, rng
        return "no", None, rng


def run(name: str, lang: str, checklist: Checklist) -> tuple[Dialog, ScriptedClient, list[CriterionResult]]:
    dialog = build_dialog(name, lang)
    client = ScriptedClient(checklist, name, lang, len(dialog.transcript) - 1)
    out = evaluate(dialog, checklist, client=client, model="scripted", prices=Prices())
    return dialog, client, out.results


def shape(results: list[CriterionResult]) -> list[tuple]:
    return [(r.criterion_id, r.answer, r.scale_value, [e.kind for e in r.evidence]) for r in results]


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_same_meaning_gives_same_results_score_and_gross_error(name, default_checklist):
    ru = run(name, "RU", default_checklist)
    kz = run(name, "KZ", default_checklist)
    assert shape(ru[2]) == shape(kz[2])
    ru_score, kz_score = score(default_checklist, ru[2]), score(default_checklist, kz[2])
    assert ru_score.total == kz_score.total and ru_score.gross_error == kz_score.gross_error


@pytest.mark.parametrize("name", list(SCENARIOS))
@pytest.mark.parametrize("lang", LANGS)
def test_saved_quotes_are_exact_slices_of_the_original(name, lang, default_checklist):
    dialog, _, results = run(name, lang, default_checklist)
    quotes = [e for r in results for e in r.evidence if e.kind == "quote"]
    assert quotes
    for e in quotes:
        assert e.quote in dialog.transcript[e.turn_index].text


def test_kazakh_capitals_and_apostrophe_free_normalization(default_checklist):
    dialog, _, results = run("hold_consultation", "KZ", default_checklist)
    c04 = next(r for r in results if r.criterion_id == "c04")
    assert c04.evidence[0].quote == "Комиссия мәміле сомасына байланысты"  # оригинал, не версия модели


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_system_prompt_is_language_independent_and_user_message_keeps_every_turn(name, default_checklist):
    ru, kz = run(name, "RU", default_checklist), run(name, "KZ", default_checklist)
    assert ru[1].requests[0][0] == kz[1].requests[0][0] == build_system_prompt(default_checklist)
    for dialog, client, _ in (ru, kz):
        user = client.requests[0][1]
        assert user == build_user_message(dialog)
        for t in dialog.transcript:  # реплики оператора коллеге не отбрасываются
            assert f"[{t.index}] {t.speaker} (" in user


@pytest.mark.parametrize("lang", LANGS)
def test_colleague_talk_during_hold_can_be_evidence_of_a_violation(lang, default_checklist):
    dialog, _, results = run("hold_violation", lang, default_checklist)
    c08 = next(r for r in results if r.criterion_id == "c08")
    assert c08.answer == "yes" and c08.evidence[0].turn_index == 2
    assert dialog.transcript[2].speaker == "operator"  # реплика оператора коллеге, не клиенту
    assert score(default_checklist, results).gross_error is True


@pytest.mark.parametrize("lang", LANGS)
def test_hold_range_is_a_valid_checked_range(lang, default_checklist):
    _, _, results = run("hold_consultation", lang, default_checklist)
    c08 = next(r for r in results if r.criterion_id == "c08")
    assert (c08.answer, c08.evidence[0].range_start, c08.evidence[0].range_end) == ("no", 1, 3)
    assert score(default_checklist, results).gross_error is False


@pytest.mark.parametrize("lang", LANGS)
def test_one_criterion_lowered_does_not_lower_another(lang, default_checklist):
    _, _, results = run("clear_but_incomplete", lang, default_checklist)
    summary = {r.criterion_id: r for r in score(default_checklist, results).criteria}
    by_id = {r.criterion_id: r for r in results}
    top = {c.id: max(s.value for s in c.scale) for c in default_checklist.criteria if c.scale}
    assert by_id["c04"].scale_value < top["c04"] and by_id["c06"].scale_value == top["c06"]
    assert summary["c06"].points == summary["c06"].effective_weight  # c06 получает полный вес
