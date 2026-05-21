import { describe, expect, it } from "vitest";

import {
  DEFAULT_WORKBENCH_THEME,
  WORKBENCH_THEME_STORAGE_KEY,
  nextWorkbenchTheme,
  normalizeWorkbenchTheme,
  readStoredWorkbenchTheme,
  writeStoredWorkbenchTheme,
} from "./themePreference";

function memoryStorage(initial: Record<string, string | null> = {}) {
  const values = new Map(Object.entries(initial).filter((entry): entry is [string, string] => entry[1] !== null));
  return {
    getItem(key: string) {
      return values.get(key) ?? null;
    },
    setItem(key: string, value: string) {
      values.set(key, value);
    },
  };
}

describe("themePreference", () => {
  it("normalizes supported workbench themes", () => {
    expect(normalizeWorkbenchTheme("light")).toBe("light");
    expect(normalizeWorkbenchTheme(" DARK ")).toBe("dark");
    expect(normalizeWorkbenchTheme("system")).toBeNull();
  });

  it("defaults to dark when no stored theme exists", () => {
    expect(readStoredWorkbenchTheme(memoryStorage())).toBe(DEFAULT_WORKBENCH_THEME);
  });

  it("persists and reads the selected theme", () => {
    const storage = memoryStorage();

    writeStoredWorkbenchTheme("light", storage);

    expect(storage.getItem(WORKBENCH_THEME_STORAGE_KEY)).toBe("light");
    expect(readStoredWorkbenchTheme(storage)).toBe("light");
  });

  it("toggles between light and dark", () => {
    expect(nextWorkbenchTheme("dark")).toBe("light");
    expect(nextWorkbenchTheme("light")).toBe("dark");
  });
});
