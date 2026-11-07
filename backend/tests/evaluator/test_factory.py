import pytest

from backend.app.evaluator.factory import build_evaluator
from backend.app.evaluator.mock import MockEvaluator
from backend.app.settings import Settings


def test_mock_mode_builds_the_mock_evaluator() -> None:
    assert isinstance(build_evaluator(Settings(evaluator="mock")), MockEvaluator)


def test_llm_mode_fails_on_start_until_the_real_evaluator_exists() -> None:
    with pytest.raises(ValueError, match="llm/evaluator-core"):
        build_evaluator(Settings(evaluator="llm"))
