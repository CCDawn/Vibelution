import { describe, expect, it } from "vitest";

import { getCachedResponseSegments, trimOldestCacheEntries } from "./conversationResponseSegmentCache";

describe("conversationResponseSegmentCache", () => {
  it("parses once and reuses LRU-touched cache entries", () => {
    const cache = new Map();
    const first = getCachedResponseSegments(cache, "hello", 2);
    const second = getCachedResponseSegments(cache, "hello", 2);
    expect(first).toBe(second);
    expect(cache.size).toBe(1);
  });

  it("trims oldest entries when over limit", () => {
    const cache = new Map<string, number>([
      ["a", 1],
      ["b", 2],
      ["c", 3],
    ]);
    trimOldestCacheEntries(cache, 2);
    expect([...cache.keys()]).toEqual(["b", "c"]);
  });
});
