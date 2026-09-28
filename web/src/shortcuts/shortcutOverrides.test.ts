/** @vitest-environment node */
import { describe, expect, it, vi } from "vitest";

import {
  normalizeShortcutOverrides,
  readStoredShortcutOverrides,
  SHORTCUT_OVERRIDES_STORAGE_KEY,
  subscribeStoredShortcutOverrides,
  writeStoredShortcutOverrides,
} from "./shortcutOverrides";

function memoryStorage(initial: Record<string, string> = {}): {
  storage: Pick<Storage, "getItem" | "setItem" | "removeItem">;
  map: Map<string, string>;
} {
  const map = new Map(Object.entries(initial));
  return {
    map,
    storage: {
      getItem: (key) => map.get(key) ?? null,
      setItem: (key, value) => {
        map.set(key, value);
      },
      removeItem: (key) => {
        map.delete(key);
      },
    },
  };
}

describe("normalizeShortcutOverrides", () => {
  it("丢弃未知命令与非法条目", () => {
    expect(
      normalizeShortcutOverrides({ openCommandPalette: ["CmdOrCtrl+k"], unknown: ["Ctrl+g"], bad: ["%"] }),
    ).toEqual({ openCommandPalette: ["CmdOrCtrl+k"] });
  });

  it("保留显式空数组（= 用户清除）", () => {
    expect(normalizeShortcutOverrides({ openSessionSearch: [] })).toEqual({ openSessionSearch: [] });
  });

  it("非对象输入归一为空表", () => {
    expect(normalizeShortcutOverrides(null)).toEqual({});
    expect(normalizeShortcutOverrides("x")).toEqual({});
    expect(normalizeShortcutOverrides(["CmdOrCtrl+k"])).toEqual({});
  });
});

describe("readStoredShortcutOverrides / writeStoredShortcutOverrides", () => {
  it("从 localStorage 读取并清洗", () => {
    const { storage } = memoryStorage({
      [SHORTCUT_OVERRIDES_STORAGE_KEY]: JSON.stringify({ openSessionSearch: ["Ctrl+Alt+f"] }),
    });
    expect(readStoredShortcutOverrides(storage)).toEqual({ openSessionSearch: ["Ctrl+Alt+f"] });
  });

  it("损坏 JSON 与缺失键返回空表", () => {
    const { storage } = memoryStorage({ [SHORTCUT_OVERRIDES_STORAGE_KEY]: "{not-json" });
    expect(readStoredShortcutOverrides(storage)).toEqual({});
    expect(readStoredShortcutOverrides(memoryStorage().storage)).toEqual({});
  });

  it("写入持久化；空覆盖时移除键", () => {
    const { storage, map } = memoryStorage();
    writeStoredShortcutOverrides({ openSessionSearch: ["Ctrl+Alt+l"] }, storage);
    expect(map.get(SHORTCUT_OVERRIDES_STORAGE_KEY)).toBe(JSON.stringify({ openSessionSearch: ["Ctrl+Alt+l"] }));
    writeStoredShortcutOverrides({}, storage);
    expect(map.has(SHORTCUT_OVERRIDES_STORAGE_KEY)).toBe(false);
  });

  it("存储抛异常时静默降级", () => {
    const throwing = {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
      removeItem: () => {
        throw new Error("blocked");
      },
    };
    expect(readStoredShortcutOverrides(throwing)).toEqual({});
    expect(() => writeStoredShortcutOverrides({ openSessionSearch: [] }, throwing)).not.toThrow();
  });

  it("真实写入触发订阅者；内容未变的幂等写入不触发", () => {
    const { storage } = memoryStorage();
    const listener = vi.fn();
    const unsubscribe = subscribeStoredShortcutOverrides(listener);
    try {
      // 空覆盖写入空存储 = 无变化，不通知。
      writeStoredShortcutOverrides({}, storage);
      expect(listener).not.toHaveBeenCalled();

      writeStoredShortcutOverrides({ openSessionSearch: ["Ctrl+Alt+f"] }, storage);
      expect(listener).toHaveBeenCalledTimes(1);
      expect(readStoredShortcutOverrides(storage)).toEqual({ openSessionSearch: ["Ctrl+Alt+f"] });

      // 相同内容重复写入（如壳层挂载写回）= 幂等，不通知。
      writeStoredShortcutOverrides({ openSessionSearch: ["Ctrl+Alt+f"] }, storage);
      expect(listener).toHaveBeenCalledTimes(1);

      // 清空覆盖移除键并通知。
      writeStoredShortcutOverrides({}, storage);
      expect(listener).toHaveBeenCalledTimes(2);
      expect(mapHas(storage)).toBe(false);
    } finally {
      unsubscribe();
    }
    writeStoredShortcutOverrides({ openCommandPalette: ["Ctrl+Alt+k"] }, storage);
    expect(listener).toHaveBeenCalledTimes(2);
  });
});

function mapHas(storage: Pick<Storage, "getItem">): boolean {
  return storage.getItem(SHORTCUT_OVERRIDES_STORAGE_KEY) !== null;
}
