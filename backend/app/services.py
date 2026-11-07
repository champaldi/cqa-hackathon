"""Сценарии приложения: связывают хранилище, оценщик и подсчёт баллов. Маршруты только вызывают их."""

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from backend.app.contracts import (
    Appeal,
    AppealCreate,
    AppealStatus,
    AudioLink,
    BatchJob,
    BatchRequest,
    Checklist,
    ChecklistDraft,
    Criterion,
    Decision,
    DecisionCreate,
    Dialog,
    DialogSummary,
    EvaluateRequest,
    Evaluation,
    EvaluationCard,
    HealthInfo,
    ImportResult,
)
from backend.app.datasets.audio import fetch_audio_duration, fetch_audio_link
from backend.app.datasets.cache import read_group, write_group
from backend.app.datasets.client import fetch_group
from backend.app.datasets.normalize import normalize_dataset
from backend.app.datasets.timing import with_audio_positions
from backend.app.errors import (
    ConflictError,
    DatasetError,
    DatasetNotConfiguredError,
    InvalidError,
    NotFoundError,
)
from backend.app.evaluator.base import Evaluator
from backend.app.scoring.engine import apply_decisions, score
from backend.app.settings import Settings
from backend.app.storage.base import Storage

logger = logging.getLogger(__name__)


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def _check_new_answer(criterion: Criterion, decision: DecisionCreate) -> None:
    """Новый ответ проверяющего должен быть допустим для этого критерия."""
    if decision.answer == "na":
        if not criterion.allow_na:
            raise InvalidError(f"Критерий {criterion.id} не допускает N/A")
    elif criterion.answer_type == "scale":
        steps = {step.value for step in criterion.scale or []}
        if decision.answer != "scale" or decision.scale_value not in steps:
            raise InvalidError(f"Для критерия {criterion.id} выберите ступень шкалы: {sorted(steps)}")
    elif decision.answer not in ("yes", "no"):
        raise InvalidError(f"Для критерия {criterion.id} допустимы только ответы да или нет")


