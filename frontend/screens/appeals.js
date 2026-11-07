// Экран проверяющего: открытые апелляции и форма решения.

import { api } from "../api.js";
import { el } from "../dom.js";
import { answerTag, cardHref, explanationLine, indexBy } from "../format.js";
import { rangeOf, turnView } from "./card-transcript.js";

const MAX_FRAGMENT_TURNS = 12;

// Контракт не отдаёт карточки пачкой, поэтому одна загрузка на каждую оценку из очереди.
async function loadCards(appeals) {
  const ids = [...new Set(appeals.map((appeal) => appeal.evaluation_id))];
  const cards = await Promise.all(ids.map((id) => api.getCard(id)));
  return new Map(cards.map((card) => [card.evaluation.id, card]));
}

// ---------- Спорный результат ----------

function evidenceIndices(result) {
  const indices = result.evidence.flatMap((item) => {
    if (Number.isInteger(item.range_start) && Number.isInteger(item.range_end)) {
      return rangeOf(item.range_start, item.range_end);
    }
    return Number.isInteger(item.turn_index) ? [item.turn_index] : [];
  });
  return [...new Set(indices)].sort((left, right) => left - right);
}

function fragment(card, result) {
  const turns = indexBy(card.dialog.transcript, "index");
  const found = evidenceIndices(result)
    .map((index) => turns.get(index))
    .filter(Boolean);
  if (!found.length) {
    return el("p", { class: "muted" }, "Оценка не ссылается на реплики. Полный диалог есть в карточке.");
  }
  const shown = found.slice(0, MAX_FRAGMENT_TURNS);
  return [
    el("ol", { class: "fragment" }, shown.map((turn) => turnView(turn))),
    shown.length < found.length
      ? el("p", { class: "muted" }, `Показано реплик: ${shown.length} из ${found.length}.`)
      : null,
  ];
}

function disputeBlock(label, ...content) {
  return el(
    "div",
    { class: "dispute__block" },
    el("h3", { class: "dispute__label" }, label),
    content,
  );
}

function disputeView(appeal, card, criterion, result) {
  return el(
    "div",
    { class: "dispute" },
    disputeBlock("Спорный результат", answerTag(result, criterion), explanationLine(result)),
    disputeBlock("Комментарий апелляции", el("p", {}, appeal.comment)),
    disputeBlock("Фрагмент диалога", fragment(card, result)),
  );
}

// ---------- Решение ----------

function answerOptions(criterion) {
  const base =
    criterion.answer_type === "scale"
      ? criterion.scale.map((step) => ({
          label: `${step.value}: ${step.label}`,
          answer: "scale",
          scale_value: step.value,
        }))
      : [
          { label: "Да", answer: "yes" },
          { label: "Нет", answer: "no" },
        ];
  return criterion.allow_na ? [...base, { label: "N/A", answer: "na" }] : base;
}

function readDecision(fields, options) {
  const reason = fields.reason.value.trim();
  if (!reason) throw new Error("Укажите причину решения.");
  if (!fields.change.checked) return { action: "confirm", reason };
  if (fields.answer.value === "") throw new Error("Выберите новый ответ.");
  const { answer, scale_value: scaleValue = null } = options[Number(fields.answer.value)];
  return { action: "change", reason, answer, scale_value: scaleValue };
}

async function submitDecision(ctx, appeal, fields, options, button) {
  const action = async () => {
    await api.decide(appeal.id, readDecision(fields, options));
    await renderAppeals(ctx);
    return true;
  };
  const saved = await ctx.run(action, { button, label: "Сохранение решения…" });
  if (saved) ctx.notify("Решение сохранено.");
}

function choice(input, label) {
  return el("label", { class: "decision__choice" }, input, label);
}

function createFields(appeal, options) {
  const name = `decision-${appeal.id}`;
  const answerChoices = options.map((option, index) =>
    el("option", { value: String(index) }, option.label),
  );
  return {
    confirm: el("input", { type: "radio", name, value: "confirm", checked: true }),
    change: el("input", { type: "radio", name, value: "change" }),
    answer: el(
      "select",
      { class: "input" },
      el("option", { value: "" }, "Выберите ответ"),
      answerChoices,
    ),
    reason: el("textarea", { class: "input", rows: "3", required: true }),
  };
}

function decisionForm(ctx, appeal, criterion) {
  const options = answerOptions(criterion);
  const fields = createFields(appeal, options);
  const answerField = el(
    "label",
    { class: "field", hidden: true },
    el("span", { class: "field__label" }, "Новый ответ"),
    fields.answer,
  );
  const button = el("button", { class: "btn btn--primary", type: "submit" }, "Сохранить решение");
  const toggleAnswer = () => {
    answerField.hidden = !fields.change.checked;
  };
  const onsubmit = (event) => {
    event.preventDefault();
    submitDecision(ctx, appeal, fields, options, button);
  };
  return el(
    "form",
    { class: "decision", onsubmit, onchange: toggleAnswer },
    el("h3", { class: "dispute__label" }, "Решение"),
    choice(fields.confirm, "Подтвердить оценку"),
    choice(fields.change, "Изменить оценку"),
    answerField,
    el(
      "label",
      { class: "field" },
      el("span", { class: "field__label" }, "Причина (обязательно)"),
      fields.reason,
    ),
    button,
  );
}

// ---------- Экран ----------

function appealPanel(ctx, appeal, card) {
  const criterion = card.checklist.criteria.find((item) => item.id === appeal.criterion_id);
  const result = card.final_results.find((item) => item.criterion_id === appeal.criterion_id);
  return el(
    "article",
    { class: "appeal" },
    el(
      "div",
      { class: "appeal__head" },
      el("h2", { class: "panel__title" }, criterion.title),
      el("span", { class: "muted appeal__dialog" }, card.dialog.conversation_id),
      el("a", { class: "btn btn--small", href: cardHref(appeal.evaluation_id) }, "Открыть карточку"),
    ),
    el(
      "div",
      { class: "appeal__body" },
      disputeView(appeal, card, criterion, result),
      decisionForm(ctx, appeal, criterion),
    ),
  );
}

export async function renderAppeals(ctx) {
  const appeals = await api.listAppeals({ status: "open" });
  const cards = await loadCards(appeals);
  const panels = appeals.map((appeal) => appealPanel(ctx, appeal, cards.get(appeal.evaluation_id)));
  ctx.view.replaceChildren(
    el(
      "div",
      { class: "screen" },
      el(
        "div",
        { class: "page-head" },
        el("h1", { class: "page-title" }, "Апелляции"),
        el("p", { class: "page-sub" }, `Открытых: ${appeals.length}`),
      ),
      panels.length ? panels : el("p", { class: "placeholder" }, "Открытых апелляций нет."),
    ),
  );
}
