const ROUTE_CHUNK_RELOAD_KEY = "vibelution:route-chunk-reload";

type ChunkRecoveryWindow = Pick<Window, "location" | "sessionStorage">;

export function isDynamicImportFetchError(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error ?? "");
  return /Failed to fetch dynamically imported module|Importing a module script failed|error loading dynamically imported module|Loading chunk .+ failed/i.test(message);
}

export function isLocalBuiltAssetResourceError(resourceUrl: string, browserWindow: ChunkRecoveryWindow | undefined = globalThis.window): boolean {
  const rawUrl = resourceUrl.trim();
  if (!rawUrl || !browserWindow) {
    return false;
  }

  try {
    const url = new URL(rawUrl, browserWindow.location.href);
    if (url.origin !== browserWindow.location.origin) {
      return false;
    }
    return /^\/assets\/.+\.(?:js|css)(?:$|\?)/i.test(`${url.pathname}${url.search}`);
  } catch {
    return false;
  }
}

export function recoverFromStaleRouteAsset(browserWindow: ChunkRecoveryWindow | undefined = globalThis.window): boolean {
  if (!browserWindow) {
    return false;
  }

  const target = `${browserWindow.location.pathname}${browserWindow.location.search}${browserWindow.location.hash}`;
  try {
    if (browserWindow.sessionStorage.getItem(ROUTE_CHUNK_RELOAD_KEY) === target) {
      return false;
    }
    browserWindow.sessionStorage.setItem(ROUTE_CHUNK_RELOAD_KEY, target);
  } catch {
    // Storage can be unavailable in constrained browser profiles; a single reload is still the safest recovery.
  }
  browserWindow.location.reload();
  return true;
}

export function recoverFromDynamicImportFetchError(error: unknown, browserWindow: ChunkRecoveryWindow | undefined = globalThis.window): boolean {
  if (!isDynamicImportFetchError(error)) {
    return false;
  }
  return recoverFromStaleRouteAsset(browserWindow);
}

export function recoverFromBuiltAssetResourceError(resourceUrl: string, browserWindow: ChunkRecoveryWindow | undefined = globalThis.window): boolean {
  if (!isLocalBuiltAssetResourceError(resourceUrl, browserWindow)) {
    return false;
  }
  return recoverFromStaleRouteAsset(browserWindow);
}
