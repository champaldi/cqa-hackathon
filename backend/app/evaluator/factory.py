"""Выбор оценщика по настройкам и сборка LlmEvaluator из явных параметров."""

from __future__ import annotations

import logging

from backend.app.settings import Settings

from .base import Evaluator
from .client import DEFAULT_TIMEOUT_SEC, AnthropicClient, Prices
from .core import LlmEvaluator
from .mock import MockEvaluator

logger = logging.getLogger(__name__)


def build_llm_evaluator(
    *,
    api_key: str,
    model: str,
    price_input_per_mtok: float,
    price_output_per_mtok: float,
    timeout: float = DEFAULT_TIMEOUT_SEC,
) -> LlmEvaluator:
    """Оценщик на настоящей модели. Молчаливого перехода на mock нет: нет модели или ключа, ошибка."""
    client = AnthropicClient(model=model, api_key=api_key, timeout=timeout)
    return LlmEvaluator(client, model=model, prices=Prices(price_input_per_mtok, price_output_per_mtok))


def build_evaluator(settings: Settings) -> Evaluator:
    if settings.evaluator == "mock":
        return MockEvaluator()
    if not settings.anthropic_api_key:
        raise ValueError("CQA_EVALUATOR=llm: задайте ANTHROPIC_API_KEY или используйте CQA_EVALUATOR=mock.")
    if not (settings.price_input_per_mtok and settings.price_output_per_mtok):
        logger.warning("Цена модели не задана, стоимость оценки будет 0: проверьте CQA_PRICE_*_PER_MTOK.")
    return build_llm_evaluator(
        api_key=settings.anthropic_api_key,
        model=settings.llm_model,
        price_input_per_mtok=settings.price_input_per_mtok,
        price_output_per_mtok=settings.price_output_per_mtok,
    )
