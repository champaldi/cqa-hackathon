from typing import Any

from fastapi import APIRouter

from backend.app.api.deps import ServicesDep, ok
from backend.app.contracts import ApiResponse, HealthInfo

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", response_model=ApiResponse[HealthInfo])
def health(services: ServicesDep) -> dict[str, Any]:
    return ok(services.health())
