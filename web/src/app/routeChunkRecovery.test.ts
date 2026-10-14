import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createReloadGracePromise,
  isDynamicImportFetchError,
  isLocalBuiltAssetResourceError,
  recoverFromBuiltAssetResourceError,
  recoverFromDynamicImportFetchError,
  ROUTE_CHUNK_RELOAD_KEY,
} from "./routeChunkRecovery";

function fakeWindow(pathname = "/teams") {
  const storage = new Map<string, string>();
  return {
    location: {
      pathname,
      search: "?team=research-core",
      hash: "",
      href: `http://127.0.0.1:8787${pathname}?team=research-core`,
      origin: "http://127.0.0.1:8787",
      reload: vi.fn(),
    },
    sessionStorage: {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => storage.set(key, value),
    },
  } as unknown as Window;
}

describe("route chunk recovery", () => {
  it("keeps the current document while offline and allows recovery after reconnect", () => {
    const win = fakeWindow("/chat");
    Object.defineProperty(win, "navigator", { value: { onLine: false }, configurable: true });
    const error = new TypeError("Failed to fetch dynamically imported module: http://127.0.0.1:8787/assets/ConversationMarkdownRenderer.js");
    expect(recoverFromDynamicImportFetchError(error, win)).toBe(false);
    expect(recoverFromBuiltAssetResourceError("/assets/ConversationMarkdownRenderer.js", win)).toBe(false);
    expect(win.location.reload).not.toHaveBeenCalled();
    expect(win.sessionStorage.getItem(ROUTE_CHUNK_RELOAD_KEY)).toBeNull();
    Object.defineProperty(win, "navigator", { value: { onLine: true } });
    expect(recoverFromDynamicImportFetchError(error, win)).toBe(true);
    expect(win.location.reload).toHaveBeenCalledTimes(1);
  });

  it("recognizes stale dynamic import fetch failures", () => {
    expect(isDynamicImportFetchError(new TypeError("Failed to fetch dynamically imported module: http://127.0.0.1:8000/assets/TeamsRoute-old.js"))).toBe(true);
    expect(isDynamicImportFetchError(new Error("Loading chunk TeamsRoute failed."))).toBe(true);
    expect(isDynamicImportFetchError(new Error("ordinary render error"))).toBe(false);
  });

  it("reloads once for a stale chunk on the current route", () => {
    const win = fakeWindow();
    const error = new TypeError("Failed to fetch dynamically imported module: http://127.0.0.1:8000/assets/TeamsRoute-old.js");
    const reports: Array<{ eventCode: string; fields?: Record<string, unknown> }> = [];

    expect(recoverFromDynamicImportFetchError(error, win, (event) => reports.push(event))).toBe(true);
    expect(win.location.reload).toHaveBeenCalledTimes(1);
    expect(reports[0].eventCode).toBe("browser.route_chunk_recovery.reload_requested");
    expect(reports[0].fields?.reason).toBe("dynamic_import_fetch_error");
    expect(reports[0].fields?.reloadRequested).toBe(true);

    expect(recoverFromDynamicImportFetchError(error, win, (event) => reports.push(event))).toBe(false);
    expect(win.location.reload).toHaveBeenCalledTimes(1);
    expect(reports[1].eventCode).toBe("browser.route_chunk_recovery.reload_skipped");
    expect(reports[1].fields?.duplicateRoute).toBe(true);
  });

  it("does not let legacy route-only reload markers permanently suppress recovery", () => {
    const win = fakeWindow();
    const error = new TypeError("Failed to fetch dynamically imported module: http://127.0.0.1:8000/assets/EvolutionRoute-old.js");

    win.sessionStorage.setItem(ROUTE_CHUNK_RELOAD_KEY, "/teams?team=research-core");

    expect(recoverFromDynamicImportFetchError(error, win)).toBe(true);
    expect(win.location.reload).toHaveBeenCalledTimes(1);
  });

  it("stores the stale chunk guard by build and target instead of a bare route string", () => {
    const win = fakeWindow();
    const error = new TypeError("Failed to fetch dynamically imported module: http://127.0.0.1:8000/assets/EvolutionRoute-old.js");

    expect(recoverFromDynamicImportFetchError(error, win)).toBe(true);

    const stored = JSON.parse(win.sessionStorage.getItem(ROUTE_CHUNK_RELOAD_KEY) || "{}");
    expect(stored.schemaVersion).toBe(1);
    expect(stored.target).toBe("/teams?team=research-core");
    expect(stored.buildId).toBeTypeOf("string");
    expect(stored.buildId.length).toBeGreaterThan(0);
  });

  it("recognizes local built asset resource failures", () => {
    const win = fakeWindow();

    expect(isLocalBuiltAssetResourceError("http://127.0.0.1:8787/assets/ConfigRoute-CeO6d7JC.js", win)).toBe(true);
    expect(isLocalBuiltAssetResourceError("/assets/index-Bz123.css", win)).toBe(true);
    expect(isLocalBuiltAssetResourceError("http://example.test/assets/ConfigRoute-CeO6d7JC.js", win)).toBe(false);
    expect(isLocalBuiltAssetResourceError("/favicon.ico", win)).toBe(false);
  });

  it("reloads once for stale local built asset resource failures", () => {
    const win = fakeWindow("/config");
    const reports: Array<{ eventCode: string; fields?: Record<string, unknown> }> = [];

    expect(recoverFromBuiltAssetResourceError("/assets/ConfigRoute-CeO6d7JC.js", win, (event) => reports.push(event))).toBe(true);
    expect(win.location.reload).toHaveBeenCalledTimes(1);
    expect(reports[0].eventCode).toBe("browser.route_chunk_recovery.reload_requested");
    expect(reports[0].fields?.reason).toBe("built_asset_resource_error");
    expect(reports[0].fields?.resourceUrl).toBe("/assets/ConfigRoute-CeO6d7JC.js");

    expect(recoverFromBuiltAssetResourceError("/assets/ConfigRoute-CeO6d7JC.js", win, (event) => reports.push(event))).toBe(false);
    expect(win.location.reload).toHaveBeenCalledTimes(1);
    expect(reports[1].eventCode).toBe("browser.route_chunk_recovery.reload_skipped");
  });
});

