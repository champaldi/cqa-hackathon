import pytest

from backend.app.contracts import Criterion, CriterionResult, Evidence, ScaleStep
from backend.app.evaluator import errors as E
from backend.app.evaluator.validate import (
    check_answer,
    find_quote,
    validate_complete,
)

from .conftest import make_turns

TURNS = make_turns(
    ("client", "Привет"),
    ("operator", "Здравствуйте!  Меня зовут  «Мира».\nОткройте раздел — «Отчёты»."),
    ("client", "Спасибо"),
)


def ev(kind="quote", **kw):
    base = {"kind": kind, "turn_index": None, "quote": None, "range_start": None, "range_end": None}
    return base | kw


def raw(answer="yes", scale_value=None, evidence=None, ref=None, explanation="Пояснение"):
    return {
        "answer": answer,
        "scale_value": scale_value,
        "explanation": explanation,
        "evidence": [ev("checked_range", range_start=0, range_end=2)] if evidence is None else evidence,
        "na_condition_ref": ref,
    }


YES_NO = Criterion(id="a", title="t", description="d", answer_type="yes_no", weight=1)
YES_NO_NA = Criterion(
    id="b",
    title="t",
    description="d",
    answer_type="yes_no",
    weight=1,
    allow_na=True,
    na_condition="Не   нужно.",
)
SCALE = Criterion(
    id="s",
    title="t",
    description="d",
    answer_type="scale",
    weight=10,
    allow_na=True,
    na_condition="Обрыв.",
    scale=[ScaleStep(value=10, label="a"), ScaleStep(value=5, label="b"), ScaleStep(value=0, label="c")],
)
FLAG = Criterion(id="f", title="t", description="d", answer_type="flag", weight=0)


def codes(c, r):
    res, errs = check_answer(c, r, TURNS)
    assert (res is None) == bool(errs)
    return {e.code for e in errs}


# --- answer_type ---


@pytest.mark.parametrize("answer", ["yes", "no"])
def test_yes_no_valid(answer):
    assert codes(YES_NO, raw(answer)) == set()


def test_yes_no_invalid_cases():
    assert E.NA_NOT_ALLOWED in codes(YES_NO, raw("na", ref="x"))
    assert codes(YES_NO, raw("maybe")) == {E.ANSWER_INVALID}
    assert codes(YES_NO, raw("scale", scale_value=3)) == {E.ANSWER_INVALID, E.SCALE_STEP_INVALID}
    assert codes(YES_NO, raw("yes", scale_value=5)) == {E.SCALE_VALUE_NOT_ALLOWED}


def test_scale_valid_and_invalid():
    assert codes(SCALE, raw("scale", 5)) == set()
    assert codes(SCALE, raw("scale", 7)) == {E.SCALE_STEP_INVALID}
    assert codes(SCALE, raw("scale", None)) == {E.SCALE_STEP_INVALID}
    assert codes(SCALE, raw("scale", True)) == {E.SCALE_STEP_INVALID}
    assert codes(SCALE, raw("yes")) == {E.ANSWER_INVALID}


def test_flag_rules():
    assert codes(FLAG, raw("no")) == set()
    q = ev(turn_index=1, quote="Откройте раздел")
    assert codes(FLAG, raw("yes", evidence=[q])) == set()
    assert codes(FLAG, raw("yes")) == {E.QUOTE_REQUIRED}  # нарушение без цитаты
    assert E.NA_NOT_ALLOWED in codes(FLAG, raw("na", ref="x"))


def test_missing_evidence_and_explanation_and_shape():
    assert codes(YES_NO, raw(evidence=[])) == {E.EVIDENCE_MISSING}
    assert codes(YES_NO, raw(explanation="  ")) == {E.EXPLANATION_EMPTY}
    r = raw()
    del r["explanation"]
    assert codes(YES_NO, r) == {E.BAD_SHAPE}
    assert codes(YES_NO, {**raw(), "extra": 1}) == {E.BAD_SHAPE}


# --- цитаты ---


def test_quote_exact_and_normalized_accepted_and_stored_as_original_slice():
    cases = [
        "Откройте раздел",
        "откройте   РАЗДЕЛ",  # регистр и пробелы
        'меня зовут "Мира"',  # кавычки и двойной пробел
        "Мира».\nОткройте",  # перевод строки как пробел
        "раздел - «Отчёты»",  # тире
        "Отчёты",  # NFC: е + диакритика
        "Отчёты".replace("ё", "ё"),
    ]
    for q in cases:
        res, errs = check_answer(YES_NO, raw(evidence=[ev(turn_index=1, quote=q)]), TURNS)
        assert not errs, (q, errs)
        saved = res.evidence[0].quote
        assert saved in TURNS[1].text, saved  # точный срез оригинала, не версия модели
    res, _ = check_answer(YES_NO, raw(evidence=[ev(turn_index=1, quote='меня зовут "мира"')]), TURNS)
    assert res.evidence[0].quote == "Меня зовут  «Мира»"


def test_find_quote_decomposed_unicode():
    text = "Привет, Отчёт"  # обычный текст
    assert find_quote("Отчёт готов", "отчёт") == "Отчёт"
    assert find_quote(text, "отчёт") == "Отчёт"


