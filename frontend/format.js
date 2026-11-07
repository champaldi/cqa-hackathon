// Подписи и форматирование, общие для экранов.

import { el } from "./dom.js";

export const SPEAKER_LABELS = {
  client: "Клиент",
  operator: "Оператор",
  bot: "Бот",
  system: "Система",
};

export const CHANNEL_LABELS = { "agent chat": "Чат", "voice call": "Звонок" };

export const APPEAL_STATUS_LABELS = {
  open: "Открыта",
  confirmed: "Оценка подтверждена",
  changed: "Оценка изменена",
};

const ANSWER_LABELS = { yes: "Да", no: "Нет", na: "N/A" };

export function formatNumber(value) {
  return Number(value).toLocaleString("ru-RU", { maximumFractionDigits: 2 });
}

export function formatTotal(total) {
  return total === null ? "не рассчитан" : formatNumber(total);
}

export function formatDate(iso) {
  return new Date(iso).toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" });
}

export function indexBy(items, key) {
  return new Map(items.map((item) => [item[key], item]));
}

export function cardHref(evaluationId) {
  return `#/card/${encodeURIComponent(evaluationId)}`;
}

// Подходит и для результата критерия, и для решения проверяющего: поля answer и scale_value.
export function answerText(result, criterion) {
  if (result.answer !== "scale") return ANSWER_LABELS[result.answer] ?? result.answer;
  const step = criterion?.scale?.find((item) => item.value === result.scale_value);
  return step ? `${step.value}: ${step.label}` : String(result.scale_value ?? "нет значения");
}

function scaleTone(result, criterion) {
  const values = (criterion?.scale ?? []).map((step) => step.value);
  if (result.scale_value === Math.max(...values)) return "pass";
  if (result.scale_value === Math.min(...values)) return "fail";
  return "partial";
}

// У флага «Да» значит, что грубая ошибка найдена, поэтому смысл цвета обратный.
export function answerTone(result, criterion) {
  if (result.answer === "na") return "na";
  if (criterion?.answer_type === "flag") return result.answer === "yes" ? "gross" : "pass";
  if (result.answer === "scale") return scaleTone(result, criterion);
  return result.answer === "yes" ? "pass" : "fail";
}

export function answerTag(result, criterion) {
  const tone = answerTone(result, criterion);
  return el("span", { class: `tag tag--${tone}` }, answerText(result, criterion));
}

export function sameAnswer(left, right) {
  return left.answer === right.answer && left.scale_value === right.scale_value;
}

// У N/A объяснение и есть причина неприменимости, поэтому она подписана явно.
export function explanationLine(result, title) {
  const heading = title ?? (result.answer === "na" ? "Причина N/A" : null);
  return el(
    "p",
    { class: "explanation" },
    heading ? el("span", { class: "evidence__label" }, `${heading}: `) : null,
    result.explanation,
  );
}
