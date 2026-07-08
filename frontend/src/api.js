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

async function req(method, path, body) {
  const res = await fetch(`/api${path}`, {
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
  pipeline: (material, platforms) =>
    req("POST", "/pipeline/content", { material, platforms }),
};
