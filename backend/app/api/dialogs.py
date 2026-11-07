from typing import Any

from fastapi import APIRouter

from backend.app.api.deps import ServicesDep, ok
from backend.app.contracts import (
    ApiResponse,
    AudioLink,
    Dialog,
    DialogSummary,
    ImportRequest,
    ImportResult,
)

router = APIRouter(prefix="/dialogs", tags=["dialogs"])


@router.get("", response_model=ApiResponse[list[DialogSummary]])
def list_dialogs(services: ServicesDep, group_id: str | None = None) -> dict[str, Any]:
    return ok(services.list_summaries(group_id))


@router.post("/import", response_model=ApiResponse[ImportResult])
def import_group(request: ImportRequest, services: ServicesDep) -> dict[str, Any]:
    return ok(services.import_group(request.group_id))


@router.get("/{conversation_id}", response_model=ApiResponse[Dialog])
def get_dialog(conversation_id: str, services: ServicesDep) -> dict[str, Any]:
    return ok(services.get_dialog(conversation_id))


@router.get("/{conversation_id}/audio", response_model=ApiResponse[AudioLink])
def get_audio(conversation_id: str, services: ServicesDep) -> dict[str, Any]:
    return ok(services.audio_link(conversation_id))
