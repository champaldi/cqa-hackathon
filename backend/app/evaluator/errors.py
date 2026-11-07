"""Типы ошибок evaluator. Имена предварительные, согласуются с Tech Lead до интеграции."""

from __future__ import annotations

from dataclasses import dataclass

from ..contracts import Usage

# Коды ошибок валидации. В логи и сообщения попадают только они, без текстов реплик и цитат.
BAD_SHAPE = "bad_shape"
NO_TOOL_BLOCK = "no_tool_block"
MISSING = "missing"
DUPLICATE = "duplicate"
UNKNOWN_CRITERION = "unknown_criterion"
ANSWER_INVALID = "answer_invalid"
NA_NOT_ALLOWED = "na_not_allowed"
NA_CONDITION_MISMATCH = "na_condition_mismatch"
NA_REASON_MISSING = "na_reason_missing"
NA_REASON_UNEXPECTED = "na_reason_unexpected"
SCALE_STEP_INVALID = "scale_step_invalid"
SCALE_VALUE_NOT_ALLOWED = "scale_value_not_allowed"
EXPLANATION_EMPTY = "explanation_empty"
EVIDENCE_MISSING = "evidence_missing"
EVIDENCE_KIND_INVALID = "evidence_kind_invalid"
EVIDENCE_FIELDS_INVALID = "evidence_fields_invalid"
TURN_INDEX_OUT_OF_RANGE = "turn_index_out_of_range"
RANGE_INVALID = "range_invalid"
QUOTE_NOT_FOUND = "quote_not_found"
QUOTE_ELLIPSIS = "quote_ellipsis"
QUOTE_REQUIRED = "quote_required"


@dataclass(frozen=True)
class CriterionError:
    criterion_id: str
    code: str
    message: str  # по-русски, без текстов модели: уходит в repair-запрос


class EvaluationError(Exception):
    """База для всех ошибок оценки. Частичный результат не возвращается никогда."""


class NoOperatorTurnsError(EvaluationError):
    """В диалоге нет ни одной реплики operator, модель не вызывалась."""

    def __init__(self, conversation_id: str) -> None:
        super().__init__(f"нет реплик оператора: {conversation_id}")
        self.conversation_id = conversation_id


class LLMUnavailableError(EvaluationError):
    """Транспортный уровень исчерпан: 429, 5xx, таймаут, соединение."""

    def __init__(self, message: str, status_code: int | None = None, usage: Usage | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.usage = usage  # расход предыдущих успешных попыток этой оценки


class ValidationFailedError(EvaluationError):
    """Ответ модели не прошёл проверку после всех repair-раундов."""

    def __init__(self, errors: list[CriterionError], usage: Usage | None = None) -> None:
        codes = ", ".join(f"{e.criterion_id or '-'}:{e.code}" for e in errors)
        super().__init__(f"валидация не пройдена: {codes}")
        self.errors = errors
        self.usage = usage  # расход, уже потраченный на неудачную оценку
