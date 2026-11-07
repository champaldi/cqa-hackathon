"""Выбор оценщика по настройкам."""

import logging

from backend.app.evaluator.base import Evaluator
from backend.app.evaluator.client import AnthropicClient, Prices
from backend.app.evaluator.core import LlmEvaluator
from backend.app.evaluator.mock import MockEvaluator
from backend.app.settings import Settings

logger = logging.getLogger(__name__)


def build_evaluator(settings: Settings) -> Evaluator:
    if settings.evaluator == "mock":
        return MockEvaluator()
    if not settings.anthropic_api_key:
        raise ValueError("CQA_EVALUATOR=llm: задайте ANTHROPIC_API_KEY или используйте CQA_EVALUATOR=mock.")
    prices = Prices(settings.price_input_per_mtok, settings.price_output_per_mtok)
    if not (prices.input_per_mtok and prices.output_per_mtok):
        logger.warning("Цена модели не задана, стоимость оценки будет 0: проверьте CQA_PRICE_*_PER_MTOK.")
    client = AnthropicClient(model=settings.llm_model, api_key=settings.anthropic_api_key)
    return LlmEvaluator(client=client, prices=prices)
