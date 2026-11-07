"""Выбор оценщика по настройкам и сборка LlmEvaluator из явных параметров."""

from __future__ import annotations

import logging

from backend.app.settings import Settings

from .base import Evaluator
from .client import DEFAULT_TIMEOUT_SEC, AnthropicClient, OpenAIClient, Prices
from .core import LlmEvaluator
from .mock import MockEvaluator

logger = logging.getLogger(__name__)

_CLIENTS = {"anthropic": AnthropicClient, "openai": OpenAIClient}
_KEY_NAMES = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}


def build_llm_evaluator(
    *,
    api_key: str,
    model: str,
    price_input_per_mtok: float,
    price_output_per_mtok: float,
    timeout: float = DEFAULT_TIMEOUT_SEC,
    provider: str = "anthropic",
) -> LlmEvaluator:
    """Оценщик на настоящей модели. Молчаливого перехода на mock нет: нет модели или ключа, ошибка."""
    client = _CLIENTS[provider](model=model, api_key=api_key, timeout=timeout)
    return LlmEvaluator(client, model=model, prices=Prices(price_input_per_mtok, price_output_per_mtok))


def build_evaluator(settings: Settings) -> Evaluator:
    if settings.evaluator == "mock":
        return MockEvaluator()
    provider = settings.llm_provider
    api_key = settings.openai_api_key if provider == "openai" else settings.anthropic_api_key
    if not api_key:
        key_name = _KEY_NAMES[provider]
        raise ValueError(f"CQA_EVALUATOR=llm: задайте {key_name} или используйте CQA_EVALUATOR=mock.")
    if not (settings.price_input_per_mtok and settings.price_output_per_mtok):
        logger.warning("Цена модели не задана, стоимость оценки будет 0: проверьте CQA_PRICE_*_PER_MTOK.")
    return build_llm_evaluator(
        api_key=api_key,
        model=settings.llm_model,
        price_input_per_mtok=settings.price_input_per_mtok,
        price_output_per_mtok=settings.price_output_per_mtok,
        provider=provider,
    )
