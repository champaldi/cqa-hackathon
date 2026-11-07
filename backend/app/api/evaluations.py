from typing import Any

from fastapi import APIRouter

from backend.app.api.deps import ServicesDep, ok
from backend.app.contracts import ApiResponse, EvaluateRequest, EvaluationCard

router = APIRouter(prefix="/evaluations", tags=["evaluations"])


@router.post("", response_model=ApiResponse[EvaluationCard])
def evaluate(request: EvaluateRequest, services: ServicesDep) -> dict[str, Any]:
    return ok(services.evaluate(request))


@router.get("/{evaluation_id}", response_model=ApiResponse[EvaluationCard])
def get_card(evaluation_id: str, services: ServicesDep) -> dict[str, Any]:
    return ok(services.get_card(evaluation_id))
