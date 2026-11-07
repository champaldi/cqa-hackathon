def draft(active: dict, **overrides: object) -> dict:
    fields = {key: active[key] for key in ("name", "sections", "criteria")}
    return {**fields, **overrides}


def test_default_checklist_is_active_on_start(api) -> None:
    active = api.get("/api/checklists/active")

    assert active["version"] == 1
    assert len(active["criteria"]) == 8


def test_default_weights_sum_to_100(api) -> None:
    active = api.get("/api/checklists/active")

    assert sum(criterion["weight"] for criterion in active["criteria"]) == 100


def test_saving_a_draft_creates_a_new_active_version(api) -> None:
    active = api.get("/api/checklists/active")

    saved = api.post("/api/checklists", draft(active, name="Новая версия"), status=201)

    assert saved["version"] == 2
    assert saved["id"] != active["id"]
    assert api.get("/api/checklists/active")["id"] == saved["id"]


def test_previous_version_stays_available(api) -> None:
    active = api.get("/api/checklists/active")
    api.post("/api/checklists", draft(active), status=201)

    assert api.get(f"/api/checklists/{active['id']}")["version"] == 1
    assert [c["version"] for c in api.get("/api/checklists")] == [1, 2]


def test_flag_with_weight_is_rejected(api) -> None:
    active = api.get("/api/checklists/active")
    criteria = [{**c, "weight": 5} if c["answer_type"] == "flag" else c for c in active["criteria"]]

    assert api.error("POST", "/api/checklists", 422, json=draft(active, criteria=criteria))


def test_missing_checklist_is_404(api) -> None:
    assert api.error("GET", "/api/checklists/unknown", 404)
