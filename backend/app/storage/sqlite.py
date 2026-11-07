"""Хранилище на SQLite: диалоги, оценки и апелляции переживают перезапуск сервера.

Модели лежат целиком в JSON. Отдельными колонками вынесено только то, по чему идёт
поиск и сортировка. Соединение одно, его закрывает замок: пакетная оценка пишет из фона.
"""

import sqlite3
from collections.abc import Iterable, Mapping
from pathlib import Path
from threading import Lock
from typing import Any

from pydantic import BaseModel

from backend.app.contracts import Appeal, AppealStatus, BatchJob, Checklist, Dialog, Evaluation

IN_MEMORY = ":memory:"

SCHEMA = """
CREATE TABLE IF NOT EXISTS dialogs (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    group_id TEXT NOT NULL,
    body TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS dialogs_by_group ON dialogs (group_id);

CREATE TABLE IF NOT EXISTS checklists (
    id TEXT PRIMARY KEY,
    version INTEGER NOT NULL,
    body TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evaluations (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    conversation_id TEXT NOT NULL,
    created_ts REAL NOT NULL,
    body TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS evaluations_by_dialog ON evaluations (conversation_id, created_ts);

CREATE TABLE IF NOT EXISTS appeals (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    evaluation_id TEXT NOT NULL,
    status TEXT NOT NULL,
    body TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS appeals_by_evaluation ON appeals (evaluation_id);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    body TEXT NOT NULL
);
"""

# Повторное сохранение меняет строку и не трогает seq, поэтому порядок остаётся прежним.
SAVE_DIALOG = """
INSERT INTO dialogs (id, group_id, body) VALUES (:id, :group_id, :body)
ON CONFLICT (id) DO UPDATE SET group_id = excluded.group_id, body = excluded.body
"""
SAVE_CHECKLIST = """
INSERT INTO checklists (id, version, body) VALUES (:id, :version, :body)
ON CONFLICT (id) DO UPDATE SET version = excluded.version, body = excluded.body
"""
SAVE_EVALUATION = """
INSERT INTO evaluations (id, conversation_id, created_ts, body)
VALUES (:id, :conversation_id, :created_ts, :body)
"""
SAVE_APPEAL = """
INSERT INTO appeals (id, evaluation_id, status, body) VALUES (:id, :evaluation_id, :status, :body)
ON CONFLICT (id) DO UPDATE SET status = excluded.status, body = excluded.body
"""
SAVE_JOB = """
INSERT INTO jobs (id, body) VALUES (:id, :body)
ON CONFLICT (id) DO UPDATE SET body = excluded.body
"""


class SqliteStorage:
    def __init__(self, path: Path | None = None) -> None:
        """Без пути база живёт в памяти и исчезает вместе с приложением."""
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._db = sqlite3.connect(str(path or IN_MEMORY), check_same_thread=False)
        self._db.execute("PRAGMA journal_mode = WAL")
        self._db.executescript(SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def save_dialogs(self, dialogs: Iterable[Dialog]) -> int:
        rows = {
            dialog.conversation_id: {
                "id": dialog.conversation_id,
                "group_id": dialog.dataset_group_id,
                "body": dialog.model_dump_json(),
            }
            for dialog in dialogs
        }
        with self._lock, self._db:
            self._db.executemany(SAVE_DIALOG, list(rows.values()))
        return len(rows)

    def list_dialogs(self, group_id: str | None = None) -> list[Dialog]:
        sql = "SELECT body FROM dialogs WHERE :group_id IS NULL OR group_id = :group_id ORDER BY seq"
        return self._all(Dialog, sql, {"group_id": group_id})

    def get_dialog(self, conversation_id: str) -> Dialog | None:
        return self._one(Dialog, "SELECT body FROM dialogs WHERE id = :id", {"id": conversation_id})

    def save_checklist(self, checklist: Checklist) -> Checklist:
        row = {"id": checklist.id, "version": checklist.version, "body": checklist.model_dump_json()}
        self._write(SAVE_CHECKLIST, row)
        return checklist

    def list_checklists(self) -> list[Checklist]:
        return self._all(Checklist, "SELECT body FROM checklists ORDER BY version", {})

    def get_checklist(self, checklist_id: str) -> Checklist | None:
        return self._one(Checklist, "SELECT body FROM checklists WHERE id = :id", {"id": checklist_id})

    def save_evaluation(self, evaluation: Evaluation) -> Evaluation:
        row = {
            "id": evaluation.id,
            "conversation_id": evaluation.conversation_id,
            "created_ts": evaluation.created_at.timestamp(),
            "body": evaluation.model_dump_json(),
        }
        try:
            self._write(SAVE_EVALUATION, row)
        except sqlite3.IntegrityError:
            raise ValueError(f"Оценка {evaluation.id} уже сохранена и не меняется") from None
        return evaluation

    def get_evaluation(self, evaluation_id: str) -> Evaluation | None:
        return self._one(Evaluation, "SELECT body FROM evaluations WHERE id = :id", {"id": evaluation_id})

    def latest_evaluation(self, conversation_id: str) -> Evaluation | None:
        sql = """
        SELECT body FROM evaluations WHERE conversation_id = :conversation_id
        ORDER BY created_ts DESC, seq DESC LIMIT 1
        """
        return self._one(Evaluation, sql, {"conversation_id": conversation_id})

    def save_appeal(self, appeal: Appeal) -> Appeal:
        row = {
            "id": appeal.id,
            "evaluation_id": appeal.evaluation_id,
            "status": appeal.status,
            "body": appeal.model_dump_json(),
        }
        self._write(SAVE_APPEAL, row)
        return appeal

    def get_appeal(self, appeal_id: str) -> Appeal | None:
        return self._one(Appeal, "SELECT body FROM appeals WHERE id = :id", {"id": appeal_id})

    def list_appeals(
        self, evaluation_id: str | None = None, status: AppealStatus | None = None
    ) -> list[Appeal]:
        sql = """
        SELECT body FROM appeals
        WHERE (:evaluation_id IS NULL OR evaluation_id = :evaluation_id)
          AND (:status IS NULL OR status = :status)
        ORDER BY seq
        """
        return self._all(Appeal, sql, {"evaluation_id": evaluation_id, "status": status})

    def save_job(self, job: BatchJob) -> BatchJob:
        self._write(SAVE_JOB, {"id": job.id, "body": job.model_dump_json()})
        return job

    def get_job(self, job_id: str) -> BatchJob | None:
        return self._one(BatchJob, "SELECT body FROM jobs WHERE id = :id", {"id": job_id})

    def _write(self, sql: str, row: Mapping[str, Any]) -> None:
        with self._lock, self._db:
            self._db.execute(sql, row)

    def _all[T: BaseModel](self, model: type[T], sql: str, params: Mapping[str, Any]) -> list[T]:
        with self._lock:
            rows = self._db.execute(sql, params).fetchall()
        return [model.model_validate_json(row[0]) for row in rows]

    def _one[T: BaseModel](self, model: type[T], sql: str, params: Mapping[str, Any]) -> T | None:
        with self._lock:
            row = self._db.execute(sql, params).fetchone()
        return None if row is None else model.model_validate_json(row[0])
