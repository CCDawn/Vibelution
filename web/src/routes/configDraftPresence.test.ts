import { describe, expect, it } from "vitest";

import {
  CONFIG_DRAFT_PRESENCE_KEY,
  publishConfigDraftPresence,
  readConfigDraftPresence,
} from "./configDraftPresence";

function memoryStorage() {
  const values = new Map<string, string>();
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
    removeItem: (key: string) => values.delete(key),
  };
}

describe("config draft presence", () => {
  it("shares only dirty presence and never serializes config content", () => {
    const storage = memoryStorage();
    publishConfigDraftPresence(true, { now: () => 1_000, storage });

    expect(readConfigDraftPresence({ now: () => 1_001, storage })).toBe(true);
    expect(storage.getItem(CONFIG_DRAFT_PRESENCE_KEY)).not.toContain("publicConfig");
    expect(storage.getItem(CONFIG_DRAFT_PRESENCE_KEY)).not.toContain("secret");
  });

  it("expires abandoned dirty presence and clears after a successful save", () => {
    const storage = memoryStorage();
    publishConfigDraftPresence(true, { now: () => 1_000, storage });
    expect(readConfigDraftPresence({ now: () => 1_000 + 31 * 60 * 1_000, storage })).toBe(false);

    publishConfigDraftPresence(false, { now: () => 2_000, storage });
    expect(readConfigDraftPresence({ now: () => 2_001, storage })).toBe(false);
  });

  it("fails closed on malformed storage", () => {
    const storage = memoryStorage();
    storage.setItem(CONFIG_DRAFT_PRESENCE_KEY, "{bad-json");
    expect(readConfigDraftPresence({ now: () => 1_000, storage })).toBe(false);
  });
});
