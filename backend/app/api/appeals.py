from typing import Any

from fastapi import APIRouter

from backend.app.api.deps import ServicesDep, ok
from backend.app.contracts import ApiResponse, Appeal, AppealCreate, AppealStatus, DecisionCreate

router = APIRouter(tags=["appeals"])


@router.post(
    "/evaluations/{evaluation_id}/appeals", response_model=ApiResponse[Appeal], status_code=201
)
def create_appeal(evaluation_id: str, request: AppealCreate, services: ServicesDep) -> dict[str, Any]:
    return ok(services.create_appeal(evaluation_id, request))


@router.get("/appeals", response_model=ApiResponse[list[Appeal]])
def list_appeals(
    services: ServicesDep, status: AppealStatus | None = None, evaluation_id: str | None = None
) -> dict[str, Any]:
    return ok(services.list_appeals(evaluation_id=evaluation_id, status=status))


@router.post("/appeals/{appeal_id}/decision", response_model=ApiResponse[Appeal])
def decide_appeal(appeal_id: str, request: DecisionCreate, services: ServicesDep) -> dict[str, Any]:
    return ok(services.decide_appeal(appeal_id, request))
