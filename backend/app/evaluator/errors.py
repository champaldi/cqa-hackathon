"""Типы ошибок evaluator. Имена предварительные, согласуются с Tech Lead до интеграции."""

from __future__ import annotations

from dataclasses import dataclass

from ..contracts import Usage
from ..errors import AppError

# Коды ошибок валидации. В логи и сообщения попадают только они, без текстов реплик и цитат.
BAD_SHAPE = "bad_shape"
BAD_JSON = "bad_json"
STOP_REASON = "stop_reason"
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


class EvaluationError(AppError):
    """База для всех ошибок оценки. Частичный результат не возвращается никогда.

    status_code это код ответа нашего API, его отдаёт обработчик AppError. retryable говорит,
    повторяет ли пакет такую оценку. Код ответа поставщика лежит отдельно, в upstream_status.
    usage: расход, уже потраченный на эту оценку (None, если вызовов модели не было).
    """

    status_code = 500
    retryable = False

    def __init__(self, message: str, usage: Usage | None = None) -> None:
        super().__init__(message)
        self.usage = usage


class NoOperatorTurnsError(EvaluationError):
    """В диалоге нет ни одной реплики operator, модель не вызывалась. Повтор бесполезен."""

    status_code = 422

    def __init__(self, conversation_id: str, usage: Usage | None = None) -> None:
        super().__init__(f"нет реплик оператора: {conversation_id}", usage)
        self.conversation_id = conversation_id


class ValidationFailedError(EvaluationError):
    """Ответ модели не прошёл проверку после всех repair-раундов. Автоповтора нет."""

    status_code = 502

    def __init__(self, errors: list[CriterionError], usage: Usage | None = None) -> None:
        codes = ", ".join(f"{e.criterion_id or '-'}:{e.code}" for e in errors)
        super().__init__(f"валидация не пройдена: {codes}", usage)
        self.errors = errors


class LLMUnavailableError(EvaluationError):
    """Временный сбой: соединение, таймаут, 429, 5xx. Пакет повторяет такие оценки."""

    status_code = 503
    retryable = True

    def __init__(self, message: str, upstream_status: int | None = None, usage: Usage | None = None) -> None:
        super().__init__(message, usage)
        self.upstream_status = upstream_status


class LLMRejectedError(EvaluationError):
    """Модель отклонила запрос (400, 401, 403, 404 и прочие 4xx): схема, ключ, модель. Без повтора."""

    status_code = 502

    def __init__(self, message: str, upstream_status: int | None = None, usage: Usage | None = None) -> None:
        super().__init__(message, usage)
        self.upstream_status = upstream_status
