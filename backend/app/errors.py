"""Ошибки приложения. Текст ошибки показывается пользователю, поэтому секретов в нём быть не должно."""


class AppError(Exception):
    status_code = 500


class NotFoundError(AppError):
    status_code = 404


class ConflictError(AppError):
    status_code = 409


class InvalidError(AppError):
    status_code = 422


class DatasetError(AppError):
    """API организаторов недоступен или вернул неверные данные."""

    status_code = 502


class DatasetNotConfiguredError(AppError):
    status_code = 503
