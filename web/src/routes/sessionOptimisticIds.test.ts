import { describe, expect, it } from "vitest";

import { createTempSessionId, isTempSessionId } from "./sessionOptimisticIds";

describe("sessionOptimisticIds", () => {
  it("mints temp session ids with a stable prefix", () => {
    const id = createTempSessionId();
    expect(isTempSessionId(id)).toBe(true);
    expect(id.startsWith("temp-session-")).toBe(true);
  });

  it("rejects real session ids", () => {
    expect(isTempSessionId("session-20260803-094116-570359")).toBe(false);
    expect(isTempSessionId("")).toBe(false);
    expect(isTempSessionId(null)).toBe(false);
  });
});
