// Критерии карточки: ответ, баллы, объяснение, доказательства и подача апелляции.
// tools = { ctx, transcript, evaluationId, refresh } приходит из card.js.

import { api } from "../api.js";
import { el } from "../dom.js";
import {
  answerTag,
  answerTone,
  explanationLine,
  formatNumber,
  indexBy,
  sameAnswer,
} from "../format.js";

function groupBySection(checklist) {
  const known = new Set(checklist.sections.map((section) => section.id));
  const titled = checklist.sections.map((section) => ({
    title: section.title,
    criteria: checklist.criteria.filter((criterion) => criterion.section_id === section.id),
  }));
  const loose = checklist.criteria.filter((criterion) => !known.has(criterion.section_id));
  return [...titled, { title: "Без секции", criteria: loose }].filter(
    (group) => group.criteria.length,
  );
}

function scoreText(score) {
  if (!score) return "";
  const base = formatNumber(score.base_weight);
  if (score.base_weight === 0) return "без баллов";
  if (!score.applicable) return `не учитывается, вес ${base}`;
  const effective = formatNumber(score.effective_weight);
  const weight = effective === base ? base : `${base}, с учётом N/A ${effective}`;
  return `баллы ${formatNumber(score.points)}, вес ${weight}`;
}

function answerBlock(criterion, original, final) {
  if (!final) return el("span", { class: "tag tag--na" }, "Нет результата");
  if (!original || sameAnswer(original, final)) return answerTag(final, criterion);
  return el(
    "span",
    { class: "answer-change" },
    el("span", { class: "answer-change__step" }, "Исходный", answerTag(original, criterion)),
    el("span", { class: "answer-change__arrow", "aria-hidden": "true" }, "→"),
    el("span", { class: "answer-change__step" }, "Финальный", answerTag(final, criterion)),
  );
}

// Решение проверяющего заменяет объяснение, поэтому исходное показывается рядом.
function explanations(original, final) {
  if (!final) return null;
  if (!original || original.explanation === final.explanation) return explanationLine(final);
  const title = original.answer === "na" ? "Исходная причина N/A" : "Исходное объяснение";
  return [explanationLine(final), explanationLine(original, title)];
}

// ---------- Доказательства ----------

function turnLink(index, transcript) {
  if (index === null || index === undefined) return null;
  if (!transcript.has(index)) return el("span", { class: "muted" }, `реплики ${index} нет в диалоге`);
  const onclick = () => transcript.focusTurn(index);
  return el("button", { class: "link-button", type: "button", onclick }, `Реплика ${index}`);
}

function rangeLink(item, transcript) {
  const { range_start: start, range_end: end } = item;
  if (!Number.isInteger(start) || !Number.isInteger(end)) return null;
  const label = `реплики ${start}–${end}`;
  if (!transcript.hasRange(start, end)) return el("span", { class: "muted" }, `${label}: их нет в диалоге`);
  const onclick = () => transcript.focusRange(start, end);
  return el("button", { class: "link-button", type: "button", onclick }, label);
}

function quoteItem(item, transcript) {
  return el(
    "li",
    { class: "evidence" },
    el("q", { class: "evidence__quote" }, item.quote ?? "цитата не указана"),
    turnLink(item.turn_index, transcript),
  );
}

function rangeItem(item, transcript) {
  return el(
    "li",
    { class: "evidence" },
    el("span", { class: "evidence__label" }, "Проверено"),
    rangeLink(item, transcript) ?? "участок не указан",
  );
}

// Причина N/A уже подписана в объяснении. Пункт нужен, только если есть цитата или ссылка.
function naItem(item, transcript) {
  const links = [turnLink(item.turn_index, transcript), rangeLink(item, transcript)].filter(Boolean);
  if (!item.quote && !links.length) return null;
  return el(
    "li",
    { class: "evidence" },
    el("span", { class: "evidence__label" }, "Основание N/A"),
    item.quote ? el("q", { class: "evidence__quote" }, item.quote) : null,
    links,
  );
}

