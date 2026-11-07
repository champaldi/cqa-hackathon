"""Evaluator: оценка оператора по чек-листу. Публичный интерфейс согласуется с Tech Lead."""

from .core import LlmEvaluator, evaluate
from .errors import (
    CriterionError,
    EvaluationError,
    LLMUnavailableError,
    NoOperatorTurnsError,
    ValidationFailedError,
)

__all__ = [
    "CriterionError",
    "EvaluationError",
    "LLMUnavailableError",
    "LlmEvaluator",
    "NoOperatorTurnsError",
    "ValidationFailedError",
    "evaluate",
]
