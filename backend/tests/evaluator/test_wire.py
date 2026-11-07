from backend.app.evaluator.wire import build_tool_schema


def test_schema_for_default_checklist(default_checklist):
    schema = build_tool_schema(default_checklist.criteria)
    ids = [c.id for c in default_checklist.criteria]
    assert schema["additionalProperties"] is False
    assert schema["required"] == ids and list(schema["properties"]) == ids
    c04 = schema["properties"]["c04"]["properties"]
    assert set(c04["answer"]["enum"]) == {"scale", "na"}
    assert set(c04["scale_value"]["enum"]) == {20, 15, 10, 5, 0, None}
    assert c04["na_condition_ref"]["enum"][0] == default_checklist.criteria[3].na_condition
    c01 = schema["properties"]["c01"]["properties"]
    assert set(c01["answer"]["enum"]) == {"yes", "no"} and c01["scale_value"] == {"type": "null"}
    assert set(schema["properties"]["c08"]["properties"]["answer"]["enum"]) == {"no", "yes"}
    for spec in schema["properties"].values():
        assert spec["additionalProperties"] is False
        assert set(spec["required"]) == set(spec["properties"])


def test_schema_for_new_scale_criterion_without_hint(new_criterion_checklist):
    schema = build_tool_schema(new_criterion_checklist.criteria)
    assert "x99" in schema["properties"] and "x99" in schema["required"]
    props = schema["properties"]["x99"]["properties"]
    assert set(props["scale_value"]["enum"]) == {0, 1, 2, 3, 4, 5, None}
    assert props["answer"]["enum"] == ["scale"]
