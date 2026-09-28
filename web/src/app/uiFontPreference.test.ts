// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  DEFAULT_UI_FONT_BASE_PX,
  MAX_UI_FONT_BASE_PX,
  MIN_UI_FONT_BASE_PX,
  UI_FONT_BASE_CSS_PROPERTY,
  UI_FONT_BASE_STORAGE_KEY,
  applyUiFontBasePx,
  clampUiFontBasePx,
  normalizeUiFontBasePx,
  readStoredUiFontBasePx,
  subscribeStoredUiFontBasePx,
  writeStoredUiFontBasePx,
} from "./uiFontPreference";

function memoryStorage(initial: Record<string, string> = {}): Storage {
  const map = new Map(Object.entries(initial));
  return {
    get length() {
      return map.size;
    },
    clear: () => map.clear(),
    getItem: (key: string) => (map.has(key) ? (map.get(key) as string) : null),
    key: (index: number) => [...map.keys()][index] ?? null,
    removeItem: (key: string) => {
      map.delete(key);
    },
    setItem: (key: string, value: string) => {
      map.set(key, String(value));
    },
  } as Storage;
}

afterEach(() => {
  window.localStorage.removeItem(UI_FONT_BASE_STORAGE_KEY);
});

describe("normalizeUiFontBasePx", () => {
  it("keeps in-range integers", () => {
    expect(normalizeUiFontBasePx(MIN_UI_FONT_BASE_PX)).toBe(14);
    expect(normalizeUiFontBasePx(DEFAULT_UI_FONT_BASE_PX)).toBe(16);
    expect(normalizeUiFontBasePx(MAX_UI_FONT_BASE_PX)).toBe(18);
  });

  it("falls back to the default for invalid or out-of-range values", () => {
    expect(normalizeUiFontBasePx(MIN_UI_FONT_BASE_PX - 1)).toBe(16);
    expect(normalizeUiFontBasePx(MAX_UI_FONT_BASE_PX + 1)).toBe(16);
    expect(normalizeUiFontBasePx(16.5)).toBe(16);
    expect(normalizeUiFontBasePx("abc")).toBe(16);
    expect(normalizeUiFontBasePx("")).toBe(16);
    expect(normalizeUiFontBasePx(null)).toBe(16);
    expect(normalizeUiFontBasePx(undefined)).toBe(16);
    expect(normalizeUiFontBasePx({})).toBe(16);
    expect(normalizeUiFontBasePx(Number.NaN)).toBe(16);
  });

  it("accepts numeric strings", () => {
    expect(normalizeUiFontBasePx("15")).toBe(15);
    expect(normalizeUiFontBasePx(" 17 ")).toBe(17);
    expect(normalizeUiFontBasePx("13")).toBe(16);
  });
});

describe("clampUiFontBasePx", () => {
  it("clamps into the 14–18 window and rounds", () => {
    expect(clampUiFontBasePx(10)).toBe(14);
    expect(clampUiFontBasePx(99)).toBe(18);
    expect(clampUiFontBasePx(15.6)).toBe(16);
    expect(clampUiFontBasePx(Number.NaN)).toBe(16);
  });
});

describe("readStoredUiFontBasePx", () => {
  it("returns the default when the key is missing or storage is unavailable", () => {
    expect(readStoredUiFontBasePx(memoryStorage())).toBe(16);
    expect(readStoredUiFontBasePx(null)).toBe(16);
  });

  it("normalizes stored garbage back to the default", () => {
    expect(readStoredUiFontBasePx(memoryStorage({ [UI_FONT_BASE_STORAGE_KEY]: "18" }))).toBe(18);
    expect(readStoredUiFontBasePx(memoryStorage({ [UI_FONT_BASE_STORAGE_KEY]: "22" }))).toBe(16);
    expect(readStoredUiFontBasePx(memoryStorage({ [UI_FONT_BASE_STORAGE_KEY]: "eighteen" }))).toBe(16);
  });

  it("survives a throwing storage", () => {
    const throwing = {
      getItem: () => {
        throw new Error("denied");
      },
    } as unknown as Storage;
    expect(readStoredUiFontBasePx(throwing)).toBe(16);
  });
});

