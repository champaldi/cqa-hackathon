"""Выбор оценщика по настройкам. Настоящая модель подключается здесь."""

from backend.app.evaluator.base import Evaluator
from backend.app.evaluator.mock import MockEvaluator
from backend.app.settings import Settings


def build_evaluator(settings: Settings) -> Evaluator:
    if settings.evaluator == "mock":
        return MockEvaluator()
    raise ValueError(
        "CQA_EVALUATOR=llm: настоящая модель ещё не подключена, это задача llm/evaluator-core. "
        "Пока используйте CQA_EVALUATOR=mock."
    )
