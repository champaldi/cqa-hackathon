// Черновик чек-листа без DOM: копия версии, правки, проверка и сборка ChecklistDraft.
// Правила формы повторяют Criterion из backend/app/contracts.py, чтобы ошибка была видна до отправки.
// Сумма весов не ограничивается: движок подсчёта приводит максимум к 100.

export const ANSWER_TYPES = [
  { value: "yes_no", label: "Да / Нет" },
  { value: "scale", label: "Шкала" },
  { value: "flag", label: "Грубая ошибка (флаг, без баллов)" },
];

const DEFAULT_SCALE = [
  { value: 10, label: "" },
  { value: 0, label: "" },
];

const text = (value) => (typeof value === "string" ? value : "");
const optional = (value) => (text(value).trim() ? text(value).trim() : null);

function copyCriterion(criterion) {
  return {
    id: text(criterion.id),
    section_id: criterion.section_id ?? "",
    title: text(criterion.title),
    description: text(criterion.description),
    answer_type: criterion.answer_type ?? "yes_no",
    weight: criterion.weight ?? 0,
    allow_na: Boolean(criterion.allow_na),
    na_condition: text(criterion.na_condition),
    scale: (criterion.scale ?? []).map((step) => ({ value: step.value, label: text(step.label) })),
    llm_hint: text(criterion.llm_hint),
  };
}

// Из сохранённой версии: серверные поля (id, version, created_at) не копируются.
export function fromChecklist({ name, sections, criteria }) {
  return {
    name: text(name),
    sections: (sections ?? []).map((section) => ({ id: section.id, title: section.title })),
    criteria: (criteria ?? []).map(copyCriterion),
  };
}

export function nextCriterionId(draft) {
  const taken = new Set(draft.criteria.map((criterion) => criterion.id));
  for (let number = draft.criteria.length + 1; ; number += 1) {
    const id = `c${String(number).padStart(2, "0")}`;
    if (!taken.has(id)) return id;
  }
}

export function blankCriterion(draft) {
  return copyCriterion({
    id: nextCriterionId(draft),
    section_id: draft.sections[0]?.id ?? "",
    answer_type: "yes_no",
    weight: 10,
  });
}

// Переключение типа приводит связанные поля к тому, что допускает контракт.
export function setAnswerType(criterion, type) {
  criterion.answer_type = type;
  if (type === "scale" && criterion.scale.length === 0) {
    criterion.scale = DEFAULT_SCALE.map((step) => ({ ...step }));
  }
  if (type === "flag") {
    criterion.weight = 0;
    criterion.allow_na = false;
  }
}

export function weightSum(draft) {
  return draft.criteria.reduce((sum, criterion) => sum + (Number(criterion.weight) || 0), 0);
}

function criterionErrors(criterion, position, seenIds) {
  const name = criterion.id.trim() || `№${position}`;
  const errors = [];
  const add = (message) => errors.push(`Критерий ${name}: ${message}`);

  if (!criterion.id.trim()) add("укажите id");
  else if (seenIds.has(criterion.id.trim())) add("id повторяется");
  seenIds.add(criterion.id.trim());
  if (!criterion.title.trim()) add("укажите название");
  if (!criterion.description.trim()) add("укажите, как оценивать");

  const weight = Number(criterion.weight);
  if (String(criterion.weight).trim() === "" || !Number.isFinite(weight) || weight < 0) {
    add("вес должен быть числом от 0");
  } else if (criterion.answer_type === "flag" && weight !== 0) {
    add("у флага грубой ошибки вес 0");
  }
  if (criterion.allow_na && !criterion.na_condition.trim()) add("при разрешённом N/A нужно условие N/A");

  if (criterion.answer_type === "scale") {
    if (criterion.scale.length === 0) add("у шкалы нужна хотя бы одна ступень");
    const values = criterion.scale.map((step) => Number(step.value));
    if (criterion.scale.some((step) => String(step.value).trim() === "" || !Number.isInteger(Number(step.value)) || Number(step.value) < 0)) {
      add("ступень шкалы — целое число от 0");
    } else if (new Set(values).size !== values.length) {
      add("ступени шкалы повторяются");
    } else if (values.length && Math.max(...values) === 0) {
      add("верхняя ступень шкалы должна быть больше 0");
    }
    if (criterion.scale.some((step) => !step.label.trim())) add("у каждой ступени нужно описание");
  }
  return errors;
}

export function validate(draft) {
  const errors = [];
  if (!draft.name.trim()) errors.push("Укажите название чек-листа");
  if (draft.criteria.length === 0) errors.push("Нужен хотя бы один критерий");
  const seenIds = new Set();
  draft.criteria.forEach((criterion, index) => errors.push(...criterionErrors(criterion, index + 1, seenIds)));
  return errors;
}

// Тело POST /api/checklists: только поля ChecklistDraft, пустые необязательные поля — null.
export function toPayload(draft) {
  return {
    name: draft.name.trim(),
    sections: draft.sections.map((section) => ({ id: section.id, title: section.title })),
    criteria: draft.criteria.map((criterion) => ({
      id: criterion.id.trim(),
      section_id: criterion.section_id || null,
      title: criterion.title.trim(),
      description: criterion.description.trim(),
      answer_type: criterion.answer_type,
      weight: criterion.answer_type === "flag" ? 0 : Number(criterion.weight),
      allow_na: criterion.answer_type === "flag" ? false : criterion.allow_na,
      na_condition: criterion.allow_na && criterion.answer_type !== "flag" ? optional(criterion.na_condition) : null,
      scale:
        criterion.answer_type === "scale"
          ? [...criterion.scale]
              .map((step) => ({ value: Number(step.value), label: step.label.trim() }))
              .sort((left, right) => right.value - left.value)
          : null,
      llm_hint: optional(criterion.llm_hint),
    })),
  };
}
