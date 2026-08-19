export const DEFAULT_WORKBENCH_LOOPBACK_URL = "http://127.0.0.1:8002/";

export function workbenchLoopbackUrl(port?: number): string {
  if (typeof port === "number" && Number.isFinite(port) && port > 0) {
    return `http://127.0.0.1:${Math.trunc(port)}/`;
  }
  return DEFAULT_WORKBENCH_LOOPBACK_URL;
}

export async function waitForWorkbenchHttp(input: {
  url: string;
  timeoutMs: number;
  pollIntervalMs?: number;
  requestTimeoutMs?: number;
  signal?: AbortSignal;
  fetchImpl?: (url: string) => Promise<{ status: number }>;
  now?: () => number;
  delay?: (ms: number) => Promise<void>;
}): Promise<void> {
  const url = input.url.trim();
  if (!url) {
    throw new Error("workbench url is required");
  }
  const requestTimeoutMs = Math.max(1, input.requestTimeoutMs ?? 2500);
  const fetchImpl =
    input.fetchImpl ??
    ((target) =>
      fetch(target, {
        method: "GET",
        redirect: "manual",
        signal: input.signal
          ? AbortSignal.any([input.signal, AbortSignal.timeout(requestTimeoutMs)])
          : AbortSignal.timeout(requestTimeoutMs)
      }));
  const now = input.now ?? Date.now;
  const delay = input.delay ?? ((ms) => abortableDelay(ms, input.signal));
  const pollIntervalMs = Math.max(0, input.pollIntervalMs ?? 400);
  const startedAt = now();
  let lastError = "";
  while (now() - startedAt < input.timeoutMs) {
    input.signal?.throwIfAborted();
    try {
      const response = await fetchImpl(url);
      input.signal?.throwIfAborted();
      if (response.status > 0 && response.status < 500) {
        return;
      }
      lastError = `HTTP ${response.status}`;
    } catch (error: unknown) {
      input.signal?.throwIfAborted();
      lastError = error instanceof Error ? error.message : String(error);
    }
    if (now() - startedAt >= input.timeoutMs) {
      break;
    }
    if (pollIntervalMs > 0) {
      await delay(pollIntervalMs);
      input.signal?.throwIfAborted();
    }
  }
  throw new Error(`workbench HTTP was not reachable at ${url}${lastError ? `: ${lastError}` : ""}`);
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
      reject(reason instanceof Error ? reason : new Error("workbench HTTP readiness aborted"));
    };
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}
