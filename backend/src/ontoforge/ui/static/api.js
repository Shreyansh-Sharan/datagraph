// HTTP client: adds identity headers, turns API errors into ApiError, shows nothing itself.
export class ApiError extends Error {
  constructor(status, detail) { super(detail || `HTTP ${status}`); this.status = status; this.detail = detail; }
}

const store = {
  get actor() { return localStorage.getItem("of.actor") || ""; },
  set actor(v) { v ? localStorage.setItem("of.actor", v) : localStorage.removeItem("of.actor"); },
  get token() { return localStorage.getItem("of.token") || ""; },
  set token(v) { v ? localStorage.setItem("of.token", v) : localStorage.removeItem("of.token"); },
};
export const identity = store;
export let authConfig = { mode: "header", header: "X-Actor", default_role: "viewer" };

export async function loadAuthConfig() {
  try { authConfig = await (await fetch("/auth/config")).json(); } catch { /* keep defaults */ }
  return authConfig;
}

function headers(extra = {}) {
  const h = { Accept: "application/json", ...extra };
  if (authConfig.mode === "token") { if (store.token) h.Authorization = `Bearer ${store.token}`; }
  else if (store.actor) h[authConfig.header] = store.actor;
  return h;
}

async function request(method, url, body, opts = {}) {
  const init = { method, headers: headers(opts.headers) };
  if (body !== undefined) {
    if (opts.raw) init.body = body; else { init.body = JSON.stringify(body); init.headers["Content-Type"] = "application/json"; }
  }
  const res = await fetch(url, init);
  const ctype = res.headers.get("content-type") || "";
  const data = res.status === 204 ? null : ctype.includes("application/json") ? await res.json() : await res.text();
  if (!res.ok) {
    const detail = data && typeof data === "object" ? (typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail)) : String(data || res.statusText);
    throw new ApiError(res.status, detail);
  }
  return data;
}

export const api = {
  get: (url, opts) => request("GET", url, undefined, opts),
  post: (url, body, opts) => request("POST", url, body, opts),
  put: (url, body, opts) => request("PUT", url, body, opts),
  del: (url, opts) => request("DELETE", url, undefined, opts),
  text: (url) => request("GET", url, undefined, { headers: { Accept: "text/plain, text/turtle, */*" } }),
};

export const qs = (params) => {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") u.set(k, v);
  const s = u.toString();
  return s ? `?${s}` : "";
};

export const local = (iri) => (iri || "").split(/[#/]/).filter(Boolean).slice(-1)[0] || iri;
