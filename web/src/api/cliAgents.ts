import { fetchJson } from "./client";

function sendJson<T>(url: string, method: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  return fetchJson<T>(url, {
    method,
    signal,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

export function ensureCliAgentTerminalSession<T>(
  body: Record<string, unknown>,
  options?: { signal?: AbortSignal },
): Promise<T> {
  return sendJson<T>("/api/cli-agents/terminal-sessions/ensure", "POST", body, options?.signal);
}

export function sendCliAgentTerminalInput<T>(
  sessionId: string,
  body: Record<string, unknown>,
): Promise<T> {
  return sendJson<T>(
    `/api/cli-agents/terminal-sessions/${encodeURIComponent(sessionId)}/input`,
    "POST",
    body,
  );
}

export function resizeCliAgentTerminal<T>(
  sessionId: string,
  body: Record<string, unknown>,
): Promise<T> {
  return sendJson<T>(
    `/api/cli-agents/terminal-sessions/${encodeURIComponent(sessionId)}/resize`,
    "POST",
    body,
  );
}

export function stopCliAgentTerminalSession<T>(sessionId: string): Promise<T> {
  return sendJson<T>(
    `/api/cli-agents/terminal-sessions/${encodeURIComponent(sessionId)}/stop`,
    "POST",
  );
}
