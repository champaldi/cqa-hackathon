"""Хранилище в памяти: данные живут до перезапуска. Приложение работает на sqlite.py."""

from collections.abc import Iterable
from threading import Lock

from backend.app.contracts import Appeal, AppealStatus, BatchJob, Checklist, Dialog, Evaluation


class MemoryStorage:
    def __init__(self) -> None:
        self._lock = Lock()  # пакетная оценка пишет из фонового потока
        self._dialogs: dict[str, Dialog] = {}
        self._checklists: dict[str, Checklist] = {}
        self._evaluations: dict[str, Evaluation] = {}
        self._appeals: dict[str, Appeal] = {}
        self._jobs: dict[str, BatchJob] = {}

    def save_dialogs(self, dialogs: Iterable[Dialog]) -> int:
        saved = {dialog.conversation_id: dialog for dialog in dialogs}
        with self._lock:
            self._dialogs.update(saved)
        return len(saved)

    def list_dialogs(self, group_id: str | None = None) -> list[Dialog]:
        with self._lock:
            dialogs = list(self._dialogs.values())
        return [d for d in dialogs if group_id is None or d.dataset_group_id == group_id]

    def get_dialog(self, conversation_id: str) -> Dialog | None:
        with self._lock:
            return self._dialogs.get(conversation_id)

    def save_checklist(self, checklist: Checklist) -> Checklist:
        with self._lock:
            self._checklists[checklist.id] = checklist
        return checklist

    def list_checklists(self) -> list[Checklist]:
        with self._lock:
            checklists = list(self._checklists.values())
        return sorted(checklists, key=lambda checklist: checklist.version)

    def get_checklist(self, checklist_id: str) -> Checklist | None:
        with self._lock:
            return self._checklists.get(checklist_id)

    def save_evaluation(self, evaluation: Evaluation) -> Evaluation:
        with self._lock:
            if evaluation.id in self._evaluations:
                raise ValueError(f"Оценка {evaluation.id} уже сохранена и не меняется")
            self._evaluations[evaluation.id] = evaluation
        return evaluation

    def get_evaluation(self, evaluation_id: str) -> Evaluation | None:
        with self._lock:
            return self._evaluations.get(evaluation_id)

    def latest_evaluation(self, conversation_id: str) -> Evaluation | None:
        with self._lock:
            evaluations = list(self._evaluations.values())
        matching = [e for e in reversed(evaluations) if e.conversation_id == conversation_id]
        return max(matching, key=lambda evaluation: evaluation.created_at, default=None)

    def save_appeal(self, appeal: Appeal) -> Appeal:
        with self._lock:
            self._appeals[appeal.id] = appeal
        return appeal

    def get_appeal(self, appeal_id: str) -> Appeal | None:
        with self._lock:
            return self._appeals.get(appeal_id)

    def list_appeals(
        self, evaluation_id: str | None = None, status: AppealStatus | None = None
    ) -> list[Appeal]:
        with self._lock:
            appeals = list(self._appeals.values())
        return [
            appeal
            for appeal in appeals
            if (evaluation_id is None or appeal.evaluation_id == evaluation_id)
            and (status is None or appeal.status == status)
        ]

    def save_job(self, job: BatchJob) -> BatchJob:
        with self._lock:
            self._jobs[job.id] = job
        return job

    def get_job(self, job_id: str) -> BatchJob | None:
        with self._lock:
            return self._jobs.get(job_id)
