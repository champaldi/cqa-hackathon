def open_appeal(api, criterion_id: str | None = None) -> tuple[dict, dict]:
    card = api.evaluate()
    target = criterion_id or card["evaluation"]["results"][0]["criterion_id"]
    appeal = api.post(
        f"/api/evaluations/{card['evaluation']['id']}/appeals",
        {"criterion_id": target, "comment": "Оператор поздоровался"},
        status=201,
    )
    return card, appeal


def decide(api, appeal: dict, status: int = 200, **fields: object) -> dict:
    payload = {"action": "change", "reason": "Проверено", **fields}
    return api.post(f"/api/appeals/{appeal['id']}/decision", payload, status=status)


def flipped(answer: str) -> str:
    return "no" if answer == "yes" else "yes"


def test_new_appeal_is_open_and_visible_to_the_reviewer(api) -> None:
    _, appeal = open_appeal(api, "c01")

    assert appeal["status"] == "open"
    assert [a["id"] for a in api.get("/api/appeals", params={"status": "open"})] == [appeal["id"]]


def test_card_shows_the_appeal(api) -> None:
    card, appeal = open_appeal(api, "c01")

    reopened = api.get(f"/api/evaluations/{card['evaluation']['id']}")

    assert [a["id"] for a in reopened["appeals"]] == [appeal["id"]]


def test_change_decision_updates_final_result(api) -> None:
    card, appeal = open_appeal(api, "c01")
    original = card["evaluation"]["results"][0]["answer"]

    decided = decide(api, appeal, answer=flipped(original))
    reopened = api.get(f"/api/evaluations/{card['evaluation']['id']}")

    assert decided["status"] == "changed"
    assert reopened["final_results"][0]["answer"] == flipped(original)


def test_change_decision_recalculates_the_final_score(api) -> None:
    card, appeal = open_appeal(api, "c01")
    original = card["evaluation"]["results"][0]["answer"]

    decide(api, appeal, answer=flipped(original))
    reopened = api.get(f"/api/evaluations/{card['evaluation']['id']}")

    assert reopened["final_score"]["total"] != card["evaluation"]["score"]["total"]


def test_original_evaluation_never_changes(api) -> None:
    card, appeal = open_appeal(api, "c01")
    original = card["evaluation"]["results"][0]["answer"]

    decide(api, appeal, answer=flipped(original))
    reopened = api.get(f"/api/evaluations/{card['evaluation']['id']}")

    assert reopened["evaluation"] == card["evaluation"]


def test_confirm_decision_keeps_the_result(api) -> None:
    card, appeal = open_appeal(api, "c01")

    decided = decide(api, appeal, action="confirm")
    reopened = api.get(f"/api/evaluations/{card['evaluation']['id']}")

    assert decided["status"] == "confirmed"
    assert reopened["final_results"] == card["evaluation"]["results"]


def test_decided_appeal_leaves_the_open_queue(api) -> None:
    _, appeal = open_appeal(api, "c01")

    decide(api, appeal, action="confirm")

    assert api.get("/api/appeals", params={"status": "open"}) == []


def test_appeal_cannot_be_decided_twice(api) -> None:
    _, appeal = open_appeal(api, "c01")
    decide(api, appeal, action="confirm")

    payload = {"action": "confirm", "reason": "Ещё раз"}
    assert api.error("POST", f"/api/appeals/{appeal['id']}/decision", 409, json=payload)


def test_second_open_appeal_on_a_criterion_is_rejected(api) -> None:
    card, _ = open_appeal(api, "c01")

    payload = {"criterion_id": "c01", "comment": "Ещё раз"}
    path = f"/api/evaluations/{card['evaluation']['id']}/appeals"
    assert api.error("POST", path, 409, json=payload)


def test_appeal_on_unknown_criterion_is_rejected(api) -> None:
    card = api.evaluate()

    payload = {"criterion_id": "unknown", "comment": "Текст"}
    path = f"/api/evaluations/{card['evaluation']['id']}/appeals"
    assert api.error("POST", path, 422, json=payload)


def test_appeal_on_missing_evaluation_is_404(api) -> None:
    payload = {"criterion_id": "c01", "comment": "Текст"}

    assert api.error("POST", "/api/evaluations/unknown/appeals", 404, json=payload)


def test_decision_on_missing_appeal_is_404(api) -> None:
    payload = {"action": "confirm", "reason": "Текст"}

    assert api.error("POST", "/api/appeals/unknown/decision", 404, json=payload)


def test_change_requires_a_new_answer(api) -> None:
    _, appeal = open_appeal(api, "c01")

    payload = {"action": "change", "reason": "Текст"}
    assert api.error("POST", f"/api/appeals/{appeal['id']}/decision", 422, json=payload)


def test_na_is_rejected_when_the_criterion_does_not_allow_it(api) -> None:
    _, appeal = open_appeal(api, "c01")

    payload = {"action": "change", "reason": "Текст", "answer": "na"}
    assert api.error("POST", f"/api/appeals/{appeal['id']}/decision", 422, json=payload)


def test_na_is_accepted_when_the_criterion_allows_it(api) -> None:
    _, appeal = open_appeal(api, "c02")

    assert decide(api, appeal, answer="na")["status"] == "changed"


def test_scale_value_must_be_a_step_of_the_scale(api) -> None:
    _, appeal = open_appeal(api, "c04")

    payload = {"action": "change", "reason": "Текст", "answer": "scale", "scale_value": 13}
    assert api.error("POST", f"/api/appeals/{appeal['id']}/decision", 422, json=payload)


def test_scale_step_is_accepted(api) -> None:
    _, appeal = open_appeal(api, "c04")

    assert decide(api, appeal, answer="scale", scale_value=15)["status"] == "changed"


def test_yes_is_rejected_for_a_scale_criterion(api) -> None:
    _, appeal = open_appeal(api, "c04")

    payload = {"action": "change", "reason": "Текст", "answer": "yes"}
    assert api.error("POST", f"/api/appeals/{appeal['id']}/decision", 422, json=payload)
