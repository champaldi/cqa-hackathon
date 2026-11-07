import json

from backend.app.contracts import Turn
from backend.app.evaluator import errors as E
from backend.app.evaluator.wire import build_output_schema, load_results, parse_reply

FIELDS = ["criterion_id", "evidence", "explanation", "answer", "scale_value", "na_condition_ref"]


def _walk(node):
    yield node
    if isinstance(node, dict):
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def test_single_item_schema_shape(default_checklist):
    schema = build_output_schema(default_checklist)
    assert schema["required"] == ["results"] and list(schema["properties"]) == ["results"]
    item = schema["properties"]["results"]["items"]
    assert list(item["properties"]) == FIELDS and item["required"] == FIELDS  # сначала основание
    assert item["properties"]["criterion_id"]["enum"] == [c.id for c in default_checklist.criteria]
    assert item["additionalProperties"] is False
    assert set(item["properties"]["answer"]["enum"]) == {"yes", "no", "scale", "na"}


def test_schema_respects_structured_output_limits(default_checklist):
    schema = build_output_schema(default_checklist)
    nodes = list(_walk(schema))
    nullable = [n for n in nodes if isinstance(n, dict) and {"type": "null"} in n.get("anyOf", [])]
    assert len(nullable) <= 16  # лимит union-типов
    for n in nodes:
        if isinstance(n, dict):
            assert "minLength" not in n and "maxLength" not in n and "minItems" not in n
            if n.get("type") == "object":
                assert n["additionalProperties"] is False


def test_schema_is_fixed_per_checklist_and_sees_new_criterion(default_checklist, new_criterion_checklist):
    assert build_output_schema(default_checklist) == build_output_schema(default_checklist)
    item = build_output_schema(new_criterion_checklist)["properties"]["results"]["items"]
    assert "x99" in item["properties"]["criterion_id"]["enum"]
    assert "x99" not in json.dumps(build_output_schema(default_checklist))


def test_load_results_variants():
    ok = '{"results": [{"criterion_id": "a"}]}'
    assert load_results(ok) == [{"criterion_id": "a"}]
    assert load_results(f"```json\n{ok}\n```") == [{"criterion_id": "a"}]
    assert load_results(f"  ```\n{ok}\n```  ") == [{"criterion_id": "a"}]
    for bad in ["", "не json", "[]", '{"results": 1}', '{"results": [], "x": 1}', '{"other": []}']:
        assert load_results(bad) is None, bad


KNOWN = frozenset(f"c0{i}" for i in range(1, 9))
TURNS = [Turn(index=0, timestamp="0", speaker="operator", text="Здравствуйте")]


def _crit(default_checklist):
    return default_checklist.criteria[:2]


def _item(cid, answer="yes"):
    return {
        "criterion_id": cid,
        "evidence": [
            {
                "kind": "quote",
                "turn_index": 0,
                "quote": "Здравствуйте",
                "range_start": None,
                "range_end": None,
            }
        ],
        "explanation": "Пояснение",
        "answer": answer,
        "scale_value": None,
        "na_condition_ref": None,
    }


def test_parse_reply_ok_missing_duplicate_and_already_valid_ignored(default_checklist):
    c1, c2 = _crit(default_checklist)
    text = json.dumps({"results": [_item(c1.id), _item("c08", "no")]})  # c08 в чек-листе, но не запрошен
    out = parse_reply(text, "end_turn", [c1, c2], TURNS, known_ids=KNOWN)
    assert set(out.ok) == {c1.id} and [e.code for e in out.errors[c2.id]] == [E.MISSING]
    dup = json.dumps({"results": [_item(c1.id), _item(c1.id), _item(c2.id)]})
    out = parse_reply(dup, "end_turn", [c1, c2], TURNS, known_ids=KNOWN)
    assert set(out.ok) == {c2.id} and [e.code for e in out.errors[c1.id]] == [E.DUPLICATE]


def test_parse_reply_whole_reply_errors(default_checklist):
    crit = _crit(default_checklist)
    good = json.dumps({"results": [_item(c.id) for c in crit]})
    for text, stop, code in [
        (good, "max_tokens", E.STOP_REASON),
        (good, "refusal", E.STOP_REASON),
        (good, None, E.STOP_REASON),
        ("не json", "end_turn", E.BAD_JSON),
    ]:
        out = parse_reply(text, stop, crit, TURNS, known_ids=KNOWN)
        assert not out.ok and {e.code for errs in out.errors.values() for e in errs} == {code}
        assert set(out.errors) == {c.id for c in crit}


def test_unknown_criterion_id_is_not_silently_ignored(default_checklist):
    crit = _crit(default_checklist)
    text = json.dumps({"results": [*(_item(c.id) for c in crit), _item("СЕКРЕТНЫЙ_ID_zzz")]})
    out = parse_reply(text, "end_turn", crit, TURNS, known_ids=KNOWN)
    assert not out.ok and set(out.errors) == {c.id for c in crit}
    codes = {e.code for errs in out.errors.values() for e in errs}
    assert codes == {E.UNKNOWN_CRITERION}
    assert all("СЕКРЕТНЫЙ" not in e.message for errs in out.errors.values() for e in errs)


def test_malformed_result_items_are_errors_not_ignored(default_checklist):
    crit = _crit(default_checklist)
    for bad in ("строка", None, {"answer": "yes"}, {"criterion_id": 5}):
        text = json.dumps({"results": [*(_item(c.id) for c in crit), bad]})
        out = parse_reply(text, "end_turn", crit, TURNS, known_ids=KNOWN)
        assert not out.ok and {e.code for errs in out.errors.values() for e in errs} == {E.BAD_SHAPE}
