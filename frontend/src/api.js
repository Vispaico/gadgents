const TOKEN_KEY = "gadgents_token";

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || "";
}
export function setToken(t) {
  t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY);
}

function authHeader() {
  const t = getToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

// Global quality/cost mode (null = agent default). Set by the header toggle.
let _mode = null;
export function setMode(m) {
  _mode = m;
}
export function getMode() {
  return _mode;
}

// Append the active mode as a query param (backend reads it from ?mode=).
function withMode(path) {
  if (!_mode) return path;
  const sep = path.includes("?") ? "&" : "?";
  return `${path}${sep}mode=${_mode}`;
}

async function req(method, path, body) {
  const url = withMode(`/api${path}`);
  const res = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json", ...authHeader() },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401) {
    setToken("");
    throw new Error("Session expired. Please log in again.");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`);
  return data;
}

export const api = {
  register: (email, password) => req("POST", "/auth/register", { email, password }),
  login: (email, password) => req("POST", "/auth/login", { email, password }),
  listAgents: () => req("GET", "/agents"),
  chat: (id, message) => req("POST", `/agents/${id}/chat`, { message }),
  plans: () => req("GET", "/billing/plans"),
  me: () => req("GET", "/billing/me"),
  buy: (plan) => req("POST", "/billing/buy", { plan }),
  pipeline: (material, platforms, output_mode = "content", urls = [], instructions = "") =>
    req("POST", "/pipeline/content", { material, platforms, output_mode, urls, instructions }),
  pipelineBriefs: () => req("GET", "/pipeline/briefs"),
  pipelineBrief: (id) => req("GET", `/pipeline/briefs/${id}`),
  socialListen: (topic, platforms, limit = 20) =>
    req("POST", "/social/listen", { topic, platforms, limit }),
  socialQueries: () => req("GET", "/social/queries"),
  socialPosts: (queryId) => req("GET", `/social/queries/${queryId}/posts`),
  leadIcpChat: (message, history) =>
    req("POST", "/leadfinder/icp-chat", { message, history }),
  leadRun: (icp) => req("POST", "/leadfinder/run", { icp }),
  leadList: () => req("GET", "/leadfinder/leads"),
  wanRun: (source_image, concept, format_kind = "", title = "") =>
    req("POST", "/wan/run", { source_image, concept, format_kind, title }),
  wanBriefs: () => req("GET", "/wan/briefs"),
  config: () => req("GET", "/config"),
};
