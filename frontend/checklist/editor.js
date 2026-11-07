// Временный редактор чек-листа: JSON в текстовом поле.
// Зона задачи qa/checklist-editor. Наружу отдаёт только renderChecklist(ctx).

import { api } from "../api.js";
import { el } from "../dom.js";
import { formatDate } from "../format.js";

const COLUMNS = ["Версия", "Название", "Критериев", "Создана", "Статус"];

function toDraftJson({ name, sections, criteria }) {
  return JSON.stringify({ name, sections, criteria }, null, 2);
}

function parseDraft(text) {
  try {
    return JSON.parse(text);
  } catch (cause) {
    throw new Error(`Некорректный JSON: ${cause.message}`, { cause });
  }
}

async function saveVersion(ctx, editor, button) {
  const action = async () => {
    const checklist = await api.saveChecklist(parseDraft(editor.value));
    await renderChecklist(ctx);
    return checklist;
  };
  const saved = await ctx.run(action, { button, label: "Сохранение версии…" });
  if (saved) ctx.notify(`Версия ${saved.version} сохранена и стала активной.`);
}

function versionRow(checklist, activeId) {
  return el(
    "tr",
    {},
    el("td", { class: "cell-num" }, checklist.version),
    el("td", {}, checklist.name),
    el("td", { class: "cell-num" }, checklist.criteria.length),
    el("td", {}, formatDate(checklist.created_at)),
    el("td", {}, checklist.id === activeId ? el("span", { class: "tag tag--pass" }, "Активная") : null),
  );
}

function versionsTable(versions, activeId) {
  const newestFirst = [...versions].sort((left, right) => right.version - left.version);
  return el(
    "div",
    { class: "table-wrap" },
    el(
      "table",
      { class: "table" },
      el("thead", {}, el("tr", {}, COLUMNS.map((label) => el("th", { scope: "col" }, label)))),
      el("tbody", {}, newestFirst.map((checklist) => versionRow(checklist, activeId))),
    ),
  );
}

function editorForm(ctx, active) {
  const editor = el("textarea", {
    class: "input input--code",
    rows: "24",
    spellcheck: "false",
    "aria-label": "JSON чек-листа: name, sections, criteria",
    value: toDraftJson(active),
  });
  const button = el("button", { class: "btn btn--primary", type: "submit" }, "Сохранить новую версию");
  const onsubmit = (event) => {
    event.preventDefault();
    saveVersion(ctx, editor, button);
  };
  return el("form", { class: "editor", onsubmit }, editor, el("div", {}, button));
}

export async function renderChecklist(ctx) {
  const [versions, active] = await Promise.all([api.listChecklists(), api.activeChecklist()]);
  ctx.view.replaceChildren(
    el(
      "div",
      { class: "screen" },
      el(
        "div",
        { class: "page-head" },
        el("h1", { class: "page-title" }, "Чек-лист"),
        el("p", { class: "page-sub" }, "Временный редактор до задачи qa/checklist-editor."),
      ),
      versionsTable(versions, active.id),
      el(
        "p",
        { class: "note" },
        `Ниже JSON активной версии ${active.version}. Новая версия применяется к следующим оценкам, `,
        "готовые карточки сохраняют свою версию.",
      ),
      editorForm(ctx, active),
    ),
  );
}
