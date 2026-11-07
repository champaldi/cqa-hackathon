// Общий контракт с сервером: единственное место с адресами.
// Меняется только через ветку contract/* с согласия всей команды.
// Ответ всегда приходит в конверте {success, data, error}, наружу отдаётся только data.

const BASE = window.CQA_API_BASE ?? "";

const NETWORK_ERROR = "Сервер недоступен. Проверьте, что он запущен, и повторите.";

function buildUrl(path, query = {}) {
  const filled = Object.entries(query).filter(([, value]) => value !== undefined && value !== null);
  const search = new URLSearchParams(filled).toString();
  const address = BASE ? `${BASE}/${path}` : path;
  return search ? `${address}?${search}` : address;
}

async function readEnvelope(response) {
  try {
    return await response.json();
  } catch (cause) {
    throw new Error(`Сервер вернул не JSON (HTTP ${response.status}).`, { cause });
  }
}

async function send(url, options) {
  try {
    return await fetch(url, options);
  } catch (cause) {
    throw new Error(NETWORK_ERROR, { cause });
  }
}

async function unwrap(response) {
  const envelope = await readEnvelope(response);
  if (envelope?.success) return envelope.data;
  throw new Error(envelope?.error ?? `Ошибка сервера (HTTP ${response.status}).`);
}

async function get(path, query) {
  return unwrap(await send(buildUrl(path, query)));
}

async function post(path, body) {
  const options = {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
  return unwrap(await send(buildUrl(path), options));
}

const part = encodeURIComponent;

export const api = {
  health: () => get("api/health"),

  listDialogs: (groupId) => get("api/dialogs", { group_id: groupId }),
  getDialog: (id) => get(`api/dialogs/${part(id)}`),
  importGroup: (groupId) => post("api/dialogs/import", { group_id: groupId }),

  listChecklists: () => get("api/checklists"),
  activeChecklist: () => get("api/checklists/active"),
  getChecklist: (id) => get(`api/checklists/${part(id)}`),
  saveChecklist: (draft) => post("api/checklists", draft),

  evaluate: (conversationId, checklistId) =>
    post("api/evaluations", { conversation_id: conversationId, checklist_id: checklistId ?? null }),
  getCard: (evaluationId) => get(`api/evaluations/${part(evaluationId)}`),

  createAppeal: (evaluationId, { criterion_id, comment }) =>
    post(`api/evaluations/${part(evaluationId)}/appeals`, { criterion_id, comment }),
  listAppeals: ({ status, evaluationId } = {}) =>
    get("api/appeals", { status, evaluation_id: evaluationId }),
  decide: (appealId, decision) => post(`api/appeals/${part(appealId)}/decision`, decision),

  startBatch: (groupId, checklistId) =>
    post("api/batches", { group_id: groupId, checklist_id: checklistId ?? null }),
  getBatch: (id) => get(`api/batches/${part(id)}`),
};