@pytest.mark.parametrize(
    ("quote", "code"),
    [
        ("Откройте страницу «Отчёты»", E.QUOTE_NOT_FOUND),  # перефраз
        ("Откройте раздел … Отчёты", E.QUOTE_ELLIPSIS),
        ("Откройте раздел...Отчёты", E.QUOTE_ELLIPSIS),
        ("Здравствуйте, Меня зовут", E.QUOTE_NOT_FOUND),  # пропуск знака/слов
        ("Hello, my name is Mira", E.QUOTE_NOT_FOUND),  # перевод
        ("   ", E.QUOTE_REQUIRED),
    ],
)
def test_bad_quotes_rejected(quote, code):
    assert codes(YES_NO, raw(evidence=[ev(turn_index=1, quote=quote)])) == {code}


def test_turn_index_and_range_bounds():
    bad = {E.TURN_INDEX_OUT_OF_RANGE}
    assert codes(YES_NO, raw(evidence=[ev(turn_index=3, quote="Спасибо")])) == bad
    assert codes(YES_NO, raw(evidence=[ev(turn_index=-1, quote="Спасибо")])) == bad
    assert codes(YES_NO, raw(evidence=[ev(turn_index=None, quote="Спасибо")])) == bad
    ok = ev("checked_range", range_start=0, range_end=2)
    assert codes(YES_NO, raw(evidence=[ok])) == set()
    for s, e in [(-1, 1), (2, 1), (0, 3)]:
        assert codes(YES_NO, raw(evidence=[ev("checked_range", range_start=s, range_end=e)])) == {
            E.RANGE_INVALID
        }
    assert codes(YES_NO, raw(evidence=[ev(turn_index=1, quote="Спасибо", range_start=0, range_end=1)])) == {
        E.EVIDENCE_FIELDS_INVALID
    }


def test_quote_in_wrong_turn_rejected():
    assert codes(YES_NO, raw(evidence=[ev(turn_index=2, quote="Откройте раздел")])) == {E.QUOTE_NOT_FOUND}


# --- N/A ---


def na(ref="Не нужно.", evidence=None):
    return raw("na", evidence=[ev("na_reason", turn_index=1)] if evidence is None else evidence, ref=ref)


def test_na_valid_with_whitespace_collapse():
    res, errs = check_answer(YES_NO_NA, na(ref="Не  нужно. "), TURNS)
    assert not errs and res.answer == "na" and res.evidence[0].kind == "na_reason"
    res, errs = check_answer(YES_NO_NA, na(evidence=[ev("na_reason", range_start=0, range_end=1)]), TURNS)
    assert not errs


def test_na_errors():
    assert codes(YES_NO_NA, na(ref=None)) == {E.NA_CONDITION_MISMATCH}
    assert codes(YES_NO_NA, na(ref="Другое условие")) == {E.NA_CONDITION_MISMATCH}
    assert codes(YES_NO_NA, na(evidence=[])) == {E.NA_REASON_MISSING}
    assert codes(YES_NO_NA, na(evidence=[ev("na_reason")])) == {E.NA_REASON_MISSING}
    assert codes(YES_NO_NA, na(evidence=[ev("na_reason", turn_index=9)])) == {E.TURN_INDEX_OUT_OF_RANGE}
    assert codes(YES_NO_NA, na(evidence=[ev("checked_range", range_start=0, range_end=1)])) == {
        E.NA_REASON_MISSING
    }
    assert codes(YES_NO_NA, raw("yes", evidence=[ev("na_reason", turn_index=1)])) == {
        E.NA_REASON_UNEXPECTED,
        E.EVIDENCE_MISSING,
    }
    assert codes(YES_NO, na()) == {E.NA_NOT_ALLOWED, E.NA_CONDITION_MISMATCH}


def test_na_scale_value_must_be_none():
    r = na()
    r["scale_value"] = 5
    assert codes(YES_NO_NA, r) == {E.SCALE_VALUE_NOT_ALLOWED}


# --- полная проверка ---


def _ok(cid):
    return CriterionResult(
        criterion_id=cid,
        answer="yes",
        explanation="Да",
        evidence=[Evidence(kind="checked_range", range_start=0, range_end=1)],
    )


def test_validate_complete(checklist):
    turns = TURNS
    good = [
        CriterionResult(
            criterion_id=c.id,
            answer="scale" if c.answer_type == "scale" else "no",
            scale_value=c.scale[0].value if c.scale else None,
            explanation="ок",
            evidence=[Evidence(kind="checked_range", range_start=0, range_end=2)],
        )
        for c in checklist.criteria
    ]
    assert validate_complete(good, checklist, turns) == []
    missing = [r for r in good if r.criterion_id != "c03"]
    assert {e.code for e in validate_complete(missing, checklist, turns)} == {E.MISSING}
    dup = [*good, good[0]]
    assert {e.code for e in validate_complete(dup, checklist, turns)} == {E.DUPLICATE}
    extra = [*good, _ok("zzz")]
    assert {e.code for e in validate_complete(extra, checklist, turns)} == {E.UNKNOWN_CRITERION}
    assert {e.code for e in validate_complete(list(reversed(good)), checklist, turns)} == {E.BAD_SHAPE}
    broken = [good[0].model_copy(update={"answer": "na"}), *good[1:]]
    assert E.NA_NOT_ALLOWED in {e.code for e in validate_complete(broken, checklist, turns)}
