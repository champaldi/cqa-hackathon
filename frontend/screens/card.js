// Карточка оценки: итог, секции, грубая ошибка, транскрипт, критерии и апелляции.

import { api } from "../api.js";
import { el } from "../dom.js";
import {
  APPEAL_STATUS_LABELS,
  CHANNEL_LABELS,
  answerText,
  formatDate,
  formatNumber,
  formatTotal,
  indexBy,
} from "../format.js";
import { criteriaPanel } from "./card-criteria.js";
import { createTranscript } from "./card-transcript.js";

const SAFE_AUDIO_URL = /^https?:\/\//i;

const APPEAL_TONES = { open: "open", confirmed: "na", changed: "pass" };

function audioLink(dialog) {
  if (dialog.channel !== "voice call") return null;
  if (!SAFE_AUDIO_URL.test(dialog.audio_url ?? "")) {
    return el("span", { class: "muted" }, "Записи нет");
  }
  return el(
    "a",
    {
      class: "btn btn--small",
      href: dialog.audio_url,
      target: "_blank",
      rel: "noopener noreferrer",
    },
    "Открыть запись",
  );
}

function headBlock(card) {
  const { dialog, evaluation } = card;
  const channel = CHANNEL_LABELS[dialog.channel] ?? dialog.channel;
  return el(
    "div",
    { class: "card-head" },
    el("a", { class: "back-link", href: "#/" }, "← К списку"),
    el("h1", { class: "page-title" }, dialog.conversation_id),
    el(
      "div",
      { class: "card-head__meta" },
      el("span", { class: "muted" }, `${channel}, ${dialog.language}, группа ${dialog.dataset_group_id}`),
      evaluation.usage.model === "mock"
        ? el("span", { class: "tag tag--mock" }, "Заглушка оценки")
        : null,
      audioLink(dialog),
    ),
  );
}

function grossBanner(card) {
  const { gross_error: grossError, gross_error_criteria: ids } = card.final_score;
  if (!grossError) return null;
  const criteria = indexBy(card.checklist.criteria, "id");
  const names = ids.map((id) => criteria.get(id)?.title ?? id);
  return el(
    "div",
    { class: "gross-banner" },
    el("strong", { class: "gross-banner__title" }, "Грубая ошибка"),
    el("span", {}, names.join(", ")),
  );
}

// После решения показываются оба итога, даже если они совпали: подтверждение тоже результат.
function scoreBlock(card) {
  const final = card.final_score.total;
  const original = card.evaluation.score.total;
  const reviewed = card.appeals.some((appeal) => appeal.decision);
  const grossRemoved = card.evaluation.score.gross_error && !card.final_score.gross_error;
  const valueClass = final === null ? "score__value score__value--empty" : "score__value";
  return el(
    "div",
    { class: "score" },
    el("p", { class: "score__label" }, reviewed ? "Финальный итог" : "Итог"),
    el("p", { class: valueClass }, formatTotal(final)),
    reviewed || final !== original
      ? el("p", { class: "score__original" }, `Исходный итог: ${formatTotal(original)}`)
      : null,
    grossRemoved
      ? el("p", { class: "score__original" }, "Грубая ошибка снята решением проверяющего")
      : null,
  );
}

function sectionRow(section) {
  const ratio = section.max_points > 0 ? section.points / section.max_points : 0;
  const share = Math.round(Math.min(Math.max(ratio, 0), 1) * 100);
  return el(
    "li",
    { class: "section-row" },
    el("span", { class: "section-row__title" }, section.title),
    el(
      "span",
      { class: "section-row__points" },
      `${formatNumber(section.points)} из ${formatNumber(section.max_points)}`,
    ),
    el(
      "span",
      { class: "meter", "aria-hidden": "true" },
      el("span", { class: "meter__fill", style: `--fill: ${share}%` }),
    ),
  );
}

function summaryBlock(card) {
  const { sections } = card.final_score;
  return el(
    "div",
    { class: "card-summary" },
    scoreBlock(card),
    sections.length ? el("ul", { class: "sections" }, sections.map(sectionRow)) : null,
  );
}

function appealDecision(appeal, criterion) {
  const { decision } = appeal;
  if (!decision) return null;
  const changed = decision.action === "change";
  return [
    changed ? el("p", {}, `Новый ответ: ${answerText(decision, criterion)}`) : null,
    el("p", {}, `Причина решения: ${decision.reason}`),
    el("p", { class: "muted" }, `Решение: ${formatDate(decision.decided_at)}`),
  ];
}

function appealItem(appeal, criteria) {
  const criterion = criteria.get(appeal.criterion_id);
  const tone = APPEAL_TONES[appeal.status] ?? "na";
  return el(
    "li",
    { class: "appeal-item" },
    el(
      "div",
      { class: "appeal-item__head" },
      el("strong", {}, criterion?.title ?? appeal.criterion_id),
      el("span", { class: `tag tag--${tone}` }, APPEAL_STATUS_LABELS[appeal.status] ?? appeal.status),
    ),
    el("p", {}, `Комментарий: ${appeal.comment}`),
    appealDecision(appeal, criterion),
  );
}

function appealsBlock(card) {
  const criteria = indexBy(card.checklist.criteria, "id");
  return el(
    "section",
    { class: "panel" },
    el(
      "div",
      { class: "panel__head" },
      el("h2", { class: "panel__title" }, "Апелляции"),
      el("span", { class: "muted" }, `всего: ${card.appeals.length}`),
    ),
    card.appeals.length
      ? el("ul", {}, card.appeals.map((appeal) => appealItem(appeal, criteria)))
      : el("p", { class: "placeholder" }, "Апелляций нет."),
  );
}

export async function renderCard(ctx) {
  const evaluationId = ctx.params[0];
  const card = await api.getCard(evaluationId);
  const transcript = createTranscript(card.dialog.transcript);
  const side = el("div", { class: "card-side" });

  // Транскрипт не перерисовывается: подсветка и прокрутка остаются на месте.
  const paintSide = (current) =>
    side.replaceChildren(criteriaPanel(current, tools), appealsBlock(current));
  const refresh = async () => paintSide(await api.getCard(evaluationId));
  const tools = { ctx, transcript, evaluationId, refresh };

  paintSide(card);
  ctx.view.replaceChildren(
    el(
      "div",
      { class: "screen" },
      headBlock(card),
      grossBanner(card),
      summaryBlock(card),
      el("div", { class: "card-columns" }, transcript.node, side),
    ),
  );
}
