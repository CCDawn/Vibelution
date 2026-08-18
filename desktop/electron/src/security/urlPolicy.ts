const LOOPBACK_HOSTS = new Set(["127.0.0.1", "localhost"]);

function isLoopbackHttpUrl(url: URL): boolean {
  return url.protocol === "http:" && LOOPBACK_HOSTS.has(url.hostname);
}

export function assertLocalHttpUrl(rawUrl: string, expectedOrigin: string): string {
  const url = new URL(rawUrl);
  if (!isLoopbackHttpUrl(url)) {
    throw new Error(`blocked non-local URL: ${rawUrl}`);
  }
  if (url.origin !== expectedOrigin) {
    throw new Error(`blocked unexpected origin: ${url.origin}`);
  }
  return url.toString();
}

export function isLiveWorkbenchWindowUrl(windowUrl: string, expectedOrigin: string): boolean {
  try {
    const url = new URL(windowUrl);
    if (!isLoopbackHttpUrl(url) || !url.href.trim() || url.pathname === "/favicon.ico") {
      return false;
    }
    const expected = new URL(expectedOrigin);
    if (!isLoopbackHttpUrl(expected)) {
      return url.origin === expected.origin;
    }
    if (url.port === "5173" && expected.port !== "5173") {
      return false;
    }
    return true;
  } catch {
    return false;
  }
}
