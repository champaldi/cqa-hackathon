"""Общий контракт системы: от него зависят все четыре роли.

ЗАМОРОЖЕН. Менять только через ветку contract/* и с одобрения всей команды.
Модели неизменяемые (frozen): новый результат создаётся копией, старый не правится.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Speaker = Literal["client", "operator", "bot", "system"]
Channel = Literal["agent chat", "voice call"]
Language = Literal["RU", "KZ", "EN"]
AnswerType = Literal["yes_no", "scale", "flag"]
Answer = Literal["yes", "no", "na", "scale"]
EvidenceKind = Literal["quote", "checked_range", "na_reason"]
AppealStatus = Literal["open", "confirmed", "changed"]
DecisionAction = Literal["confirm", "change"]
BatchStatus = Literal["running", "done"]


def utc_now() -> datetime:
    return datetime.now(UTC)


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


# ---------- Диалоги ----------


class Turn(Frozen):
    index: int  # 0-based, на него ссылается Evidence.turn_index
    timestamp: str  # исходная метка, не меняем
    speaker: Speaker
    text: str
    offset_sec: float | None = None  # секунды от начала диалога
    audio_offset_sec: float | None = None  # позиция от начала записи, None если реплика вне записи
    audio_tail_sec: float | None = None  # секунды до конца записи


class Dialog(Frozen):
    conversation_id: str
    dataset_group_id: str
    channel: Channel
    language: Language
    transcript: list[Turn]
    audio_url: str | None = None


# ---------- Чек-лист ----------


class ScaleStep(Frozen):
    value: int = Field(ge=0)
    label: str


class Section(Frozen):
    id: str
    title: str


class Criterion(Frozen):
    id: str
    section_id: str | None = None
    title: str
    description: str
    answer_type: AnswerType
    weight: float = Field(ge=0)
    allow_na: bool = False
    na_condition: str | None = None
    scale: list[ScaleStep] | None = None
    llm_hint: str | None = None  # необязательная подсказка модели, задаётся в настройках

    @model_validator(mode="after")
    def _check_shape(self) -> Criterion:
        if self.answer_type == "scale" and not self.scale:
            raise ValueError(f"{self.id}: шкальному критерию нужна шкала")
        if self.answer_type != "scale" and self.scale:
            raise ValueError(f"{self.id}: шкала задаётся только шкальному критерию")
        if self.answer_type == "flag" and self.weight != 0:
            raise ValueError(f"{self.id}: критерий-флаг не даёт баллов, вес должен быть 0")
        if self.allow_na and not self.na_condition:
            raise ValueError(f"{self.id}: для N/A нужно условие неприменимости")
        return self


class ChecklistDraft(Frozen):
    """То, что присылает редактор чек-листа. id и версию назначает сервер."""

    name: str = Field(min_length=1)
    sections: list[Section] = []
    criteria: list[Criterion] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_refs(self) -> ChecklistDraft:
        ids = [c.id for c in self.criteria]
        if len(ids) != len(set(ids)):
            raise ValueError("id критериев должны быть уникальными")
        section_ids = {s.id for s in self.sections}
        unknown = {c.section_id for c in self.criteria if c.section_id} - section_ids
        if unknown:
            raise ValueError(f"неизвестные секции: {sorted(unknown)}")
        return self


class Checklist(ChecklistDraft):
    id: str
    version: int
    created_at: datetime = Field(default_factory=utc_now)


# ---------- Результат оценки ----------


class Evidence(Frozen):
    """quote - цитата реплики, checked_range - проверенный участок, na_reason - обоснование N/A."""

    kind: EvidenceKind
    turn_index: int | None = None
    quote: str | None = None
    range_start: int | None = None  # включительно
    range_end: int | None = None  # включительно


class CriterionResult(Frozen):
    criterion_id: str
    answer: Answer  # для шкального критерия "scale" или "na"
    scale_value: int | None = None
    explanation: str
    evidence: list[Evidence] = []


class Usage(Frozen):
    """Суммарный расход по всем вызовам модели за одну оценку."""

    model: str = "mock"
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


class EvaluatorOutput(Frozen):
    results: list[CriterionResult]
    usage: Usage = Usage()


class CriterionScore(Frozen):
    criterion_id: str
    applicable: bool  # False при N/A и у критериев без веса
    base_weight: float  # вес из чек-листа
    effective_weight: float  # вес после перераспределения N/A
    points: float  # баллы после перераспределения


class SectionScore(Frozen):
    section_id: str
    title: str
    points: float
    max_points: float


class ScoreSummary(Frozen):
    total: float | None  # None, если применимых критериев с весом нет
    criteria: list[CriterionScore]
    sections: list[SectionScore] = []
    gross_error: bool = False
    gross_error_criteria: list[str] = []


class Evaluation(Frozen):
    """Исходная оценка. После сохранения не меняется, апелляции хранятся отдельно."""

    id: str
    conversation_id: str
    checklist_id: str
    results: list[CriterionResult]
    score: ScoreSummary
    usage: Usage = Usage()
    created_at: datetime = Field(default_factory=utc_now)


# ---------- Апелляции ----------


class AppealCreate(Frozen):
    criterion_id: str
    comment: str = Field(min_length=1)


class DecisionCreate(Frozen):
    action: DecisionAction
    reason: str = Field(min_length=1)
    answer: Answer | None = None  # обязателен при action="change"
    scale_value: int | None = None

    @model_validator(mode="after")
    def _check_change(self) -> DecisionCreate:
        if self.action == "change" and self.answer is None:
            raise ValueError("при изменении оценки нужен новый ответ")
        return self


class Decision(DecisionCreate):
    decided_at: datetime = Field(default_factory=utc_now)


class Appeal(Frozen):
    id: str
    evaluation_id: str
    criterion_id: str
    comment: str
    status: AppealStatus = "open"
    created_at: datetime = Field(default_factory=utc_now)
    decision: Decision | None = None


class EvaluationCard(Frozen):
    """Всё для карточки: исходная оценка, апелляции и финальный результат."""

    evaluation: Evaluation
    dialog: Dialog
    checklist: Checklist
    appeals: list[Appeal]
    final_results: list[CriterionResult]
    final_score: ScoreSummary


class DialogSummary(Frozen):
    """Строка списка диалогов."""

    conversation_id: str
    dataset_group_id: str
    channel: Channel
    language: Language
    turns: int
    evaluation_id: str | None = None
    total: float | None = None
    gross_error: bool = False


# ---------- Запросы и задачи ----------


class ApiResponse[T](Frozen):
    """Единый конверт всех ответов API. На клиенте его разворачивает frontend/api.js."""

    success: bool = True
    data: T | None = None
    error: str | None = None


class HealthInfo(Frozen):
    status: str = "ok"
    evaluator: str
    dataset_configured: bool


class ImportRequest(Frozen):
    group_id: str = Field(min_length=1, max_length=64, pattern=r"^[\w-]+$")


class ImportResult(Frozen):
    group_id: str
    imported: int


class AudioLink(Frozen):
    """Свежая ссылка на запись звонка, её запрашивают перед прослушиванием."""

    url: str


class EvaluateRequest(Frozen):
    conversation_id: str
    checklist_id: str | None = None  # None - активный чек-лист


class BatchRequest(Frozen):
    group_id: str
    checklist_id: str | None = None


class BatchJob(Frozen):
    id: str
    group_id: str
    checklist_id: str
    status: BatchStatus = "running"
    total: int = 0
    done: int = 0
    failed: int = 0
    errors: list[str] = []
