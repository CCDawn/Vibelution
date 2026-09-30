import { describe, expect, it } from "vitest";

import type { ConversationMessage } from "../../api/types";
import { rerunFileRestorePlan } from "./rerunFileRestore";

function message(
  id: string,
  role: "user" | "assistant",
  extras: { turnId?: string; changedFiles?: Array<{ path: string }> | unknown } = {},
): ConversationMessage {
  const metadata: Record<string, unknown> = {};
  if (extras.changedFiles !== undefined) {
    metadata.changedFiles = extras.changedFiles;
  }
  return {
    id,
    role,
    content: id,
    timestamp: "2026-09-30T00:00:00Z",
    status: "completed",
    turnId: extras.turnId ?? "",
    metadata,
  } as ConversationMessage;
}

describe("rerunFileRestorePlan", () => {
  const tail = [
    message("user-1", "user", { turnId: "turn-user" }),
    message("assistant-1", "assistant", {
      turnId: "turn-a",
      changedFiles: [{ path: "src/a.ts" }, { path: "src/shared.ts" }],
    }),
    message("assistant-2", "assistant", {
      turnId: "turn-b",
      changedFiles: [{ path: "src/b.ts" }, { path: "src/shared.ts" }],
    }),
  ];

  it("returns nothing when the start index is outside the loaded window", () => {
    expect(rerunFileRestorePlan(tail, -1)).toEqual({ turnIds: [], paths: [] });
    expect(rerunFileRestorePlan(tail, 1.5)).toEqual({ turnIds: [], paths: [] });
    expect(rerunFileRestorePlan(tail, 99)).toEqual({ turnIds: [], paths: [] });
  });

  it("collects unique turns and paths from the replaced tail, oldest first", () => {
    expect(rerunFileRestorePlan(tail, 0)).toEqual({
      turnIds: ["turn-a", "turn-b"],
      paths: ["src/a.ts", "src/shared.ts", "src/b.ts"],
    });
  });

  it("starts at the clicked answer, so earlier file changes stay out of the plan", () => {
    expect(rerunFileRestorePlan(tail, 2)).toEqual({
      turnIds: ["turn-b"],
      paths: ["src/b.ts", "src/shared.ts"],
    });
  });

  it("skips file lists that have no turn id and malformed entries", () => {
    const messages = [
      message("assistant-blank", "assistant", {
        changedFiles: [{ path: "src/orphan.ts" }],
      }),
      message("assistant-bad", "assistant", {
        turnId: "turn-bad",
        changedFiles: "src/nope.ts",
      }),
      message("assistant-ok", "assistant", {
        turnId: "turn-ok",
        changedFiles: [{ path: "  " }, { path: "src/ok.ts" }],
      }),
    ];
    expect(rerunFileRestorePlan(messages, 0)).toEqual({
      turnIds: ["turn-ok"],
      paths: ["src/ok.ts"],
    });
  });

  it("records one turn id when several messages share it", () => {
    const messages = [
      message("assistant-1", "assistant", {
        turnId: "turn-same",
        changedFiles: [{ path: "src/a.ts" }],
      }),
      message("assistant-2", "assistant", {
        turnId: "turn-same",
        changedFiles: [{ path: "src/b.ts" }],
      }),
    ];
    expect(rerunFileRestorePlan(messages, 0).turnIds).toEqual(["turn-same"]);
  });
});
