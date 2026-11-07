from typing import Any

from fastapi import APIRouter, BackgroundTasks

from backend.app.api.deps import ServicesDep, ok
from backend.app.contracts import ApiResponse, BatchJob, BatchRequest

router = APIRouter(prefix="/batches", tags=["batches"])


@router.post("", response_model=ApiResponse[BatchJob], status_code=202)
def start_batch(
    request: BatchRequest, background: BackgroundTasks, services: ServicesDep
) -> dict[str, Any]:
    job = services.start_batch(request)
    background.add_task(services.run_batch, job)
    return ok(job)


@router.get("/{job_id}", response_model=ApiResponse[BatchJob])
def get_batch(job_id: str, services: ServicesDep) -> dict[str, Any]:
    return ok(services.get_batch(job_id))
