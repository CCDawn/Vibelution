// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from "vitest";
import { subscribeStoredWorkbenchTheme, WORKBENCH_THEME_STORAGE_KEY, writeStoredWorkbenchTheme } from "./themePreference";

afterEach(() => localStorage.clear());

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
});
