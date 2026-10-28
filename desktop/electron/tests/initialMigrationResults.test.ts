import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { InitialMigrationResults } from "../src/assistant/initialMigrationResults.js";

describe("initial migration result references", () => {
  it("retains only a confirmed result for the original operation across reopen", async () => {
    const root = mkdtempSync(join(tmpdir(), "initial-result-")), id = "initial-" + "a".repeat(40);
    try {
      const store = new InitialMigrationResults(join(root, "results"));
      expect(await store.get(id)).toBeNull();
      await store.record(id, "completed");
      expect(await new InitialMigrationResults(join(root, "results")).get(id)).toBe("completed");
      await expect(store.record(id, "partial")).rejects.toThrow();
    } finally { rmSync(root, { recursive: true, force: true }); }
  });
});
