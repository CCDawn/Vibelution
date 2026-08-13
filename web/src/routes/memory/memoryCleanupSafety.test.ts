import { describe, expect, it } from "vitest";

import {
  canExecuteMemoryCleanup,
  isMemoryCleanupExecutionSuccessful,
} from "./memoryCleanupSafety";

describe("memoryCleanupSafety", () => {
  it("requires a live preview token as well as the exact confirmation phrase", () => {
    const preview = {
      previewToken: "preview-token",
      confirmationPhrase: "硬删除记忆",
    };

    expect(canExecuteMemoryCleanup(null, 1, "硬删除记忆")).toBe(false);
    expect(canExecuteMemoryCleanup({ ...preview, previewToken: "" }, 1, "硬删除记忆")).toBe(false);
    expect(canExecuteMemoryCleanup(preview, 0, "硬删除记忆")).toBe(false);
    expect(canExecuteMemoryCleanup(preview, 1, "delete")).toBe(false);
    expect(canExecuteMemoryCleanup(preview, 1, "硬删除记忆")).toBe(true);
  });

  it("treats partial or failed execution payloads as non-success", () => {
    expect(isMemoryCleanupExecutionSuccessful({ outcome: "succeeded" })).toBe(true);
    expect(isMemoryCleanupExecutionSuccessful({ outcome: "partial" })).toBe(false);
    expect(isMemoryCleanupExecutionSuccessful({ outcome: "failed" })).toBe(false);
    expect(isMemoryCleanupExecutionSuccessful({})).toBe(false);
  });
});
