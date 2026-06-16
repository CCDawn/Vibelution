export const ROUTE_CHUNK_RELOAD_KEY = "vibelution:route-chunk-reload";
const ROUTE_CHUNK_RELOAD_RECORD_VERSION = 1;

type ChunkRecoveryWindow = Pick<Window, "location" | "sessionStorage">;
type ChunkRecoveryReporter = (event: {
  phase: string;
  eventCode: string;
  message: string;
  level?: "info" | "warning" | "error";
  fields?: Record<string, unknown>;
}) => void;

type ChunkRecoveryDetails = {
  reporter?: ChunkRecoveryReporter;
  reason?: "dynamic_import_fetch_error" | "built_asset_resource_error";
  resourceUrl?: string;
  errorMessage?: string;
};

type RouteChunkReloadRecord = {
  schemaVersion: typeof ROUTE_CHUNK_RELOAD_RECORD_VERSION;
  buildId: string;
  target: string;
};

function compactTelemetryText(value: string | undefined, limit = 300) {
  const text = String(value ?? "").replace(/\s+/g, " ").trim();
  if (text.length <= limit) {
    return text;
  }
  return `${text.slice(0, Math.max(0, limit - 3))}...`;
}

function currentBuildId() {
  try {
    return __VIBELUTION_BUILD_ID__ || "unknown";
  } catch {
    return "unknown";
  }
}

function parseReloadRecord(rawValue: string | null): RouteChunkReloadRecord | null {
  if (!rawValue) {
    return null;
  }
  try {
    const parsed = JSON.parse(rawValue) as Partial<RouteChunkReloadRecord>;
    if (
      parsed &&
      parsed.schemaVersion === ROUTE_CHUNK_RELOAD_RECORD_VERSION &&
      typeof parsed.buildId === "string" &&
      typeof parsed.target === "string"
    ) {
      return parsed as RouteChunkReloadRecord;
    }
  } catch {
    // Ignore legacy plain route markers so an upgraded client gets one fresh recovery attempt.
  }
  return null;
}

function stringifyReloadRecord(record: RouteChunkReloadRecord) {
  return JSON.stringify(record);
}

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

function reportRouteChunkRecovery(
  details: ChunkRecoveryDetails,
  browserWindow: ChunkRecoveryWindow,
  options: {
    routeTarget: string;
    reloadRequested: boolean;
    duplicateRoute: boolean;
  },
) {
  if (!details.reporter) {
    return;
  }
  const { routeTarget, reloadRequested, duplicateRoute } = options;
  details.reporter({
    phase: "recovery",
    eventCode: reloadRequested
      ? "browser.route_chunk_recovery.reload_requested"
      : "browser.route_chunk_recovery.reload_skipped",
    message: reloadRequested
      ? "Stale route chunk detected; requesting a page reload."
      : "Stale route chunk detected; reload was already requested for this route.",
    level: reloadRequested ? "warning" : "info",
    fields: {
      reason: details.reason || "",
      routeTarget,
      buildId: currentBuildId(),
      pathname: browserWindow.location.pathname,
      resourceUrl: compactTelemetryText(details.resourceUrl, 500),
      errorMessage: compactTelemetryText(details.errorMessage, 500),
      reloadRequested,
      duplicateRoute,
    },
  });
}

export function recoverFromStaleRouteAsset(
  browserWindow: ChunkRecoveryWindow | undefined = globalThis.window,
  details: ChunkRecoveryDetails = {},
): boolean {
  if (!browserWindow) {
    return false;
  }

  const target = `${browserWindow.location.pathname}${browserWindow.location.search}${browserWindow.location.hash}`;
  const buildId = currentBuildId();
  try {
    const existingRecord = parseReloadRecord(browserWindow.sessionStorage.getItem(ROUTE_CHUNK_RELOAD_KEY));
    if (existingRecord?.target === target && existingRecord.buildId === buildId) {
      reportRouteChunkRecovery(details, browserWindow, {
        routeTarget: target,
        reloadRequested: false,
        duplicateRoute: true,
      });
      return false;
    }
    browserWindow.sessionStorage.setItem(
      ROUTE_CHUNK_RELOAD_KEY,
      stringifyReloadRecord({
        schemaVersion: ROUTE_CHUNK_RELOAD_RECORD_VERSION,
        buildId,
        target,
      }),
    );
  } catch {
    // Storage can be unavailable in constrained browser profiles; a single reload is still the safest recovery.
  }
  reportRouteChunkRecovery(details, browserWindow, {
    routeTarget: target,
    reloadRequested: true,
    duplicateRoute: false,
  });
  browserWindow.location.reload();
  return true;
}

export function recoverFromDynamicImportFetchError(
  error: unknown,
  browserWindow: ChunkRecoveryWindow | undefined = globalThis.window,
  reporter?: ChunkRecoveryReporter,
): boolean {
  if (!isDynamicImportFetchError(error)) {
    return false;
  }
  return recoverFromStaleRouteAsset(browserWindow, {
    reporter,
    reason: "dynamic_import_fetch_error",
    errorMessage: error instanceof Error ? error.message : String(error ?? ""),
  });
}

export function recoverFromBuiltAssetResourceError(
  resourceUrl: string,
  browserWindow: ChunkRecoveryWindow | undefined = globalThis.window,
  reporter?: ChunkRecoveryReporter,
): boolean {
  if (!isLocalBuiltAssetResourceError(resourceUrl, browserWindow)) {
    return false;
  }
  return recoverFromStaleRouteAsset(browserWindow, {
    reporter,
    reason: "built_asset_resource_error",
    resourceUrl,
  });
}