describe("writeStoredUiFontBasePx", () => {
  it("persists the normalized value as a plain number string", () => {
    const storage = memoryStorage();
    expect(writeStoredUiFontBasePx(18, storage)).toBe(18);
    expect(storage.getItem(UI_FONT_BASE_STORAGE_KEY)).toBe("18");
  });

  it("removes the key when writing the default (absent = default)", () => {
    const storage = memoryStorage({ [UI_FONT_BASE_STORAGE_KEY]: "18" });
    writeStoredUiFontBasePx(16, storage);
    expect(storage.getItem(UI_FONT_BASE_STORAGE_KEY)).toBeNull();
  });

  it("skips the write and notification when the value is unchanged", () => {
    const storage = memoryStorage({ [UI_FONT_BASE_STORAGE_KEY]: "18" });
    const listener = vi.fn();
    const unsubscribe = subscribeStoredUiFontBasePx(listener);
    try {
      writeStoredUiFontBasePx(18, storage);
      expect(listener).not.toHaveBeenCalled();
      expect(storage.getItem(UI_FONT_BASE_STORAGE_KEY)).toBe("18");
    } finally {
      unsubscribe();
    }
  });

  it("notifies subscribers with the new value", () => {
    const storage = memoryStorage();
    const listener = vi.fn();
    const unsubscribe = subscribeStoredUiFontBasePx(listener);
    try {
      writeStoredUiFontBasePx(14, storage);
      expect(listener).toHaveBeenCalledWith(14);
    } finally {
      unsubscribe();
    }
  });
});

describe("applyUiFontBasePx", () => {
  it("sets only the --vui-font-base custom property, never the root font-size", () => {
    document.documentElement.style.fontSize = "16px";
    document.documentElement.style.setProperty("--vui-window-width", "100svw");
    try {
      applyUiFontBasePx(document, 18);
      expect(document.documentElement.style.getPropertyValue(UI_FONT_BASE_CSS_PROPERTY)).toBe("18px");
      expect(document.documentElement.style.fontSize).toBe("16px");
      expect(document.documentElement.style.getPropertyValue("--vui-window-width")).toBe("100svw");
    } finally {
      document.documentElement.style.removeProperty(UI_FONT_BASE_CSS_PROPERTY);
      document.documentElement.style.removeProperty("--vui-window-width");
      document.documentElement.style.removeProperty("font-size");
    }
  });

  it("normalizes before applying", () => {
    try {
      applyUiFontBasePx(document, 30);
      expect(document.documentElement.style.getPropertyValue(UI_FONT_BASE_CSS_PROPERTY)).toBe("16px");
    } finally {
      document.documentElement.style.removeProperty(UI_FONT_BASE_CSS_PROPERTY);
    }
  });
});

describe("subscribeStoredUiFontBasePx", () => {
  it("stops notifying after unsubscribe", () => {
    const storage = memoryStorage({ [UI_FONT_BASE_STORAGE_KEY]: "14" });
    const listener = vi.fn();
    const unsubscribe = subscribeStoredUiFontBasePx(listener);
    unsubscribe();
    writeStoredUiFontBasePx(15, storage);
    expect(listener).not.toHaveBeenCalled();
  });

  it("reacts to cross-window storage events for the owned key", () => {
    const listener = vi.fn();
    const unsubscribe = subscribeStoredUiFontBasePx(listener);
    try {
      // Storage 事件的语义是「另一窗口已写入」：先写真实存储再派发，与浏览器时序一致。
      window.localStorage.setItem(UI_FONT_BASE_STORAGE_KEY, "17");
      window.dispatchEvent(
        new StorageEvent("storage", {
          key: UI_FONT_BASE_STORAGE_KEY,
          newValue: "17",
          oldValue: null,
        }),
      );
      expect(listener).toHaveBeenCalledWith(17);

      window.dispatchEvent(new StorageEvent("storage", { key: "vibelution.workbench.theme", newValue: "dark" }));
      expect(listener).toHaveBeenCalledTimes(1);
    } finally {
      unsubscribe();
    }
  });

  it("removes the shared window storage listener when the last subscriber leaves", () => {
    const unsubscribeA = subscribeStoredUiFontBasePx(() => undefined);
    const unsubscribeB = subscribeStoredUiFontBasePx(() => undefined);
    unsubscribeA();
    unsubscribeB();
    const spy = vi.spyOn(window, "removeEventListener");
    const unsubscribeC = subscribeStoredUiFontBasePx(() => undefined);
    unsubscribeC();
    expect(spy).toHaveBeenCalledWith("storage", expect.any(Function));
    spy.mockRestore();
  });
});
