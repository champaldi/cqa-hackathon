"""Сборка приложения. Запуск: uvicorn backend.app.main:create_app --factory --reload"""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend.app.api import appeals, batches, checklists, dialogs, evaluations, health
from backend.app.api.errors import register_error_handlers
from backend.app.evaluator.base import Evaluator
from backend.app.evaluator.factory import build_evaluator
from backend.app.seed import seed
from backend.app.services import Services
from backend.app.settings import ROOT_DIR, Settings, load_settings
from backend.app.storage.memory import MemoryStorage

FRONTEND_DIR = ROOT_DIR / "frontend"
ROUTERS = (
    health.router,
    dialogs.router,
    checklists.router,
    evaluations.router,
    appeals.router,
    batches.router,
)


def create_app(settings: Settings | None = None, evaluator: Evaluator | None = None) -> FastAPI:
    resolved = settings or load_settings()
    storage = MemoryStorage()
    seed(storage)

    app = FastAPI(title="CQA", version="0.1.0")
    app.state.services = Services(
        settings=resolved, storage=storage, evaluator=evaluator or build_evaluator(resolved)
    )
    register_error_handlers(app)
    for router in ROUTERS:
        app.include_router(router, prefix="/api")
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
    return app
