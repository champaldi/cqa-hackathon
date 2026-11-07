"""Стартовые данные: чек-лист по умолчанию и примеры диалогов, чтобы приложение работало без API."""

import json
from pathlib import Path
from typing import Any

from backend.app.contracts import Checklist, ChecklistDraft
from backend.app.datasets.normalize import normalize_dataset
from backend.app.settings import ROOT_DIR
from backend.app.storage.base import Storage

CONFIG_DIR = ROOT_DIR / "config"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def seed(storage: Storage) -> None:
    """Заполняет только пустую базу, чтобы перезапуск не затирал сохранённые данные."""
    if storage.list_checklists():
        return
    draft = ChecklistDraft.model_validate(_read_json(CONFIG_DIR / "checklist.default.json"))
    storage.save_checklist(Checklist(**draft.model_dump(), id="checklist-v1", version=1))
    storage.save_dialogs(normalize_dataset(_read_json(CONFIG_DIR / "sample_dialogs.json")))