function trackPromise<T>(promise: Promise<T>) {
  const state = {
    status: "pending" as "pending" | "fulfilled" | "rejected",
    reason: undefined as unknown,
  };
  promise.then(
    () => {
      state.status = "fulfilled";
    },
    (error) => {
      state.status = "rejected";
      state.reason = error;
    },
  );
  return state;
}

describe("reload grace promise", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("stays pending while the recovery reload can still take effect", async () => {
    vi.useFakeTimers();
    const error = new TypeError("Failed to fetch dynamically imported module: http://127.0.0.1:8000/assets/TeamsRoute-old.js");
    const onDegrade = vi.fn();
    const grace = createReloadGracePromise<{ default: unknown }>(error, { degradeMs: 4000, onDegrade });
    const tracked = trackPromise(grace);

    await vi.advanceTimersByTimeAsync(3999);

    expect(tracked.status).toBe("pending");
    expect(onDegrade).not.toHaveBeenCalled();
    // Test teardown: clear the pending degrade timer.
    grace.cancel();
  });

  it("rejects with the original error and fires onDegrade exactly once after the default grace", async () => {
    vi.useFakeTimers();
    const error = new TypeError("Failed to fetch dynamically imported module: http://127.0.0.1:8000/assets/TeamsRoute-old.js");
    const onDegrade = vi.fn();
    const grace = createReloadGracePromise<{ default: unknown }>(error, { onDegrade });
    const tracked = trackPromise(grace);

    await vi.advanceTimersByTimeAsync(3999);
    expect(tracked.status).toBe("pending");
    await vi.advanceTimersByTimeAsync(1);

    expect(tracked.status).toBe("rejected");
    expect(tracked.reason).toBe(error);
    expect(onDegrade).toHaveBeenCalledTimes(1);
    expect(onDegrade).toHaveBeenCalledWith(error);

    // No double-settle: extra ticks (or a late cancel) never re-fire the degrade.
    grace.cancel();
    await vi.advanceTimersByTimeAsync(10_000);
    expect(onDegrade).toHaveBeenCalledTimes(1);
    expect(tracked.status).toBe("rejected");
    expect(tracked.reason).toBe(error);
  });

  it("clears the degrade timer on cancel so a successful reload path stays silent", async () => {
    vi.useFakeTimers();
    const error = new TypeError("Failed to fetch dynamically imported module: http://127.0.0.1:8000/assets/TeamsRoute-old.js");
    const onDegrade = vi.fn();
    const grace = createReloadGracePromise<{ default: unknown }>(error, { degradeMs: 400, onDegrade });
    const tracked = trackPromise(grace);

    grace.cancel();
    await vi.runAllTimersAsync();

    expect(tracked.status).toBe("pending");
    expect(onDegrade).not.toHaveBeenCalled();
  });

  it("keeps a throwing onDegrade hook from masking the original chunk error", async () => {
    vi.useFakeTimers();
    const error = new TypeError("Failed to fetch dynamically imported module: http://127.0.0.1:8000/assets/TeamsRoute-old.js");
    const grace = createReloadGracePromise<{ default: unknown }>(error, {
      degradeMs: 100,
      onDegrade: () => {
        throw new Error("telemetry sink down");
      },
    });
    const tracked = trackPromise(grace);

    await vi.advanceTimersByTimeAsync(100);

    expect(tracked.status).toBe("rejected");
    expect(tracked.reason).toBe(error);
  });

  it("supports an injectable timer and guards settle races through cancel", () => {
    const scheduled: Array<{ handler: () => void; timeoutMs: number }> = [];
    let clearedCount = 0;
    const error = new TypeError("Failed to fetch dynamically imported module: http://127.0.0.1:8000/assets/TeamsRoute-old.js");
    const onDegrade = vi.fn();
    const grace = createReloadGracePromise<{ default: unknown }>(error, {
      degradeMs: 250,
      onDegrade,
      timer: {
        setTimeout: (handler, timeoutMs) => {
          scheduled.push({ handler, timeoutMs });
          return scheduled.length;
        },
        clearTimeout: () => {
          clearedCount += 1;
        },
      },
    });
    const tracked = trackPromise(grace);

    expect(scheduled).toEqual([{ handler: expect.any(Function), timeoutMs: 250 }]);
    expect(clearedCount).toBe(0);

    grace.cancel();
    expect(clearedCount).toBe(1);

    // A late timer callback (double-fire) must not degrade a cancelled grace.
    scheduled[0]?.handler();
    expect(tracked.status).toBe("pending");
    expect(onDegrade).not.toHaveBeenCalled();
  });
});
