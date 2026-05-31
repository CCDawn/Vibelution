import { describe, expect, it, vi } from "vitest";

import {
  isDynamicImportFetchError,
  isLocalBuiltAssetResourceError,
  recoverFromBuiltAssetResourceError,
  recoverFromDynamicImportFetchError,
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
  it("recognizes stale dynamic import fetch failures", () => {
    expect(isDynamicImportFetchError(new TypeError("Failed to fetch dynamically imported module: http://127.0.0.1:8000/assets/TeamsRoute-old.js"))).toBe(true);
    expect(isDynamicImportFetchError(new Error("Loading chunk TeamsRoute failed."))).toBe(true);
    expect(isDynamicImportFetchError(new Error("ordinary render error"))).toBe(false);
  });

  it("reloads once for a stale chunk on the current route", () => {
    const win = fakeWindow();
    const error = new TypeError("Failed to fetch dynamically imported module: http://127.0.0.1:8000/assets/TeamsRoute-old.js");

    expect(recoverFromDynamicImportFetchError(error, win)).toBe(true);
    expect(win.location.reload).toHaveBeenCalledTimes(1);
    expect(recoverFromDynamicImportFetchError(error, win)).toBe(false);
    expect(win.location.reload).toHaveBeenCalledTimes(1);
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

    expect(recoverFromBuiltAssetResourceError("/assets/ConfigRoute-CeO6d7JC.js", win)).toBe(true);
    expect(win.location.reload).toHaveBeenCalledTimes(1);
    expect(recoverFromBuiltAssetResourceError("/assets/ConfigRoute-CeO6d7JC.js", win)).toBe(false);
    expect(win.location.reload).toHaveBeenCalledTimes(1);
  });
});
