"""Все ошибки API приходят в том же конверте, что и успешные ответы."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from backend.app.errors import AppError

logger = logging.getLogger(__name__)


def _failure(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code, content={"success": False, "data": None, "error": message}
    )


def _describe(exc: RequestValidationError) -> str:
    messages = []
    for error in exc.errors():
        field = ".".join(str(part) for part in error["loc"] if part != "body")
        messages.append(f"{field}: {error['msg']}" if field else error["msg"])
    return "; ".join(messages)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    def handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
        return _failure(exc.status_code, str(exc))

    @app.exception_handler(RequestValidationError)
    def handle_validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return _failure(422, _describe(exc))

    @app.exception_handler(HTTPException)
    def handle_http_error(_request: Request, exc: HTTPException) -> JSONResponse:
        return _failure(exc.status_code, str(exc.detail))

    @app.exception_handler(Exception)
    def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.error("Сбой при обработке %s %s", request.method, request.url.path, exc_info=exc)
        return _failure(500, "Внутренняя ошибка сервера")
