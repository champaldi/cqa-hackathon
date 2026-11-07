// Экран списка: импорт группы, пакетная оценка и таблица диалогов.

import { api } from "../api.js";
import { el } from "../dom.js";
import { CHANNEL_LABELS, cardHref, formatTotal } from "../format.js";

const POLL_MS = 1000;

const COLUMNS = [
  { label: "ID" },
  { label: "Канал" },
  { label: "Язык" },
  { label: "Реплик", class: "cell-num" },
  { label: "Итог", class: "cell-num" },
  { label: "Грубая ошибка" },
  { label: "Действие", class: "cell-action" },
];

// Переживает переход в карточку: контролёр возвращается к той же группе и тому же прогрессу.
let remembered = { groupId: "", batchId: null };

function readGroup(parts) {
  return parts.groupInput.value.trim();
}

function requireGroup(parts) {
  const groupId = readGroup(parts);
  if (!groupId) throw new Error("Укажите group_id.");
  return groupId;
}

// ---------- Таблица ----------

async function evaluateDialog(ctx, dialog, button) {
  const card = await ctx.run(() => api.evaluate(dialog.conversation_id), {
    button,
    label: `Оценка диалога ${dialog.conversation_id}…`,
  });
  if (card && ctx.isActive()) ctx.go(cardHref(card.evaluation.id));
}

function rowAction(ctx, dialog) {
  if (dialog.evaluation_id) {
    return el("a", { class: "btn btn--small", href: cardHref(dialog.evaluation_id) }, "Открыть");
  }
  const button = el(
    "button",
    {
      class: "btn btn--small btn--primary",
      type: "button",
      onclick: () => evaluateDialog(ctx, dialog, button),
    },
    "Оценить",
  );
  return button;
}

function dialogRow(ctx, dialog) {
  return el(
    "tr",
    {},
    el("td", { class: "cell-id" }, dialog.conversation_id),
    el("td", {}, CHANNEL_LABELS[dialog.channel] ?? dialog.channel),
    el("td", {}, dialog.language),
    el("td", { class: "cell-num" }, dialog.turns),
    el("td", { class: "cell-num cell-score" }, dialog.evaluation_id ? formatTotal(dialog.total) : "—"),
    el("td", {}, dialog.gross_error ? el("span", { class: "tag tag--gross" }, "Есть") : null),
    el("td", { class: "cell-action" }, rowAction(ctx, dialog)),
  );
}

function dialogTable(ctx, dialogs) {
  const headings = COLUMNS.map((column) =>
    el("th", { scope: "col", class: column.class }, column.label),
  );
  return el(
    "table",
    { class: "table" },
    el("thead", {}, el("tr", {}, headings)),
    el("tbody", {}, dialogs.map((dialog) => dialogRow(ctx, dialog))),
  );
}

function tableContent(ctx, dialogs, groupId) {
  if (!dialogs.length) {
    const scope = groupId ? `В группе ${groupId}` : "В системе";
    return [el("p", { class: "placeholder" }, `${scope} диалогов нет. Импортируйте группу выше.`)];
  }
  const scope = groupId ? `Группа ${groupId}, диалогов` : "Все группы, диалогов";
  return [
    el("p", { class: "list-count" }, `${scope}: ${dialogs.length}`),
    el("div", { class: "table-wrap" }, dialogTable(ctx, dialogs)),
  ];
}

async function reload(ctx, parts) {
  const groupId = readGroup(parts);
  const dialogs = await api.listDialogs(groupId || undefined);
  remembered = { ...remembered, groupId };
  parts.table.replaceChildren(...tableContent(ctx, dialogs, groupId));
}

// ---------- Импорт ----------

async function importGroup(ctx, parts, button) {
  const action = async () => {
    const imported = await api.importGroup(requireGroup(parts));
    await reload(ctx, parts);
    return imported;
  };
  const result = await ctx.run(action, { button, label: "Импорт группы…" });
  if (result) ctx.notify(`Группа ${result.group_id}: импортировано диалогов ${result.imported}.`);
}

function datasetNote(health) {
  if (health.dataset_configured) return null;
  return el(
    "p",
    { class: "note" },
    "Импорт недоступен: на сервере не задан адрес набора. Укажите CQA_DATASET_URL в файле .env ",
    "и перезапустите сервер. До этого в списке только встроенные примеры.",
  );
}

