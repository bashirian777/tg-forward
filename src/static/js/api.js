import { get, setBusy } from "./core.js";

const TOKEN_KEY = "tg_forwarder_web_token";
const EXPIRY_KEY = "tg_forwarder_web_expiry";
export const session = {
  token: localStorage.getItem(TOKEN_KEY) || "",
  expiresAt: Number(localStorage.getItem(EXPIRY_KEY)) || 0,
  ready: false,
};

function clearSession() {
  session.token = "";
  session.expiresAt = 0;
  session.ready = false;
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(EXPIRY_KEY);
}

export function showGate(message = "") {
  session.ready = false;
  document.dispatchEvent(new Event("auth:required"));
  get("auth-gate").hidden = false;
  get("app-content").hidden = true;
  get("auth-error").textContent = message;
}

function showApp() {
  session.ready = true;
  get("auth-gate").hidden = true;
  get("app-content").hidden = false;
  get("logout-btn").hidden = !session.token;
  document.dispatchEvent(new Event("auth:ready"));
}

export async function apiFetch(url, options = {}) {
  const headers = new Headers(options.headers || {});
  if (session.token) headers.set("Authorization", "Bearer " + session.token);
  const response = await fetch(url, {
    ...options,
    headers,
    signal: options.signal || AbortSignal.timeout(15000),
  });
  if (response.status === 401 && session.ready) {
    clearSession();
    showGate("登录已过期，请重新输入密码");
  }
  return response;
}

export async function initAuth() {
  get("logout-btn").addEventListener("click", () => {
    clearSession();
    showGate();
    get("auth-password").focus();
  });
  get("auth-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = get("auth-submit");
    setBusy(button, true);
    get("auth-error").textContent = "";
    try {
      const response = await fetch("/api/auth", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password: get("auth-password").value }),
        signal: AbortSignal.timeout(15000),
      });
      const data = await response.json();
      if (!response.ok)
        throw new Error(response.status === 401 ? "密码不正确，请重试" : "服务暂时不可用");
      session.token = data.token || "";
      session.expiresAt = Number(data.expires_at) || 0;
      if (session.token) localStorage.setItem(TOKEN_KEY, session.token);
      localStorage.setItem(EXPIRY_KEY, String(session.expiresAt));
      get("auth-form").reset();
      showApp();
    } catch (error) {
      get("auth-error").textContent = error.message || "无法连接到服务";
    } finally {
      setBusy(button, false);
    }
  });
  if (session.token && (!session.expiresAt || session.expiresAt * 1000 > Date.now())) {
    showApp();
    return;
  }
  clearSession();
  try {
    const response = await fetch("/api/auth", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: "" }),
      signal: AbortSignal.timeout(15000),
    });
    const data = await response.json();
    if (response.ok && data.auth_required === false) showApp();
    else showGate();
  } catch {
    showGate("无法连接到 Web 服务，请稍后重试");
  }
}
