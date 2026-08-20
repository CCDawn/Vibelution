import { mkdtemp, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import {
  MAIN_LINE_INTENT_FILE,
  readMainLineIntent,
  writeMainLineIntent,
} from "../src/lifecycle/mainLine/commandIntent.js";

describe("mainLineCommandIntent", () => {
  it("round-trips a crash-recovery intent through the runtime-manager file", async () => {
    const dir = await mkdtemp(join(tmpdir(), "main-line-intent-"));
    await writeMainLineIntent(dir, {
      schemaVersion: 1,
      desiredState: "open",
      operation: "restart",
      commandId: "cmd_recovery",
      updatedAt: "2026-08-20T10:00:00Z",
    });
    const raw = await readFile(join(dir, MAIN_LINE_INTENT_FILE), "utf8");
    expect(JSON.parse(raw).commandId).toBe("cmd_recovery");
    await expect(readMainLineIntent(dir)).resolves.toMatchObject({
      desiredState: "open",
      operation: "restart",
      commandId: "cmd_recovery",
    });
  });

  it("returns null for a missing or invalid intent file", async () => {
    const dir = await mkdtemp(join(tmpdir(), "main-line-intent-missing-"));
    await expect(readMainLineIntent(dir)).resolves.toBeNull();
  });
});
