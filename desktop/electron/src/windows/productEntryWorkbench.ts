export const PRODUCT_ENTRY_HTTP_PROBE_MS = 1500;

export async function startOrFocusWorkbenchFromProductEntry(input: {
  url: string;
  waitForHttp: (opts: {
    url: string;
    timeoutMs: number;
    requestTimeoutMs?: number;
    pollIntervalMs?: number;
  }) => Promise<void>;
  openOrFocus: (url: string) => Promise<unknown>;
  startLifecycle: () => Promise<unknown>;
  probeTimeoutMs?: number;
  resolveReadyUrl?: () => Promise<string>;
  readyTimeoutMs?: number;
}): Promise<"focused" | "started"> {
  const url = input.url.trim();
  const probeTimeoutMs = Math.max(1, input.probeTimeoutMs ?? PRODUCT_ENTRY_HTTP_PROBE_MS);
  try {
    await input.waitForHttp({
      url,
      timeoutMs: probeTimeoutMs,
      requestTimeoutMs: Math.min(800, probeTimeoutMs),
      pollIntervalMs: 200
    });
    await input.openOrFocus(url);
    return "focused";
  } catch {
    await input.startLifecycle();
    const readyUrl = String((await input.resolveReadyUrl?.()) || url).trim() || url;
    await input.waitForHttp({
      url: readyUrl,
      timeoutMs: Math.max(1, input.readyTimeoutMs ?? 90_000),
      pollIntervalMs: 400
    });
    await input.openOrFocus(readyUrl);
    return "started";
  }
}
