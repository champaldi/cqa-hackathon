// Маленький помощник для разметки. Строки попадают в DOM только текстовыми узлами:
// транскрипт приходит извне, поэтому разметка из строк здесь не собирается.

const PROPERTIES = new Set(["value", "checked", "disabled", "selected", "hidden"]);

function setProp(node, key, value) {
  if (value === null || value === undefined || value === false) return;
  if (key === "class") node.className = value;
  else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
  else if (PROPERTIES.has(key)) node[key] = value;
  else node.setAttribute(key, value === true ? "" : String(value));
}

function appendChild(node, child) {
  if (child === null || child === undefined || child === false) return;
  if (Array.isArray(child)) child.forEach((item) => appendChild(node, item));
  else if (child instanceof Node) node.appendChild(child);
  else node.appendChild(document.createTextNode(String(child)));
}

// el("a", { class: "btn", href: "#/", onclick: fn }, "Текст", otherNode, [nodes], null)
export function el(tag, props, ...children) {
  const node = document.createElement(tag);
  Object.entries(props ?? {}).forEach(([key, value]) => setProp(node, key, value));
  appendChild(node, children);
  return node;
}

export function clear(node) {
  node.replaceChildren();
}
