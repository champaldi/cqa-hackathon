// Транскрипт карточки: реплики, прокрутка к доказательству и подсветка.

import { el } from "../dom.js";
import { SPEAKER_LABELS } from "../format.js";

const MARKS = ["turn--hit", "turn--range"];

export function rangeOf(start, end) {
  const length = Math.max(end - start + 1, 0);
  return Array.from({ length }, (_, offset) => start + offset);
}

// id передаёт только карточка: на экране апелляций реплики разных диалогов идут подряд.
export function turnView(turn, id) {
  return el(
    "li",
    { id, class: `turn turn--${turn.speaker}` },
    el(
      "div",
      { class: "turn__meta" },
      el("span", { class: "turn__speaker" }, SPEAKER_LABELS[turn.speaker] ?? turn.speaker),
      el("span", { class: "turn__index" }, `#${turn.index}`),
      el("span", { class: "turn__time" }, turn.timestamp),
    ),
    el("p", { class: "turn__text" }, turn.text),
  );
}

function scrollBehavior() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
}

// В двух колонках прокручивается сам список, чтобы критерий не уезжал со страницы.
function scrollToRow(list, row) {
  const behavior = scrollBehavior();
  if (list.scrollHeight <= list.clientHeight) {
    row.scrollIntoView({ behavior, block: "center" });
    return;
  }
  list.scrollTo({ top: row.offsetTop - (list.clientHeight - row.offsetHeight) / 2, behavior });
}

export function createTranscript(turns) {
  const rows = new Map(turns.map((turn) => [turn.index, turnView(turn, `turn-${turn.index}`)]));
  const list = el("ol", { class: "transcript__list" }, [...rows.values()]);
  let marked = [];

  const mark = (indices, className) => {
    marked.forEach((row) => row.classList.remove(...MARKS));
    marked = indices.map((index) => rows.get(index)).filter(Boolean);
    marked.forEach((row) => row.classList.add(className));
    if (marked.length) scrollToRow(list, marked[0]);
  };

  const node = el(
    "section",
    { class: "panel transcript", "aria-label": "Транскрипт" },
    el(
      "div",
      { class: "panel__head" },
      el("h2", { class: "panel__title" }, "Транскрипт"),
      el("span", { class: "muted" }, `реплик: ${turns.length}`),
    ),
    turns.length ? list : el("p", { class: "placeholder" }, "В диалоге нет реплик."),
  );

  return {
    node,
    has: (index) => rows.has(index),
    hasRange: (start, end) => turns.some(({ index }) => index >= start && index <= end),
    focusTurn: (index) => mark([index], "turn--hit"),
    focusRange: (start, end) => mark(rangeOf(start, end), "turn--range"),
  };
}
