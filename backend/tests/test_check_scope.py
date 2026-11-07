import subprocess

import pytest

from scripts import check_scope
from scripts.check_scope import changed_files, main, role_of, violations


@pytest.mark.parametrize(
    ("branch", "path"),
    [
        ("backend/data-and-storage", "backend/app/storage/sqlite.py"),
        ("backend/data-and-storage", "backend/app/services.py"),
        ("backend/data-and-storage", "backend/tests/storage/test_sqlite.py"),
        ("backend/data-and-storage", ".github/workflows/ci.yml"),
        ("backend/data-and-storage", "requirements.txt"),
        ("llm/evaluator-core", "backend/app/evaluator/llm.py"),
        ("llm/evaluator-core", "backend/tests/evaluator/test_llm.py"),
        ("ui/review-card", "frontend/screens/card.js"),
        ("ui/review-card", "frontend/styles.css"),
        ("frontend", "frontend/app.js"),
        ("frontend", "frontend/styles.css"),
        ("frontend", "frontend/screens/card.js"),
        ("frontend", "frontend/checklist/editor.js"),
        ("frontend", "frontend/checklist/model.js"),
        ("frontend", "frontend/tests/checklist-model.test.mjs"),
        ("qa/scoring-engine", "backend/app/scoring/engine.py"),
        ("qa/scoring-engine", "backend/tests/api/test_appeals.py"),
        ("qa/checklist-editor", "frontend/checklist/editor.js"),
        ("qa/gold-set", "eval/compare.py"),
        ("qa/readme-and-demo", "README.md"),
        ("qa/readme-and-demo", "docs/BRIEF.md"),
    ],
)
def test_role_can_change_its_own_zone(branch: str, path: str) -> None:
    assert violations(branch, [path]) == []


@pytest.mark.parametrize(
    ("branch", "path"),
    [
        ("backend/data-and-storage", "backend/app/evaluator/mock.py"),
        ("backend/data-and-storage", "backend/app/scoring/engine.py"),
        ("backend/data-and-storage", "frontend/app.js"),
        ("llm/evaluator-core", "backend/app/scoring/engine.py"),
        ("llm/evaluator-core", "backend/tests/api/test_appeals.py"),
        ("llm/evaluator-core", "requirements.txt"),
        ("ui/review-card", "frontend/checklist/editor.js"),
        ("ui/review-card", "backend/app/main.py"),
        ("qa/checklist-editor", "frontend/app.js"),
        ("qa/scoring-engine", "backend/app/services.py"),
        ("frontend", "backend/app/main.py"),
        ("frontend", "backend/tests/test_check_scope.py"),
        ("frontend", "config/checklist.default.json"),
        ("frontend", ".github/workflows/ci.yml"),
        ("frontend", "scripts/check_scope.py"),
        ("frontend", "requirements.txt"),
        ("frontend", "README.md"),
        ("frontend", "docs/BRIEF.md"),
    ],
)
def test_role_cannot_change_a_foreign_zone(branch: str, path: str) -> None:
    assert violations(branch, [path]) == [path]


@pytest.mark.parametrize(
    "path", ["backend/app/contracts.py", "frontend/api.js", "AGENTS.md", "CLAUDE.md"]
)
@pytest.mark.parametrize("branch", ["backend/x", "llm/x", "ui/x", "qa/x", "frontend"])
def test_shared_contract_is_closed_for_every_role(branch: str, path: str) -> None:
    assert violations(branch, [path]) == [path]


def test_contract_branch_can_change_anything() -> None:
    paths = ["backend/app/contracts.py", "frontend/api.js", "backend/app/evaluator/mock.py"]

    assert violations("contract/skeleton", paths) == []


def test_frontend_is_a_distinct_exact_branch_role() -> None:
    assert role_of("frontend") == "frontend"
    assert role_of("frontend/feature") is None
    assert role_of("Frontend") is None
    assert check_scope.owners_of("frontend/api.js") == frozenset()


def test_only_foreign_paths_are_reported() -> None:
    paths = ["frontend/app.js", "backend/app/main.py"]

    assert violations("ui/review-card", paths) == ["backend/app/main.py"]


@pytest.mark.parametrize(
    "branch", ["main", "feature/x", "backendx/y", "qa", "frontend/feature", "Frontend"]
)
def test_branch_without_role_prefix_has_no_role(branch: str) -> None:
    assert role_of(branch) is None


@pytest.mark.parametrize("branch", ["feature/x", "frontend/feature", "Frontend"])
def test_unknown_branch_is_an_error(branch: str) -> None:
    with pytest.raises(ValueError, match="префикс"):
        violations(branch, ["README.md"])


def run_cli(branch: str) -> int:
    return main(["--branch", branch, "--base", "origin/main"])


def test_cli_passes_when_every_file_is_in_the_zone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(check_scope, "changed_files", lambda base: ["frontend/app.js"])

    assert run_cli("ui/review-card") == 0


def test_cli_names_foreign_files(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(check_scope, "changed_files", lambda base: ["backend/app/main.py"])

    assert run_cli("ui/review-card") == 1
    assert "backend/app/main.py" in capsys.readouterr().err


def test_cli_fails_for_a_branch_without_role(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(check_scope, "changed_files", lambda base: [])

    assert run_cli("feature/x") == 2


def test_cli_fails_when_git_diff_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(_command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 128, stdout="", stderr="unknown revision")

    monkeypatch.setattr(check_scope.subprocess, "run", fail)

    assert run_cli("ui/review-card") == 2


def test_paths_with_cyrillic_are_read_without_quoting(monkeypatch: pytest.MonkeyPatch) -> None:
    def succeed(_command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 0, stdout="frontend/экран.js\0README.md\0", stderr="")

    monkeypatch.setattr(check_scope.subprocess, "run", succeed)

    assert changed_files("origin/main") == ["frontend/экран.js", "README.md"]


def test_base_cannot_look_like_a_git_option() -> None:
    with pytest.raises(ValueError, match="--base"):
        changed_files("--output=stolen")
