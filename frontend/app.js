// Оболочка: шапка, хеш-роутер и единое состояние загрузки и ошибки.
//
// Экран - это функция render(ctx), она рисует только внутри ctx.view:
//   ctx.params    части адреса, например id оценки
//   ctx.run(fn, { label, button, retry, silent })  выполняет действие; ошибку показывает
//                 в общей строке и возвращает undefined. silent не показывает занятость.
//   ctx.notify(text)   сообщение об успехе
//   ctx.go(hash)       переход на другой экран
//   ctx.isActive()     false, когда пользователь ушёл с экрана
//   ctx.onLeave(fn)    уборка при уходе с экрана

import { renderChecklist } from "./checklist/editor.js";
import { el } from "./dom.js";
import { renderAppeals } from "./screens/appeals.js";
import { renderCard } from "./screens/card.js";
import { renderList } from "./screens/list.js";

const ROUTES = [
  { pattern: /^\/$/, nav: "list", render: renderList },
  { pattern: /^\/card\/([^/]+)$/, nav: "list", render: renderCard },
  { pattern: /^\/appeals$/, nav: "appeals", render: renderAppeals },
  { pattern: /^\/checklist$/, nav: "checklist", render: renderChecklist },
];

const NAV = [
  { id: "list", href: "#/", label: "Диалоги" },
  { id: "appeals", href: "#/appeals", label: "Апелляции" },
  { id: "checklist", href: "#/checklist", label: "Чек-лист" },
];

function buildShell(root) {
  const links = NAV.map((item) => ({
    id: item.id,
    node: el("a", { class: "nav__link", href: item.href }, item.label),
  }));
  const busy = el("span", { class: "app-busy", role: "status" });
  const header = el(
    "header",
    { class: "app-header" },
    el(
      "a",
      { class: "brand", href: "#/" },
      el("span", { class: "brand__mark" }, "CQA"),
      el("span", { class: "brand__name" }, "Контроль качества диалогов"),
    ),
    el("nav", { class: "nav", "aria-label": "Разделы" }, links.map((link) => link.node)),
    busy,
  );
  const messages = el("div", { class: "app-messages" });
  const outlet = el("main", { class: "app-main" });
  root.replaceChildren(el("div", { class: "app-top" }, header, messages), outlet);
  return { links, busy, messages, outlet };
}

function messageLine({ kind, text, retry }, dismiss) {
  // Строка убирается сразу: иначе старая ошибка висит после удачного повтора,
  // а второе нажатие запускает действие дважды.
  const retryNow = () => {
    dismiss();
    retry();
  };
  return el(
    "div",
    { class: `message message--${kind}`, role: kind === "error" ? "alert" : "status" },
    el("span", { class: "message__text" }, text),
    retry ? el("button", { class: "btn btn--small", type: "button", onclick: retryNow }, "Повторить") : null,
    el("button", { class: "btn btn--small", type: "button", onclick: dismiss }, "Закрыть"),
  );
}

function createStatus(shell) {
  let tasks = [];

  const paintBusy = () => {
    shell.busy.textContent = tasks.at(-1)?.label ?? "";
  };
  const clearMessage = () => shell.messages.replaceChildren();
  const show = (message) => shell.messages.replaceChildren(messageLine(message, clearMessage));
  const begin = (label) => {
    const task = { label };
    tasks = [...tasks, task];
    paintBusy();
    return () => {
      tasks = tasks.filter((item) => item !== task);
      paintBusy();
    };
  };

  return { begin, show, clearMessage };
}

function createContext(view, params, status) {
  let cleanups = [];
  let active = true;

  async function run(action, options = {}) {
    const { label = "Выполняется…", button, retry, silent = false } = options;
    if (!silent) status.clearMessage();
    const finish = silent ? () => {} : status.begin(label);
    if (button) button.disabled = true;
    try {
      return await action();
    } catch (error) {
      // Фоновый опрос ушедшего экрана не должен сыпать ошибки на новый экран.
      if (active || !silent) status.show({ kind: "error", text: error.message, retry });
      return undefined;
    } finally {
      finish();
      if (button) button.disabled = false;
    }
  }

  return {
    view,
    params,
    run,
    notify: (text) => status.show({ kind: "ok", text }),
    go: (hash) => {
      window.location.hash = hash;
    },
    isActive: () => active,
    onLeave: (cleanup) => {
      cleanups = [...cleanups, cleanup];
    },
    leave: () => {
      active = false;
      cleanups.forEach((cleanup) => cleanup());
    },
  };
}

function decodeParam(value) {
  try {
    return decodeURIComponent(value);
  } catch {
    return value; // битый адрес: сервер ответит понятной ошибкой 404
  }
}

function matchRoute(hash) {
  const path = hash.replace(/^#/, "") || "/";
  for (const route of ROUTES) {
    const match = route.pattern.exec(path);
    if (match) return { route, params: match.slice(1).map(decodeParam) };
  }
  return { route: null, params: [] };
}

function markActiveLink(links, navId) {
  links.forEach(({ id, node }) => {
    if (id === navId) node.setAttribute("aria-current", "page");
    else node.removeAttribute("aria-current");
  });
}

function placeholder(text) {
  return el("p", { class: "placeholder" }, text);
}

async function loadScreen(screen, route, retry) {
  const render = async () => {
    await route.render(screen);
    return true;
  };
  const loaded = await screen.run(render, { label: "Загрузка…", retry });
  if (!loaded) screen.view.replaceChildren(placeholder("Экран не загружен, причина указана выше."));
}

function startApp(root) {
  const shell = buildShell(root);
  const status = createStatus(shell);
  let screen = null;

  async function open() {
    const { route, params } = matchRoute(window.location.hash);
    screen?.leave();
    status.clearMessage();
    markActiveLink(shell.links, route?.nav);
    const view = el("section", { class: "view", tabindex: "-1" }, placeholder("Загрузка…"));
    shell.outlet.replaceChildren(view);
    window.scrollTo(0, 0);
    view.focus({ preventScroll: true });
    screen = createContext(view, params, status);
    if (route) await loadScreen(screen, route, open);
    else view.replaceChildren(placeholder("Такого экрана нет. Откройте раздел в шапке."));
  }

  window.addEventListener("hashchange", open);
  open();
}

startApp(document.getElementById("cqa-app"));
