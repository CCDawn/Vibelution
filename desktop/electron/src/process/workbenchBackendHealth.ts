import { probeTcpConnect } from "../lifecycle/mainLine/observation.js";

export const BACKEND_CONNECT_TIMEOUT_MS = 300;
export const BACKEND_HEALTH_HTTP_TIMEOUT_MS = 1500;
// Route warm-up may outlive the old budget under memory pressure. API callers
// retain the full readiness wait; window startup explicitly requests the shell.
export const BACKEND_HEALTH_WAIT_MS = 180_000;
export const BACKEND_HEALTH_POLL_MS = 100;

export type WorkbenchHealthResponse = { status: number; json?: () => Promise<unknown> };
export type WorkbenchReadiness = "routes" | "shell";

export function workbenchHealthUrl(port: number, host = "127.0.0.1"): string {
  return `http://${host}:${Math.trunc(port)}/api/health`;
}

export function workbenchHealthPayloadReady(payload: unknown, readiness: WorkbenchReadiness = "routes"): boolean {
  if (typeof payload !== "object" || payload === null || Array.isArray(payload)) {
    return false;
  }
  const body = payload as Record<string, unknown>;
  const ready = readiness === "shell"
    ? body.shellReady === true || (body.shellReady === undefined && body.routesReady === true)
    : body.routesReady === true;
  return body.status === "ok" && ready;
}

export function defaultFetchWorkbenchHealth(input: {
  httpTimeoutMs: number;
  signal?: AbortSignal;
}): (url: string) => Promise<WorkbenchHealthResponse> {
  const signal = input.signal;
  const httpTimeoutMs = Math.max(1, input.httpTimeoutMs);
  return (target) =>
    fetch(target, {
      method: "GET",
      redirect: "manual",
      signal: signal
        ? AbortSignal.any([signal, AbortSignal.timeout(httpTimeoutMs)])
        : AbortSignal.timeout(httpTimeoutMs)
    });
}

export async function probeBackendHealthy(input: {
  port: number;
  host?: string;
  readiness?: WorkbenchReadiness;
  connectTimeoutMs?: number;
  httpTimeoutMs?: number;
  signal?: AbortSignal;
  connect?: (port: number, host: string) => Promise<boolean>;
  fetchHealth?: (url: string) => Promise<WorkbenchHealthResponse>;
}): Promise<boolean> {
  input.signal?.throwIfAborted();
  const host = input.host?.trim() || "127.0.0.1";
  const port = Math.trunc(input.port);
  if (!Number.isFinite(port) || port <= 0) {
    return false;
  }
  const connect = input.connect ?? ((nextPort, nextHost) =>
    probeTcpConnect(nextPort, nextHost, input.connectTimeoutMs ?? BACKEND_CONNECT_TIMEOUT_MS));
  if (!(await connect(port, host))) {
    return false;
  }
  input.signal?.throwIfAborted();
  const url = workbenchHealthUrl(port, host);
  const httpTimeoutMs = Math.max(1, input.httpTimeoutMs ?? BACKEND_HEALTH_HTTP_TIMEOUT_MS);
  const fetchHealth =
    input.fetchHealth ?? defaultFetchWorkbenchHealth({ httpTimeoutMs, signal: input.signal });
  try {
    const response = await fetchHealth(url);
    if (response.status !== 200) {
      return false;
    }
    // HTTP 200 alone is insufficient: the requested readiness must be proven.
    if (typeof response.json !== "function") {
      return false;
    }
    return workbenchHealthPayloadReady(await response.json(), input.readiness);
  } catch {
    input.signal?.throwIfAborted();
    return false;
  }
}

export async function waitForBackendHealthy(input: {
  port: number;
  host?: string;
  readiness?: WorkbenchReadiness;
  timeoutMs?: number;
  pollIntervalMs?: number;
  signal?: AbortSignal;
  childError?: () => Error | null;
  childAlive?: () => boolean;
  now?: () => number;
  delay?: (ms: number) => Promise<void>;
  connect?: (port: number, host: string) => Promise<boolean>;
  fetchHealth?: (url: string) => Promise<WorkbenchHealthResponse>;
}): Promise<void> {
  const timeoutMs = Math.max(1, input.timeoutMs ?? BACKEND_HEALTH_WAIT_MS);
  const pollIntervalMs = Math.max(0, input.pollIntervalMs ?? BACKEND_HEALTH_POLL_MS);
  const now = input.now ?? Date.now;
  const delay = input.delay ?? ((ms) => abortableDelay(ms, input.signal));
  const startedAt = now();
  let lastError = "";
  while (now() - startedAt < timeoutMs) {
    input.signal?.throwIfAborted();
    const childError = input.childError?.();
    if (childError !== null && childError !== undefined) {
      throw childError;
    }
    if (input.childAlive && !input.childAlive()) {
      throw new Error(`workbench backend exited before it became healthy at ${workbenchHealthUrl(input.port, input.host)}`);
    }
    try {
      if (await probeBackendHealthy(input)) {
        return;
      }
      lastError = "health probe failed";
    } catch (error: unknown) {
      input.signal?.throwIfAborted();
      lastError = error instanceof Error ? error.message : String(error);
    }
    if (now() - startedAt >= timeoutMs) {
      break;
    }
    if (pollIntervalMs > 0) {
      await delay(pollIntervalMs);
    }
  }
  throw new Error(
    `workbench backend was not healthy at ${workbenchHealthUrl(input.port, input.host)}${lastError ? `: ${lastError}` : ""}`
  );
}

async function abortableDelay(timeoutMs: number, signal?: AbortSignal): Promise<void> {
  signal?.throwIfAborted();
  await new Promise<void>((resolve, reject) => {
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, timeoutMs);
    const onAbort = () => {
      clearTimeout(timer);
      signal?.removeEventListener("abort", onAbort);
      const reason = signal?.reason;
      reject(reason instanceof Error ? reason : new Error("workbench health wait aborted"));
    };
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}
