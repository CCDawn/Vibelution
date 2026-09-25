import { describe, expect, it } from "vitest";

import {
  COMMAND_PALETTE_RECENT_LIMIT,
  isCommandItem,
  readRecentCommandIds,
  recordRecentCommandId,
  resolvePaletteScope,
  withRecentGroupTop,
} from "./paletteScope";

type FakeBacked = Map<string, string>;

function fakeStorage(backed: FakeBacked = new Map()) {
  return {
    getItem: (key: string) => (backed.has(key) ? (backed.get(key) as string) : null),
    setItem: (key: string, value: string) => void backed.set(key, value),
    removeItem: (key: string) => void backed.delete(key),
  };
}

describe("resolvePaletteScope", () => {
  it("routes # to session search with the prefix stripped", () => {
    expect(resolvePaletteScope("#")).toEqual({ kind: "sessions", text: "" });
    expect(resolvePaletteScope("# login 失败")).toEqual({ kind: "sessions", text: " login 失败" });
  });

  it("routes > to command mode with the prefix stripped", () => {
    expect(resolvePaletteScope(">")).toEqual({ kind: "commands", text: "" });
    expect(resolvePaletteScope(">restart")).toEqual({ kind: "commands", text: "restart" });
  });

  it("keeps prefixless queries as the default mixed scope", () => {
    expect(resolvePaletteScope("")).toEqual({ kind: "default", text: "" });
    expect(resolvePaletteScope("chat")).toEqual({ kind: "default", text: "chat" });
    // 前缀必须出现在开头：中间的 # / > 不分流。
    expect(resolvePaletteScope("a > b")).toEqual({ kind: "default", text: "a > b" });
  });
});

describe("isCommandItem", () => {
  it("filters navigation entries out and keeps the rest", () => {
    expect(isCommandItem({ id: "nav:/chat" })).toBe(false);
    expect(isCommandItem({ id: "action:open-session-search" })).toBe(true);
    expect(isCommandItem({ id: "cmd:restart" })).toBe(true);
  });
});

describe("withRecentGroupTop", () => {
  const items = [
    { id: "nav:/chat", group: "导航", label: "对话" },
    { id: "nav:/teams", group: "导航", label: "团队" },
    { id: "action:open", group: "动作", label: "搜索" },
  ];

  it("moves matched items into a top recent group and removes them from their original groups", () => {
    const merged = withRecentGroupTop(items, ["nav:/teams", "action:open"], "最近使用");
    expect(merged.map((item) => item.id)).toEqual(["nav:/teams", "action:open", "nav:/chat"]);
    expect(merged[0].group).toBe("最近使用");
    // 原分组不再重复出现同 id。
    expect(merged.filter((item) => item.id === "nav:/teams")).toHaveLength(1);
  });

  it("keeps items unchanged when nothing matches and drops unknown ids", () => {
    expect(withRecentGroupTop(items, [], "Recent")).toEqual(items);
    expect(withRecentGroupTop(items, ["gone:id"], "Recent")).toEqual(items);
    // recentIds 内的重复 id 只出现一次，顺序按最近执行在前。
    const merged = withRecentGroupTop(items, ["nav:/chat", "nav:/chat"], "Recent");
    expect(merged.map((item) => item.id)).toEqual(["nav:/chat", "nav:/teams", "action:open"]);
  });
});

describe("recent command id storage", () => {
  it("reads normalized ids and tolerates corrupt payloads", () => {
    expect(readRecentCommandIds(fakeStorage())).toEqual([]);
    expect(
      readRecentCommandIds(fakeStorage(new Map([["vibelution.commandPalette.recent.v1", JSON.stringify(["a", 3, "b"])]]))),
    ).toEqual(["a", "b"]);
    expect(
      readRecentCommandIds(fakeStorage(new Map([["vibelution.commandPalette.recent.v1", "{not json"]]))),
    ).toEqual([]);
    expect(readRecentCommandIds(null)).toEqual([]);
  });

  it("records most-recent-first with dedupe and persistence", () => {
    const backed: FakeBacked = new Map();
    const storage = fakeStorage(backed);
    let ids = recordRecentCommandId("nav:/chat", [], storage);
    ids = recordRecentCommandId("nav:/teams", ids, storage);
    ids = recordRecentCommandId("nav:/chat", ids, storage);
    expect(ids).toEqual(["nav:/chat", "nav:/teams"]);
    expect(JSON.parse(backed.get("vibelution.commandPalette.recent.v1") as string)).toEqual([
      "nav:/chat",
      "nav:/teams",
    ]);
    expect(readRecentCommandIds(storage)).toEqual(["nav:/chat", "nav:/teams"]);
  });

  it("caps the list at the recent limit and degrades when storage is unavailable", () => {
    const previous = Array.from({ length: COMMAND_PALETTE_RECENT_LIMIT }, (_, index) => `id-${index}`);
    const capped = recordRecentCommandId("newest", previous, fakeStorage());
    expect(capped).toHaveLength(COMMAND_PALETTE_RECENT_LIMIT);
    expect(capped[0]).toBe("newest");
    expect(capped).not.toContain(`id-${COMMAND_PALETTE_RECENT_LIMIT - 1}`);
    // 存储为 null（SSR/隐私模式）时仍返回计算结果，供会话内使用。
    expect(recordRecentCommandId("a", ["b"], null)).toEqual(["a", "b"]);
  });
});
