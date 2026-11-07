"""Сборка LlmEvaluator из явных параметров (бэкенд берёт их из Settings)."""

from __future__ import annotations

from .client import DEFAULT_TIMEOUT_SEC, AnthropicClient, Prices
from .core import LlmEvaluator


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
