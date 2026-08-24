const SESSION_KEY = "grasp:abstat-session";

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
}

export function clearStoredSession() {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(SESSION_KEY);
}

export async function login(email, password) {
  const response = await fetch("/api/v1/auth/login", {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({ email, password }),
  });
  return readJson(response);
}

export async function signup(email, password, displayName = null) {
  const response = await fetch("/api/v1/auth/signup", {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({ email, password, display_name: displayName || null }),
  });
  return readJson(response);
}

export async function loadDefaults() {
  const response = await fetch("/api/v1/abstat/defaults");
  return readJson(response);
}

export async function loadRuns(token, limit = 30) {
  const response = await fetch(`/api/v1/runs?limit=${limit}`, {
    headers: jsonHeaders(token),
  });
  return readJson(response);
}

export async function loadRun(token, runId) {
  const response = await fetch(`/api/v1/runs/${encodeURIComponent(runId)}`, {
    headers: jsonHeaders(token),
  });
  return readJson(response);
}

export async function cleanupStaleRuns(token) {
  const response = await fetch("/api/v1/runs/cleanup-stale", {
    method: "POST",
    headers: jsonHeaders(token),
  });
  return readJson(response);
}

export async function deleteRun(token, runId) {
  const response = await fetch(`/api/v1/runs/${runId}`, {
    method: "DELETE",
    headers: jsonHeaders(token),
  });
  return readJson(response);
}

export async function cancelRun(token, runId) {
  const response = await fetch(`/api/v1/abstat/sample/${encodeURIComponent(runId)}/cancel`, {
    method: "POST",
    headers: jsonHeaders(token),
  });
  return readJson(response);
}

export async function loadRunEvents(token, runId, options = {}) {
  const params = new URLSearchParams();
  if (options.after) params.set("after", options.after);
  if (options.limit) params.set("limit", String(options.limit));
  const query = params.toString();
  const response = await fetch(`/api/v1/runs/${runId}/events${query ? `?${query}` : ""}`, {
    headers: jsonHeaders(token),
  });
  return readJson(response);
}

export async function loadRunSubgraphs(token, runId) {
  const response = await fetch(`/api/v1/runs/${runId}/subgraphs`, {
    headers: jsonHeaders(token),
  });
  return readJson(response);
}

export async function loadRunQaPairs(token, runId, options = {}) {
  const params = new URLSearchParams();
  if (options.activeOnly === false) params.set("active_only", "false");
  const query = params.toString();
  const response = await fetch(
    `/api/v1/runs/${runId}/qa-pairs${query ? `?${query}` : ""}`,
    { headers: jsonHeaders(token) },
  );
  return readJson(response);
}

function parseSseFrame(frame) {
  const lines = frame.split(/\r?\n/);
  let event = "message";
  const dataLines = [];
  for (const line of lines) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
  }
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
  const response = await fetch(url, {
    method: "POST",
    headers: jsonHeaders(token),
    body: JSON.stringify(payload),
    signal,
  });
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
      if (frame) onFrame(parseSseFrame(frame));
      boundary = buffer.indexOf("\n\n");
    }
  }

  const tail = buffer.trim();
  if (tail) onFrame(parseSseFrame(tail));
}

export function streamSampling(token, payload, onFrame, signal = null) {
  return streamPost("/api/v1/abstat/sample/stream", token, payload, onFrame, signal);
}

export async function skipDiscovery(token, runId) {
  return fetch(`/api/v1/abstat/sample/${encodeURIComponent(runId)}/skip-discovery`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
}

export async function skipSubgraphs(token, runId) {
  return fetch(`/api/v1/abstat/sample/${encodeURIComponent(runId)}/skip-subgraphs`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
}

export function streamLlm(token, payload, onFrame, signal = null) {
  return streamPost("/api/v1/abstat/llm/stream", token, payload, onFrame, signal);
}
