// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from "vitest";
import { requestWorkbenchTheme, subscribeStoredWorkbenchTheme, WORKBENCH_THEME_STORAGE_KEY, writeStoredWorkbenchTheme } from "./themePreference";

afterEach(() => { localStorage.clear(); vi.unstubAllGlobals(); vi.useRealTimers(); });

describe("shared workbench appearance preferences", () => {
  it("updates same-window settings and shell subscribers, then unsubscribes", () => {
    const listener = vi.fn();
    const stop = subscribeStoredWorkbenchTheme(listener);
    writeStoredWorkbenchTheme("dark");
    expect(listener).toHaveBeenCalledWith("dark");
    expect(localStorage.getItem(WORKBENCH_THEME_STORAGE_KEY)).toBe("dark");
    stop();
    writeStoredWorkbenchTheme("light");
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("reads cross-window theme changes and ignores unrelated storage", () => {
    const listener = vi.fn();
    const stop = subscribeStoredWorkbenchTheme(listener);
    localStorage.setItem(WORKBENCH_THEME_STORAGE_KEY, "dark");
    window.dispatchEvent(new StorageEvent("storage", { key: "unrelated" }));
    expect(listener).not.toHaveBeenCalled();
    window.dispatchEvent(new StorageEvent("storage", { key: WORKBENCH_THEME_STORAGE_KEY, newValue: "dark" }));
    expect(listener).toHaveBeenCalledWith("dark");
    stop();
  });

  it("projects confirmed authority revisions and rejects stale or locally divergent updates", async () => {
    let incoming: ((value: unknown) => void) | undefined;
    const unsubscribe = vi.fn();
    const initial = { epoch: "test", revision: 0, theme: "light" as const, writeId: "a".repeat(32) };
    const next = { ...initial, revision: 1, theme: "dark" as const };
    const commit = vi.fn(async () => ({ code: "applied", snapshot: next }));
    vi.stubGlobal("vibelutionLauncher", { readThemeAuthority: async () => ({ code: "read", snapshot: initial }), setThemeAuthority: commit,
      onAssistantThemeChanged: (handler: (value: unknown) => void) => { incoming = handler; return unsubscribe; } });
    const listener = vi.fn();
    const stop = subscribeStoredWorkbenchTheme(listener);
    await vi.waitFor(() => expect(localStorage.getItem(WORKBENCH_THEME_STORAGE_KEY)).toBe("light"));
    expect(await requestWorkbenchTheme("dark")).toBe("applied");
    expect(localStorage.getItem(WORKBENCH_THEME_STORAGE_KEY)).toBe("dark");
    expect(listener).toHaveBeenCalledWith("dark");
    incoming?.({ snapshot: initial, explicit: false });
    expect(localStorage.getItem(WORKBENCH_THEME_STORAGE_KEY)).toBe("dark");
    incoming?.({ snapshot: { ...initial, revision: 2 }, explicit: false });
    expect(localStorage.getItem(WORKBENCH_THEME_STORAGE_KEY)).toBe("light");
    localStorage.setItem(WORKBENCH_THEME_STORAGE_KEY, "dark");
    incoming?.({ snapshot: { ...initial, revision: 3 }, explicit: false });
    expect(localStorage.getItem(WORKBENCH_THEME_STORAGE_KEY)).toBe("dark");
    expect(commit).toHaveBeenCalledOnce();
    stop();
    expect(unsubscribe).toHaveBeenCalledOnce();
  });

  it("preserves conflicting legacy preferences until the user selects the global value", async () => {
    vi.resetModules();
    const preferences = await import("./themePreference");
    localStorage.setItem(WORKBENCH_THEME_STORAGE_KEY, "light");
    const statuses: string[] = [];
    const stopStatus = preferences.subscribeWorkbenchThemeSync(value => statuses.push(value));
    vi.stubGlobal("vibelutionLauncher", { readThemeAuthority: async () => ({ code: "read", snapshot: { epoch: "test-conflict", revision: 1, theme: "dark", writeId: "a".repeat(32) } }),
      onAssistantThemeChanged: () => () => undefined });
    const stop = preferences.subscribeStoredWorkbenchTheme(() => undefined);
    await vi.waitFor(() => expect(statuses).toContain("conflict"));
    expect(localStorage.getItem(WORKBENCH_THEME_STORAGE_KEY)).toBe("light");
    vi.stubGlobal("vibelutionLauncher", { readThemeAuthority: async () => ({ code: "read", snapshot: { epoch: "test-conflict", revision: 1, theme: "dark", writeId: "a".repeat(32) } }),
      setThemeAuthority: async () => ({ code: "applied", snapshot: { epoch: "test-conflict", revision: 2, theme: "dark", writeId: "b".repeat(32) } }) });
    expect(await preferences.useAuthorityTheme()).toBe("applied");
    expect(localStorage.getItem(WORKBENCH_THEME_STORAGE_KEY)).toBe("dark");
    stop(); stopStatus();
  });

  it("keeps an offline choice local and prevents an automatic overwrite on reconnect", async () => {
    vi.resetModules();
    const preferences = await import("./themePreference");
    vi.stubGlobal("vibelutionLauncher", { readThemeAuthority: async () => { throw new Error("offline"); }, setThemeAuthority: vi.fn() });
    expect(await preferences.requestWorkbenchTheme("dark")).toBe("local");
    expect(localStorage.getItem(WORKBENCH_THEME_STORAGE_KEY)).toBe("dark");
    const statuses: string[] = [];
    const stopStatus = preferences.subscribeWorkbenchThemeSync(value => statuses.push(value));
    vi.stubGlobal("vibelutionLauncher", { readThemeAuthority: async () => ({ code: "read", snapshot: { epoch: "global", revision: 1, theme: "light", writeId: "a".repeat(32) } }) });
    const stop = preferences.subscribeStoredWorkbenchTheme(() => undefined);
    await vi.waitFor(() => expect(statuses).toContain("local"));
    expect(localStorage.getItem(WORKBENCH_THEME_STORAGE_KEY)).toBe("dark");
    stop(); stopStatus();
  });

  it("never applies an older request's late failure over a newer choice", async () => {
    vi.resetModules();
    const preferences = await import("./themePreference");
    const initial = { epoch: "sequence", revision: 1, theme: "light" as const, writeId: "a".repeat(32) };
    let failOld!: (error: Error) => void;
    const set = vi.fn().mockImplementationOnce(() => new Promise((_resolve, reject) => { failOld = reject; }))
      .mockImplementationOnce(async () => ({ code: "applied", snapshot: { ...initial, revision: 2, theme: "dark", writeId: "b".repeat(32) } }));
    vi.stubGlobal("vibelutionLauncher", { readThemeAuthority: async () => ({ code: "read", snapshot: initial }), setThemeAuthority: set });
    const old = preferences.requestWorkbenchTheme("light");
    await vi.waitFor(() => expect(set).toHaveBeenCalledTimes(1));
    const next = preferences.requestWorkbenchTheme("dark");
    expect(await next).toBe("applied");
    failOld(new Error("late failure"));
    expect(await old).toBe("superseded");
    expect(localStorage.getItem(WORKBENCH_THEME_STORAGE_KEY)).toBe("dark");
  });

  it("bounds an unresponsive write and readback without retrying or applying its late reply", async () => {
    vi.resetModules();
    const preferences = await import("./themePreference");
    vi.useFakeTimers();
    const initial = { epoch: "timeout", revision: 1, theme: "light" as const, writeId: "a".repeat(32) };
    let resolveOld!: (value: unknown) => void;
    const read = vi.fn().mockResolvedValueOnce({ code: "read", snapshot: initial })
      .mockImplementationOnce(() => new Promise(() => undefined));
    const set = vi.fn().mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }))
      .mockImplementationOnce(async () => ({ code: "applied", snapshot: { ...initial, revision: 3, theme: "light", writeId: "c".repeat(32) } }));
    vi.stubGlobal("vibelutionLauncher", { readThemeAuthority: read, setThemeAuthority: set });
    const old = preferences.requestWorkbenchTheme("dark");
    await vi.advanceTimersByTimeAsync(3000);
    expect(set).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(3000);
    expect(await old).toBe("unknown");
    expect(read).toHaveBeenCalledTimes(2);
    expect(localStorage.getItem(WORKBENCH_THEME_STORAGE_KEY)).toBe("dark");
    expect(await preferences.requestWorkbenchTheme("light")).toBe("applied");
    resolveOld({ code: "applied", snapshot: { ...initial, revision: 2, theme: "dark", writeId: "b".repeat(32) } });
    await Promise.resolve();
    expect(set).toHaveBeenCalledTimes(2);
    expect(localStorage.getItem(WORKBENCH_THEME_STORAGE_KEY)).toBe("light");
  });

  it("accepts an explicit same-side projection but protects a newer unsynced local choice", async () => {
    vi.resetModules();
    const preferences = await import("./themePreference");
    const initial = { epoch: "explicit", revision: 1, theme: "dark" as const, writeId: "a".repeat(32) };
    let incoming!: (value: unknown) => void;
    localStorage.setItem(WORKBENCH_THEME_STORAGE_KEY, "light");
    vi.stubGlobal("vibelutionLauncher", { readThemeAuthority: async () => ({ code: "read", snapshot: initial }),
      onAssistantThemeChanged: (handler: (value: unknown) => void) => { incoming = handler; return () => undefined; } });
    const status = vi.fn();
    const stopStatus = preferences.subscribeWorkbenchThemeSync(status);
    const stop = preferences.subscribeStoredWorkbenchTheme(() => undefined);
    await vi.waitFor(() => expect(status).toHaveBeenCalledWith("conflict"));
    incoming({ snapshot: { ...initial, revision: 2 }, explicit: true });
    expect(localStorage.getItem(WORKBENCH_THEME_STORAGE_KEY)).toBe("dark");
    vi.stubGlobal("vibelutionLauncher", { readThemeAuthority: async () => { throw Error("offline"); }, setThemeAuthority: vi.fn().mockRejectedValue(Error("offline")) });
    expect(await preferences.requestWorkbenchTheme("light")).toBe("unknown");
    incoming({ snapshot: { ...initial, revision: 3 }, explicit: true });
    expect(localStorage.getItem(WORKBENCH_THEME_STORAGE_KEY)).toBe("light");
    stop(); stopStatus();
  });
});