function evidenceItem(item, transcript) {
  if (item.kind === "quote") return quoteItem(item, transcript);
  if (item.kind === "checked_range") return rangeItem(item, transcript);
  return naItem(item, transcript);
}

function evidenceList(result, transcript) {
  const items = (result?.evidence ?? []).map((item) => evidenceItem(item, transcript)).filter(Boolean);
  return items.length ? el("ul", { class: "evidence-list" }, items) : null;
}

// ---------- Апелляция ----------

async function sendAppeal(criterion, comment, button, tools) {
  const action = async () => {
    const text = comment.value.trim();
    if (!text) throw new Error("Напишите комментарий к апелляции.");
    await api.createAppeal(tools.evaluationId, { criterion_id: criterion.id, comment: text });
    await tools.refresh();
    return true;
  };
  const sent = await tools.ctx.run(action, { button, label: "Отправка апелляции…" });
  if (sent) tools.ctx.notify(`Апелляция по критерию «${criterion.title}» подана.`);
}

function appealForm(criterion, tools) {
  const comment = el("textarea", {
    class: "input",
    rows: "3",
    required: true,
    placeholder: "Что в оценке неверно",
    "aria-label": `Комментарий к апелляции: ${criterion.title}`,
  });
  const button = el("button", { class: "btn btn--small", type: "submit" }, "Подать апелляцию");
  const onsubmit = (event) => {
    event.preventDefault();
    sendAppeal(criterion, comment, button, tools);
  };
  return el(
    "details",
    { class: "appeal-form" },
    el("summary", {}, "Оспорить"),
    el("form", { class: "appeal-form__body", onsubmit }, comment, button),
  );
}

function appealSlot(criterion, appeals, tools) {
  const open = appeals.find((appeal) => appeal.status === "open");
  if (!open) return appealForm(criterion, tools);
  return el(
    "p",
    { class: "appeal-status" },
    el("span", { class: "tag tag--open" }, "Апелляция открыта"),
    el("span", {}, open.comment),
  );
}

// ---------- Критерий ----------

function criterionRow(criterion, card, lookups, tools) {
  const final = lookups.finals.get(criterion.id);
  const original = lookups.originals.get(criterion.id);
  const appeals = card.appeals.filter((appeal) => appeal.criterion_id === criterion.id);
  const tone = final ? answerTone(final, criterion) : "na";
  const shown = final?.evidence.length ? final : original;
  return el(
    "li",
    { id: `criterion-${criterion.id}`, class: `criterion criterion--${tone}` },
    el(
      "div",
      { class: "criterion__head" },
      el("h4", { class: "criterion__title" }, criterion.title),
      answerBlock(criterion, original, final),
    ),
    el("p", { class: "criterion__score" }, scoreText(lookups.scores.get(criterion.id))),
    explanations(original, final),
    evidenceList(shown, tools.transcript),
    appealSlot(criterion, appeals, tools),
  );
}

export function criteriaPanel(card, tools) {
  const lookups = {
    finals: indexBy(card.final_results, "criterion_id"),
    originals: indexBy(card.evaluation.results, "criterion_id"),
    scores: indexBy(card.final_score.criteria, "criterion_id"),
  };
  const groups = groupBySection(card.checklist).map((group) =>
    el(
      "div",
      { class: "criteria-group" },
      el("h3", { class: "criteria-group__title" }, group.title),
      el("ol", {}, group.criteria.map((item) => criterionRow(item, card, lookups, tools))),
    ),
  );
  return el(
    "section",
    { class: "panel" },
    el(
      "div",
      { class: "panel__head" },
      el("h2", { class: "panel__title" }, "Критерии"),
      el("span", { class: "muted" }, `${card.checklist.name}, версия ${card.checklist.version}`),
    ),
    groups,
  );
}
