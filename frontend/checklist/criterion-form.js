// Форма одного критерия. Текстовые поля пишут в черновик без перерисовки, чтобы не терять фокус.
// Смена типа, N/A и шкалы меняет набор полей, поэтому вызывает onStructure() и форма рисуется заново.

import { el } from "../dom.js";
import { ANSWER_TYPES, setAnswerType } from "./draft.js";

let uid = 0;
const nextId = (prefix) => `${prefix}-${(uid += 1)}`;

function field(label, control, hint) {
  const id = nextId("ck");
  control.id = id;
  return el(
    "div",
    { class: "field" },
    el("label", { class: "field__label", for: id }, label),
    control,
    hint ? el("span", { class: "muted" }, hint) : null,
  );
}

function textInput(value, onInput, attrs = {}) {
  return el("input", { class: "input", type: "text", value, oninput: (e) => onInput(e.target.value), ...attrs });
}

function textArea(value, onInput, rows = 2) {
  return el("textarea", { class: "input", rows: String(rows), value, oninput: (e) => onInput(e.target.value) });
}

function select(options, current, onChange) {
  return el(
    "select",
    { class: "input", onchange: (e) => onChange(e.target.value) },
    options.map((option) =>
      el("option", { value: option.value, selected: option.value === current }, option.label),
    ),
  );
}

function scaleEditor(criterion, onStructure) {
  const rows = criterion.scale.map((step, index) =>
    el(
      "div",
      { class: "toolbar" },
      field(
        "Балл",
        el("input", {
          class: "input",
          type: "number",
          min: "0",
          step: "1",
          value: String(step.value),
          oninput: (e) => {
            step.value = e.target.value;
          },
        }),
      ),
      el(
        "div",
        { class: "field", style: "flex: 1 1 16rem" },
        el("span", { class: "field__label" }, "Когда ставить"),
        textInput(step.label, (value) => {
          step.label = value;
        }, { "aria-label": `Описание ступени ${index + 1}` }),
      ),
      el(
        "button",
        {
          class: "btn btn--small",
          type: "button",
          onclick: () => {
            criterion.scale.splice(index, 1);
            onStructure();
          },
        },
        "Убрать ступень",
      ),
    ),
  );
  const add = el(
    "button",
    {
      class: "btn btn--small",
      type: "button",
      onclick: () => {
        criterion.scale.push({ value: 0, label: "" });
        onStructure();
      },
    },
    "Добавить ступень",
  );
  return el(
    "div",
    { class: "editor" },
    el("span", { class: "field__label" }, "Шкала: верхняя ступень даёт полный вес"),
    rows,
    el("div", {}, add),
  );
}

export function criterionForm(criterion, sections, { onStructure, onWeight, onRemove }) {
  const isFlag = criterion.answer_type === "flag";
  const sectionOptions = [{ value: "", label: "Без секции" }, ...sections.map((s) => ({ value: s.id, label: s.title }))];

  const weight = el("input", {
    class: "input",
    type: "number",
    min: "0",
    step: "any",
    value: String(criterion.weight),
    disabled: isFlag,
    oninput: (e) => {
      criterion.weight = e.target.value;
      onWeight();
    },
  });

  const allowNa = el("input", {
    type: "checkbox",
    checked: criterion.allow_na,
    disabled: isFlag,
    onchange: (e) => {
      criterion.allow_na = e.target.checked;
      onStructure();
    },
  });

  return el(
    "section",
    { class: "panel" },
    el(
      "div",
      { class: "panel__head" },
      el("h2", { class: "panel__title" }, `${criterion.id || "Новый критерий"}: ${criterion.title || "без названия"}`),
      el("button", { class: "btn btn--small", type: "button", onclick: onRemove }, "Удалить критерий"),
    ),
    el(
      "div",
      { class: "editor", style: "padding: var(--space-3)" },
      el(
        "div",
        { class: "toolbar" },
        field("id", textInput(criterion.id, (value) => {
          criterion.id = value;
        })),
        field("Секция", select(sectionOptions, criterion.section_id, (value) => {
          criterion.section_id = value;
        })),
        field("Тип ответа", select(ANSWER_TYPES, criterion.answer_type, (value) => {
          setAnswerType(criterion, value);
          onStructure();
        })),
        field("Вес", weight, isFlag ? "Флаг не даёт баллов" : null),
      ),
      field("Название", textInput(criterion.title, (value) => {
        criterion.title = value;
      })),
      field("Как оценивать", textArea(criterion.description, (value) => {
        criterion.description = value;
      })),
      isFlag
        ? null
        : el("label", { class: "decision__choice" }, allowNa, "Разрешить N/A"),
      criterion.allow_na && !isFlag
        ? field("Когда ставить N/A", textArea(criterion.na_condition, (value) => {
            criterion.na_condition = value;
          }))
        : null,
      criterion.answer_type === "scale" ? scaleEditor(criterion, onStructure) : null,
      field(
        "Подсказка модели (необязательно)",
        textArea(criterion.llm_hint, (value) => {
          criterion.llm_hint = value;
        }, 3),
        "Правила разметки для спорных случаев. Модель видит её вместе с описанием.",
      ),
    ),
  );
}
