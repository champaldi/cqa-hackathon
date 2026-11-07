// Редактор чек-листа: таблица версий и форма критериев. Наружу отдаёт только renderChecklist(ctx).
// Сохранение создаёт новую версию через api.saveChecklist, старые версии и готовые оценки не меняются.

import { api } from "../api.js";
import { el } from "../dom.js";
import { formatDate } from "../format.js";
import { criterionForm } from "./criterion-form.js";
import { blankCriterion, fromChecklist, toPayload, validate, weightSum } from "./draft.js";

const COLUMNS = ["Версия", "Название", "Критериев", "Сумма весов", "Создана", "Статус"];

const formatWeight = (value) => String(Math.round(value * 100) / 100).replace(".", ",");

function versionRow(checklist, activeId) {
  return el(
    "tr",
    {},
    el("td", { class: "cell-num" }, checklist.version),
    el("td", {}, checklist.name),
    el("td", { class: "cell-num" }, checklist.criteria.length),
    el("td", { class: "cell-num" }, formatWeight(weightSum(checklist))),
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

function sumText(draft) {
  const sum = weightSum(draft);
  const note = sum === 100 ? "" : ". Сумма не равна 100: при подсчёте веса приводятся к 100, сохранять можно";
  return `Сумма весов: ${formatWeight(sum)}${note}.`;
}

function errorList(errors) {
  return el(
    "div",
    { class: "message message--error", role: "alert" },
    el(
      "div",
      { class: "message__text" },
      el("strong", {}, "Версия не сохранена, исправьте поля:"),
      el("ul", {}, errors.map((error) => el("li", {}, error))),
    ),
  );
}

async function save(ctx, draft, button, errorsBox) {
  const errors = validate(draft);
  errorsBox.replaceChildren(errors.length ? errorList(errors) : "");
  if (errors.length) {
    errorsBox.scrollIntoView({ block: "nearest" });
    return;
  }
  const saved = await ctx.run(() => api.saveChecklist(toPayload(draft)), {
    button,
    label: "Сохранение версии…",
  });
  if (!saved) return;
  await renderChecklist(ctx);
  ctx.notify(`Версия ${saved.version} сохранена и стала активной. Новые оценки пойдут по ней.`);
}

function editorForm(ctx, active) {
  const draft = fromChecklist(active);
  const sum = el("p", { class: "note", role: "status" });
  const list = el("div", { class: "editor" });
  const errorsBox = el("div", {});
  const paintSum = () => {
    sum.textContent = sumText(draft);
  };

  const paint = () => {
    list.replaceChildren(
      ...draft.criteria.map((criterion, index) =>
        criterionForm(criterion, draft.sections, {
          onStructure: paint,
          onWeight: paintSum,
          onRemove: () => {
            draft.criteria.splice(index, 1);
            paint();
          },
        }),
      ),
    );
    paintSum();
  };

  const name = el("input", {
    class: "input",
    type: "text",
    value: draft.name,
    oninput: (e) => {
      draft.name = e.target.value;
    },
  });
  name.id = "checklist-name";

  const addButton = el(
    "button",
    {
      class: "btn",
      type: "button",
      onclick: () => {
        draft.criteria.push(blankCriterion(draft));
        paint();
        list.lastElementChild?.scrollIntoView({ block: "start" });
      },
    },
    "Добавить критерий",
  );
  const saveButton = el("button", { class: "btn btn--primary", type: "submit" }, "Сохранить новую версию");
  const resetButton = el(
    "button",
    { class: "btn", type: "button", onclick: () => renderChecklist(ctx) },
    "Отменить изменения",
  );
  const onsubmit = (event) => {
    event.preventDefault();
    save(ctx, draft, saveButton, errorsBox);
  };

  paint();
  return el(
    "form",
    { class: "editor", onsubmit, novalidate: true },
    el(
      "div",
      { class: "field" },
      el("label", { class: "field__label", for: "checklist-name" }, "Название чек-листа"),
      name,
    ),
    list,
    el("div", {}, addButton),
    sum,
    errorsBox,
    el("div", { class: "toolbar" }, saveButton, resetButton),
  );
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
        el(
          "p",
          { class: "page-sub" },
          `Активная версия ${active.version}. Правки сохраняются новой версией, она сразу становится активной.`,
        ),
      ),
      versionsTable(versions, active.id),
      el(
        "p",
        { class: "note" },
        "Готовые оценки остаются на своей версии. Чтобы применить новую, оцените диалог ещё раз.",
      ),
      editorForm(ctx, active),
    ),
  );
}
