import logging

import pytest

from backend.app.evaluator.client import Prices
from backend.app.evaluator.core import LlmEvaluator
from backend.app.evaluator.factory import build_evaluator
from backend.app.evaluator.mock import MockEvaluator
from backend.app.settings import Settings


def llm_settings(price: float = 2.0) -> Settings:
    return Settings(
        evaluator="llm",
        anthropic_api_key="test-placeholder",
        llm_model="test-model",
        price_input_per_mtok=price,
        price_output_per_mtok=price * 5,
    )


def test_mock_mode_builds_the_mock_evaluator() -> None:
    assert isinstance(build_evaluator(Settings(evaluator="mock")), MockEvaluator)


def test_llm_mode_without_key_fails_on_start() -> None:
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        build_evaluator(Settings(evaluator="llm"))


def test_llm_mode_builds_the_evaluator_from_settings() -> None:
    evaluator = build_evaluator(llm_settings())

    assert isinstance(evaluator, LlmEvaluator)
    assert evaluator._model == "test-model"
    assert evaluator._prices == Prices(2.0, 10.0)


def test_zero_price_warns_but_starts(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        evaluator = build_evaluator(llm_settings(price=0.0))

    assert isinstance(evaluator, LlmEvaluator)
    assert "CQA_PRICE" in caplog.text
