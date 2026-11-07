from typing import Any

from fastapi import APIRouter

from backend.app.api.deps import ServicesDep, ok
from backend.app.contracts import ApiResponse, Checklist, ChecklistDraft

router = APIRouter(prefix="/checklists", tags=["checklists"])


@router.get("", response_model=ApiResponse[list[Checklist]])
def list_checklists(services: ServicesDep) -> dict[str, Any]:
    return ok(services.list_checklists())


@router.get("/active", response_model=ApiResponse[Checklist])
def active_checklist(services: ServicesDep) -> dict[str, Any]:
    return ok(services.active_checklist())


@router.post("", response_model=ApiResponse[Checklist], status_code=201)
def save_checklist(draft: ChecklistDraft, services: ServicesDep) -> dict[str, Any]:
    return ok(services.save_checklist(draft))


@router.get("/{checklist_id}", response_model=ApiResponse[Checklist])
def get_checklist(checklist_id: str, services: ServicesDep) -> dict[str, Any]:
    return ok(services.get_checklist(checklist_id))
