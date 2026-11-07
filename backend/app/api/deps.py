"""Общие зависимости маршрутов."""

from typing import Annotated, Any

from fastapi import Depends, Request

from backend.app.services import Services


def get_services(request: Request) -> Services:
    return request.app.state.services


ServicesDep = Annotated[Services, Depends(get_services)]


def ok(data: Any) -> dict[str, Any]:
    """Успешный конверт ответа, см. ApiResponse в contracts.py."""
    return {"success": True, "data": data, "error": None}
