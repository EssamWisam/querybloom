import { base } from "$app/paths";

const SESSION_KEY = "grasp:abstat-session";

let authListeners = [];

export function onAuthChange(callback) {
  authListeners.push(callback);
  return () => {
    authListeners = authListeners.filter((cb) => cb !== callback);
  };
}

function notifyAuthListeners(session) {
  for (const listener of authListeners) {
    try {
      listener(session, extractAccessToken(session));
    } catch (e) {
      console.error("Error in auth listener:", e);
    }
  }
}

function jsonHeaders(token = null) {
  const headers = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  return headers;
}

async function readJson(response) {
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message =
      payload?.detail?.message || payload?.detail || payload?.msg || response.statusText;
    throw new Error(typeof message === "string" ? message : JSON.stringify(message));
  }
  return payload;
}

export function extractAccessToken(session) {
  return session?.access_token || session?.session?.access_token || null;
}

export function extractRefreshToken(session) {
  return session?.refresh_token || session?.session?.refresh_token || null;
}

export function isSessionExpiringSoon(session, thresholdSeconds = 120) {
  if (!session) return true;
  if (session.expires_at) {
    const nowSec = Math.floor(Date.now() / 1000);
    return nowSec >= (Number(session.expires_at) - thresholdSeconds);
  }
  return false;
}

export function loadStoredSession() {
  if (typeof window === "undefined") return null;
  try {
    const value = window.localStorage.getItem(SESSION_KEY);
    return value ? JSON.parse(value) : null;
  } catch {
    return null;
  }
}

export function saveStoredSession(session) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(SESSION_KEY, JSON.stringify(session));
  notifyAuthListeners(session);
}

export function clearStoredSession() {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(SESSION_KEY);
  notifyAuthListeners(null);
}

let refreshPromise = null;

