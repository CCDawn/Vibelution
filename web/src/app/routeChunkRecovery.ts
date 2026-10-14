import { allowNextWorkbenchWindowUnload } from "./projectCloseGuard";

export const ROUTE_CHUNK_RELOAD_KEY = "vibelution:route-chunk-reload";
const ROUTE_CHUNK_RELOAD_RECORD_VERSION = 1;

type ChunkRecoveryWindow = Pick<Window, "location" | "sessionStorage" | "navigator">;
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

  // An offline chunk fetch is not proof of a stale build. Reloading now
  // replaces the editable document with a browser network error page.
  // Keep the one-shot reload allowance for a later online failure.
  if (browserWindow.navigator?.onLine === false) {
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
  // Avoid racing the workbench project-close beforeunload guard during recovery reloads.
  allowNextWorkbenchWindowUnload();
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

type ReloadGraceTimer = {
  setTimeout: (handler: () => void, timeoutMs: number) => unknown;
  clearTimeout: (handle: unknown) => void;
};

export type ReloadGraceOptions = {
  degradeMs?: number;
  onDegrade?: (error: unknown) => void;
  timer?: ReloadGraceTimer;
};

/** Default grace before a requested recovery reload is treated as vetoed. */
const ROUTE_CHUNK_RELOAD_GRACE_MS = 4_000;

export type ReloadGracePromise<T> = Promise<T> & { cancel: () => void };

function resolveReloadGraceTimer(timer?: ReloadGraceTimer): ReloadGraceTimer | undefined {
  if (timer) {
    return timer;
  }
  if (typeof globalThis.setTimeout !== "function" || typeof globalThis.clearTimeout !== "function") {
    return undefined;
  }
  return {
    setTimeout: (handler, timeoutMs) => globalThis.setTimeout(handler, timeoutMs),
    clearTimeout: (handle) => globalThis.clearTimeout(handle as ReturnType<typeof setTimeout>),
  };
}

/**
 * Keeps a lazy route suspension pending while its recovery reload can still
 * take effect, then degrades to the original chunk error so React Router's
 * errorElement can render actionable recovery instead of freezing the view
 * forever. Needed because the recovery reload can be silently vetoed by the
 * project-close beforeunload guard (one-shot unload pass expired / re-armed).
 *
 * `cancel()` clears the degrade timer for the successful-reload path and test
 * teardown; a cancelled grace stays pending, which is correct once the
 * document is already unloading. `onDegrade` fires at most once, before the
 * rejection, and never masks the original error if telemetry throws.
 */
export function createReloadGracePromise<T>(
  error: unknown,
  options: ReloadGraceOptions = {},
): ReloadGracePromise<T> {
  const degradeMs = options.degradeMs ?? ROUTE_CHUNK_RELOAD_GRACE_MS;
  const timer = resolveReloadGraceTimer(options.timer);
  let degradeHandle: unknown;
  let settled = false;

  const grace = new Promise<T>((_resolve, reject) => {
    if (!timer) {
      // No scheduler (constrained runtime): keep suspending rather than drop
      // a reload that may still be in flight with no degrade point left.
      return;
    }
    degradeHandle = timer.setTimeout(() => {
      if (settled) {
        return;
      }
      settled = true;
      if (options.onDegrade) {
        try {
          options.onDegrade(error);
        } catch {
          // Telemetry must never replace the original chunk error.
        }
      }
      reject(error);
    }, degradeMs);
  }) as ReloadGracePromise<T>;

  grace.cancel = () => {
    if (settled) {
      return;
    }
    settled = true;
    if (timer) {
      timer.clearTimeout(degradeHandle);
    }
  };

  return grace;
}