@dataclass(frozen=True)
class Services:
    settings: Settings
    storage: Storage
    evaluator: Evaluator

    def health(self) -> HealthInfo:
        return HealthInfo(
            evaluator=self.settings.evaluator, dataset_configured=bool(self.settings.dataset_url)
        )

    # ---------- Диалоги ----------

    def list_summaries(self, group_id: str | None = None) -> list[DialogSummary]:
        return [self._summary(dialog) for dialog in self.storage.list_dialogs(group_id)]

    def get_dialog(self, conversation_id: str) -> Dialog:
        dialog = self.storage.get_dialog(conversation_id)
        if dialog is None:
            raise NotFoundError(f"Диалог {conversation_id} не найден")
        return dialog

    def import_group(self, group_id: str) -> ImportResult:
        if not self.settings.dataset_url:
            raise DatasetNotConfiguredError("Не задан CQA_DATASET_URL: вставьте ссылку из гайда в файл .env")
        payload = self._fetch_group(group_id)
        received = payload.get("dataset_group_id")
        if received != group_id:
            raise DatasetError(f"Запрошен набор {group_id}, а API вернул {received}")
        dialogs = normalize_dataset(payload)
        write_group(self.settings.cache_dir, group_id, payload)
        with ThreadPoolExecutor(max_workers=self.settings.batch_concurrency) as pool:
            placed = list(pool.map(self._place_on_recording, dialogs))
        return ImportResult(group_id=group_id, imported=self.storage.save_dialogs(placed))

    def audio_link(self, conversation_id: str) -> AudioLink:
        dialog = self.get_dialog(conversation_id)
        if dialog.audio_url is None:
            raise NotFoundError(f"У диалога {conversation_id} нет записи")
        return AudioLink(url=fetch_audio_link(dialog.audio_url))

    def _fetch_group(self, group_id: str) -> dict[str, Any]:
        """Сначала свежие данные из API. Копия нужна, только если API не ответил."""
        try:
            return fetch_group(self.settings.dataset_url, group_id)
        except DatasetError as exc:
            cached = read_group(self.settings.cache_dir, group_id)
            if cached is None:
                raise
            logger.warning("Набор %s взят из кеша: %s", group_id, exc)
            return cached

    def _place_on_recording(self, dialog: Dialog) -> Dialog:
        """Без длины записи импорт не падает: положение реплики остаётся в audio_tail_sec."""
        if not self.settings.measure_audio or dialog.audio_url is None:
            return dialog
        try:
            duration = fetch_audio_duration(dialog.audio_url)
        except DatasetError as exc:
            logger.warning("Длина записи %s не получена: %s", dialog.conversation_id, exc)
            return dialog
        return dialog if duration is None else with_audio_positions(dialog, duration)

    def _summary(self, dialog: Dialog) -> DialogSummary:
        summary = DialogSummary(
            conversation_id=dialog.conversation_id,
            dataset_group_id=dialog.dataset_group_id,
            channel=dialog.channel,
            language=dialog.language,
            turns=len(dialog.transcript),
        )
        evaluation = self.storage.latest_evaluation(dialog.conversation_id)
        if evaluation is None:
            return summary
        final_score = self._card(evaluation).final_score
        return summary.model_copy(
            update={
                "evaluation_id": evaluation.id,
                "total": final_score.total,
                "gross_error": final_score.gross_error,
            }
        )

    # ---------- Чек-листы ----------

    def list_checklists(self) -> list[Checklist]:
        return self.storage.list_checklists()

    def get_checklist(self, checklist_id: str) -> Checklist:
        checklist = self.storage.get_checklist(checklist_id)
        if checklist is None:
            raise NotFoundError(f"Чек-лист {checklist_id} не найден")
        return checklist

    def active_checklist(self) -> Checklist:
        checklists = self.storage.list_checklists()
        if not checklists:
            raise NotFoundError("Чек-листов пока нет")
        return checklists[-1]

    def save_checklist(self, draft: ChecklistDraft) -> Checklist:
        version = self.active_checklist().version + 1
        checklist = Checklist(**draft.model_dump(), id=f"checklist-v{version}", version=version)
        return self.storage.save_checklist(checklist)

    def _resolve_checklist(self, checklist_id: str | None) -> Checklist:
        return self.active_checklist() if checklist_id is None else self.get_checklist(checklist_id)

    # ---------- Оценка ----------

    def evaluate(self, request: EvaluateRequest) -> EvaluationCard:
        dialog = self.get_dialog(request.conversation_id)
        checklist = self._resolve_checklist(request.checklist_id)
        return self._card(self._evaluate_dialog(dialog, checklist))

    def get_card(self, evaluation_id: str) -> EvaluationCard:
        return self._card(self._get_evaluation(evaluation_id))

    def _evaluate_dialog(self, dialog: Dialog, checklist: Checklist) -> Evaluation:
        output = self.evaluator.evaluate(dialog, checklist)
        evaluation = Evaluation(
            id=new_id("ev"),
            conversation_id=dialog.conversation_id,
            checklist_id=checklist.id,
            results=output.results,
            score=score(checklist, output.results),
            usage=output.usage,
        )
        return self.storage.save_evaluation(evaluation)

    def _get_evaluation(self, evaluation_id: str) -> Evaluation:
        evaluation = self.storage.get_evaluation(evaluation_id)
        if evaluation is None:
            raise NotFoundError(f"Оценка {evaluation_id} не найдена")
        return evaluation

    def _card(self, evaluation: Evaluation) -> EvaluationCard:
        checklist = self.get_checklist(evaluation.checklist_id)
        appeals = self.storage.list_appeals(evaluation_id=evaluation.id)
        final_results = apply_decisions(evaluation.results, appeals)
        return EvaluationCard(
            evaluation=evaluation,
            dialog=self.get_dialog(evaluation.conversation_id),
            checklist=checklist,
            appeals=appeals,
            final_results=final_results,
            final_score=score(checklist, final_results),
        )

    # ---------- Апелляции ----------

    def create_appeal(self, evaluation_id: str, request: AppealCreate) -> Appeal:
        evaluation = self._get_evaluation(evaluation_id)
        if request.criterion_id not in {result.criterion_id for result in evaluation.results}:
            raise InvalidError(f"В оценке нет критерия {request.criterion_id}")
        open_appeals = self.storage.list_appeals(evaluation_id=evaluation_id, status="open")
        if any(appeal.criterion_id == request.criterion_id for appeal in open_appeals):
            raise ConflictError("По этому критерию уже есть открытая апелляция")
        appeal = Appeal(
            id=new_id("ap"),
            evaluation_id=evaluation_id,
            criterion_id=request.criterion_id,
            comment=request.comment,
        )
        return self.storage.save_appeal(appeal)

    def list_appeals(
        self, evaluation_id: str | None = None, status: AppealStatus | None = None
    ) -> list[Appeal]:
        return self.storage.list_appeals(evaluation_id=evaluation_id, status=status)

    def decide_appeal(self, appeal_id: str, request: DecisionCreate) -> Appeal:
        appeal = self.storage.get_appeal(appeal_id)
        if appeal is None:
            raise NotFoundError(f"Апелляция {appeal_id} не найдена")
        if appeal.status != "open":
            raise ConflictError("Решение по этой апелляции уже принято")
        if request.action == "change":
            _check_new_answer(self._criterion_of(appeal), request)
        status: AppealStatus = "changed" if request.action == "change" else "confirmed"
        decision = Decision(**request.model_dump())
        return self.storage.save_appeal(appeal.model_copy(update={"status": status, "decision": decision}))

    def _criterion_of(self, appeal: Appeal) -> Criterion:
        checklist = self.get_checklist(self._get_evaluation(appeal.evaluation_id).checklist_id)
        return next(c for c in checklist.criteria if c.id == appeal.criterion_id)

    # ---------- Пакетная оценка ----------

    def start_batch(self, request: BatchRequest) -> BatchJob:
        checklist = self._resolve_checklist(request.checklist_id)
        dialogs = self.storage.list_dialogs(request.group_id)
        if not dialogs:
            raise NotFoundError(f"В группе {request.group_id} нет диалогов")
        job = BatchJob(
            id=new_id("job"), group_id=request.group_id, checklist_id=checklist.id, total=len(dialogs)
        )
        return self.storage.save_job(job)

    def run_batch(self, job: BatchJob) -> None:
        """Работает в фоне. Параллельность и повторы добавляет задача backend/batch-and-appeals."""
        checklist = self.get_checklist(job.checklist_id)
        for dialog in self.storage.list_dialogs(job.group_id):
            job = self.storage.save_job(self._run_one(job, dialog, checklist))
        self.storage.save_job(job.model_copy(update={"status": "done"}))

    def get_batch(self, job_id: str) -> BatchJob:
        job = self.storage.get_job(job_id)
        if job is None:
            raise NotFoundError(f"Пакет {job_id} не найден")
        return job

    def _run_one(self, job: BatchJob, dialog: Dialog, checklist: Checklist) -> BatchJob:
        try:
            self._evaluate_dialog(dialog, checklist)
        except Exception:  # один сбойный диалог не должен останавливать весь пакет
            logger.exception("Не удалось оценить диалог %s", dialog.conversation_id)
            error = f"{dialog.conversation_id}: не удалось оценить"
            return job.model_copy(update={"failed": job.failed + 1, "errors": [*job.errors, error]})
        return job.model_copy(update={"done": job.done + 1})