export async function refreshSession(refreshToken) {
  const response = await fetch(base + "/api/v1/auth/refresh", {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
  return readJson(response);
}

export async function refreshSessionDeduplicated(refreshToken) {
  if (!refreshToken) return null;
  if (refreshPromise) return refreshPromise;
  refreshPromise = (async () => {
    try {
      const newSession = await refreshSession(refreshToken);
      if (newSession && extractAccessToken(newSession)) {
        saveStoredSession(newSession);
        return newSession;
      }
      clearStoredSession();
      return null;
    } catch (err) {
      console.warn("Auto-refresh session failed:", err);
      clearStoredSession();
      return null;
    } finally {
      refreshPromise = null;
    }
  })();
  return refreshPromise;
}

export async function ensureFreshSession() {
  const stored = loadStoredSession();
  if (!stored) return null;
  const refreshToken = extractRefreshToken(stored);
  if (!refreshToken) return stored;
  if (isSessionExpiringSoon(stored)) {
    const refreshed = await refreshSessionDeduplicated(refreshToken);
    if (refreshed) return refreshed;
  }
  return stored;
}

export async function authFetch(url, options = {}, token = null) {
  let effectiveToken = token;
  if (!effectiveToken && typeof window !== "undefined") {
    const freshSession = await ensureFreshSession();
    effectiveToken = extractAccessToken(freshSession);
  }

  const reqHeaders = {
    ...jsonHeaders(effectiveToken),
    ...(options.headers || {}),
  };

  let response = await fetch(url, { ...options, headers: reqHeaders });

  if ((response.status === 401 || response.status === 403) && typeof window !== "undefined") {
    const stored = loadStoredSession();
    const refreshToken = extractRefreshToken(stored);
    if (refreshToken) {
      const refreshedSession = await refreshSessionDeduplicated(refreshToken);
      const newAccessToken = extractAccessToken(refreshedSession);
      if (newAccessToken) {
        const retryHeaders = {
          ...reqHeaders,
          ...jsonHeaders(newAccessToken),
          ...(options.headers || {}),
        };
        response = await fetch(url, { ...options, headers: retryHeaders });
      }
    }
  }

  return response;
}

export async function login(email, password) {
  const response = await fetch(base + "/api/v1/auth/login", {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({ email, password }),
  });
  return readJson(response);
}

export async function signup(email, password, displayName = null) {
  const response = await fetch(base + "/api/v1/auth/signup", {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({ email, password, display_name: displayName || null }),
  });
  return readJson(response);
}

export async function loadDefaults() {
  const response = await fetch(base + "/api/v1/abstat/defaults");
  return readJson(response);
}

export async function loadRuns(token, limit = 30) {
  const response = await authFetch(`${base}/api/v1/runs?limit=${limit}`, {}, token);
  return readJson(response);
}

export async function loadRun(token, runId) {
  const response = await authFetch(`${base}/api/v1/runs/${encodeURIComponent(runId)}`, {}, token);
  return readJson(response);
}

export async function cleanupStaleRuns(token) {
  const response = await authFetch(base + "/api/v1/runs/cleanup-stale", {
    method: "POST",
  }, token);
  return readJson(response);
}

export async function deleteRun(token, runId) {
  const response = await authFetch(`${base}/api/v1/runs/${runId}`, {
    method: "DELETE",
  }, token);
  return readJson(response);
}

export async function cancelRun(token, runId) {
  const response = await authFetch(`${base}/api/v1/abstat/sample/${encodeURIComponent(runId)}/cancel`, {
    method: "POST",
  }, token);
  return readJson(response);
}

export async function loadRunEvents(token, runId, options = {}) {
  const params = new URLSearchParams();
  if (options.after) params.set("after", options.after);
  if (options.limit) params.set("limit", String(options.limit));
  const query = params.toString();
  const response = await authFetch(`${base}/api/v1/runs/${runId}/events${query ? `?${query}` : ""}`, {}, token);
  return readJson(response);
}

export async function loadRunSubgraphs(token, runId) {
  const response = await authFetch(`${base}/api/v1/runs/${runId}/subgraphs`, {}, token);
  return readJson(response);
}

export async function loadRunQaPairs(token, runId, options = {}) {
  const params = new URLSearchParams();
  if (options.activeOnly === false) params.set("active_only", "false");
  const query = params.toString();
  const response = await authFetch(
    `${base}/api/v1/runs/${runId}/qa-pairs${query ? `?${query}` : ""}`,
    {},
    token,
  );
  return readJson(response);
}

function parseSseFrame(frame) {
  const lines = frame.split(/\r?\n/);
  let event = "message";
  let isCommentOnly = true;
  const dataLines = [];
  for (const line of lines) {
    if (line.startsWith(":")) continue;
    isCommentOnly = false;
    if (line.startsWith("event:")) event = line.slice(6).trim();
    if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
  }
  if (isCommentOnly) return null;
  const rawData = dataLines.join("\n");
  let data = rawData;
  if (rawData) {
    try {
      data = JSON.parse(rawData);
    } catch {
      data = rawData;
    }
  }
  return { event, data };
}

async function streamPost(url, token, payload, onFrame, signal = null) {
  const response = await authFetch(url, {
    method: "POST",
    body: JSON.stringify(payload),
    signal,
  }, token);
  if (!response.ok || !response.body) await readJson(response);

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const frame = buffer.slice(0, boundary).trim();
      buffer = buffer.slice(boundary + 2);
      if (frame) {
        const parsed = parseSseFrame(frame);
        if (parsed) onFrame(parsed);
      }
      boundary = buffer.indexOf("\n\n");
    }
  }

  const tail = buffer.trim();
  if (tail) {
    const parsed = parseSseFrame(tail);
    if (parsed) onFrame(parsed);
  }
}

export function streamSampling(token, payload, onFrame, signal = null) {
  return streamPost(base + "/api/v1/abstat/sample/stream", token, payload, onFrame, signal);
}

export async function skipDiscovery(token, runId) {
  return authFetch(`${base}/api/v1/abstat/sample/${encodeURIComponent(runId)}/skip-discovery`, {
    method: "POST",
  }, token);
}

export async function skipSubgraphs(token, runId) {
  return authFetch(`${base}/api/v1/abstat/sample/${encodeURIComponent(runId)}/skip-subgraphs`, {
    method: "POST",
  }, token);
}

export function streamLlm(token, payload, onFrame, signal = null) {
  return streamPost(base + "/api/v1/abstat/llm/stream", token, payload, onFrame, signal);
}