// ---------- Пакетная оценка ----------

function batchProgress(job) {
  const handled = job.done + job.failed;
  const title = job.status === "done" ? "Пакетная оценка завершена" : "Идёт пакетная оценка";
  return [
    el(
      "div",
      { class: "batch__line" },
      el("strong", {}, title),
      el("span", {}, `Группа ${job.group_id}: ${handled} из ${job.total}, ошибок ${job.failed}`),
    ),
    el("progress", {
      class: "batch__bar",
      max: job.total || 1,
      value: handled,
      "aria-label": "Прогресс пакетной оценки",
    }),
    job.errors.length
      ? el("ul", { class: "batch__errors" }, job.errors.map((text) => el("li", {}, text)))
      : "",
  ];
}

function followBatch(ctx, parts, batchId) {
  let timer = null;

  const tick = async () => {
    const job = await ctx.run(() => api.getBatch(batchId), { silent: true, retry: tick });
    if (!ctx.isActive()) return;
    const running = job?.status === "running";
    remembered = { ...remembered, batchId: running ? batchId : null };
    parts.batchButton.disabled = running;
    if (!job) return;
    parts.progress.replaceChildren(...batchProgress(job));
    if (running) timer = setTimeout(tick, POLL_MS);
    else await ctx.run(() => reload(ctx, parts), { silent: true }); // чужую ошибку не стирает
  };

  ctx.onLeave(() => clearTimeout(timer));
  parts.batchButton.disabled = true;
  tick();
}

async function startBatch(ctx, parts) {
  const job = await ctx.run(() => api.startBatch(requireGroup(parts)), {
    button: parts.batchButton,
    label: "Запуск пакетной оценки…",
  });
  if (!job) return;
  remembered = { groupId: job.group_id, batchId: job.id };
  followBatch(ctx, parts, job.id);
}

// ---------- Экран ----------

function createParts(ctx) {
  const groupInput = el("input", {
    id: "group-id",
    class: "input",
    value: remembered.groupId,
    placeholder: "пусто: все группы",
    autocomplete: "off",
    spellcheck: "false",
  });
  const batchButton = el("button", { class: "btn btn--primary", type: "button" }, "Оценить группу");
  const parts = {
    groupInput,
    batchButton,
    progress: el("div", { class: "batch" }),
    table: el("div", { class: "list-table" }),
  };
  batchButton.addEventListener("click", () => startBatch(ctx, parts));
  return parts;
}

function toolbar(ctx, parts, health) {
  const importButton = el(
    "button",
    {
      class: "btn",
      type: "button",
      disabled: !health.dataset_configured,
      onclick: () => importGroup(ctx, parts, importButton),
    },
    "Импортировать",
  );
  const showGroup = (event) => {
    event.preventDefault();
    ctx.run(() => reload(ctx, parts), { button: event.submitter, label: "Загрузка списка…" });
  };
  return el(
    "form",
    { class: "toolbar", onsubmit: showGroup },
    el(
      "label",
      { class: "field", for: "group-id" },
      el("span", { class: "field__label" }, "Группа (group_id)"),
      parts.groupInput,
    ),
    el("button", { class: "btn", type: "submit" }, "Показать"),
    importButton,
    parts.batchButton,
  );
}

export async function renderList(ctx) {
  const { groupId, batchId } = remembered;
  const [health, dialogs] = await Promise.all([api.health(), api.listDialogs(groupId || undefined)]);
  const parts = createParts(ctx);
  parts.table.replaceChildren(...tableContent(ctx, dialogs, groupId));
  ctx.view.replaceChildren(
    el(
      "div",
      { class: "screen" },
      el(
        "div",
        { class: "page-head" },
        el("h1", { class: "page-title" }, "Диалоги"),
        el("p", { class: "page-sub" }, `Оценщик: ${health.evaluator}`),
      ),
      toolbar(ctx, parts, health),
      datasetNote(health),
      parts.progress,
      parts.table,
    ),
  );
  if (batchId && ctx.isActive()) followBatch(ctx, parts, batchId);
}
