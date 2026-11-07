def test_evaluation_covers_every_criterion(api) -> None:
    card = api.evaluate()

    criterion_ids = [c["id"] for c in card["checklist"]["criteria"]]
    assert [r["criterion_id"] for r in card["evaluation"]["results"]] == criterion_ids


def test_card_contains_everything_for_the_screen(api) -> None:
    card = api.evaluate()

    assert card["dialog"]["conversation_id"] == "sample-ru-001"
    assert card["appeals"] == []
    assert card["final_results"] == card["evaluation"]["results"]
    assert card["final_score"] == card["evaluation"]["score"]


def test_saved_card_can_be_opened_by_id(api) -> None:
    card = api.evaluate()

    assert api.get(f"/api/evaluations/{card['evaluation']['id']}") == card


def test_unknown_dialog_is_404(api) -> None:
    payload = {"conversation_id": "unknown"}

    assert api.error("POST", "/api/evaluations", 404, json=payload)


def test_unknown_checklist_is_404(api) -> None:
    payload = {"conversation_id": "sample-ru-001", "checklist_id": "unknown"}

    assert api.error("POST", "/api/evaluations", 404, json=payload)


def test_missing_evaluation_is_404(api) -> None:
    assert api.error("GET", "/api/evaluations/unknown", 404)


def test_replaced_criterion_is_applied_through_settings(api) -> None:
    active = api.get("/api/checklists/active")
    replacement = {**active["criteria"][0], "id": "c99", "title": "Новый критерий"}
    criteria = [replacement, *active["criteria"][1:]]
    new_version = api.post(
        "/api/checklists",
        {"name": active["name"], "sections": active["sections"], "criteria": criteria},
        status=201,
    )

    card = api.evaluate()

    assert card["evaluation"]["checklist_id"] == new_version["id"]
    assert "c99" in [r["criterion_id"] for r in card["evaluation"]["results"]]


def test_old_card_keeps_its_checklist_version(api) -> None:
    old_card = api.evaluate()
    active = api.get("/api/checklists/active")
    api.post(
        "/api/checklists",
        {"name": "Другой", "sections": active["sections"], "criteria": active["criteria"]},
        status=201,
    )

    reopened = api.get(f"/api/evaluations/{old_card['evaluation']['id']}")

    assert reopened["checklist"]["name"] == active["name"]


def test_evaluation_can_use_a_chosen_version(api) -> None:
    active = api.get("/api/checklists/active")
    api.post(
        "/api/checklists",
        {"name": "Другой", "sections": active["sections"], "criteria": active["criteria"]},
        status=201,
    )

    card = api.evaluate(checklist_id=active["id"])

    assert card["evaluation"]["checklist_id"] == active["id"]
