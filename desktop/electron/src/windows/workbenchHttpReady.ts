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
        signal: AbortSignal.timeout(requestTimeoutMs)
      }));
  const now = input.now ?? Date.now;
  const delay = input.delay ?? ((ms) => new Promise((resolve) => setTimeout(resolve, ms)));
  const pollIntervalMs = Math.max(0, input.pollIntervalMs ?? 400);
  const startedAt = now();
  let lastError = "";
  while (now() - startedAt < input.timeoutMs) {
    try {
      const response = await fetchImpl(url);
      if (response.status > 0 && response.status < 500) {
        return;
      }
      lastError = `HTTP ${response.status}`;
    } catch (error: unknown) {
      lastError = error instanceof Error ? error.message : String(error);
    }
    if (now() - startedAt >= input.timeoutMs) {
      break;
    }
    if (pollIntervalMs > 0) {
      await delay(pollIntervalMs);
    }
  }
  throw new Error(`workbench HTTP was not reachable at ${url}${lastError ? `: ${lastError}` : ""}`);
}
