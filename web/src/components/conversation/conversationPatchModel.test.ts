import { describe, expect, it } from "vitest";

import {
  buildConversationPatchDiff,
  conversationToolPatchText,
} from "./conversationPatchModel";
import type { CodexTranscriptCell } from "./codexTranscriptCells";

describe("buildConversationPatchDiff", () => {
  it("parses an apply_patch update with per-file diff stats", () => {
    const diff = buildConversationPatchDiff([
      "*** Begin Patch",
      "*** Update File: web/src/app.ts",
      "@@",
      "-const value = 1;",
      "+const value = 2;",
      "+const extra = true;",
      "*** End Patch",
    ].join("\n"));

    expect(diff.files).toHaveLength(1);
    expect(diff.files[0].path).toBe("web/src/app.ts");
    expect(diff.files[0].op).toBe("update");
    expect(diff.files[0].additions).toBe(2);
    expect(diff.files[0].deletions).toBe(1);
    expect(diff.additions).toBe(2);
    expect(diff.deletions).toBe(1);
    expect(diff.files[0].lines.map((line) => line.kind)).toEqual(["hunk", "del", "add", "add"]);
    expect(diff.files[0].lines[1].text).toBe("const value = 1;");
  });

  it("parses add and delete file sections", () => {
    const diff = buildConversationPatchDiff([
      "*** Begin Patch",
      "*** Add File: new.txt",
      "+hello",
      "+world",
      "*** Delete File: old.txt",
      "-remove me",
      "*** End Patch",
    ].join("\n"));

    expect(diff.files.map((file) => [file.path, file.op])).toEqual([
      ["new.txt", "add"],
      ["old.txt", "delete"],
    ]);
    expect(diff.files[0].additions).toBe(2);
    expect(diff.files[1].deletions).toBe(1);
    expect(diff.lineCount).toBe(3);
  });

  it("numbers lines from a git-style hunk header", () => {
    const diff = buildConversationPatchDiff([
      "diff --git a/demo.py b/demo.py",
      "index 1111111..2222222 100644",
      "--- a/demo.py",
      "+++ b/demo.py",
      "@@ -10,3 +10,4 @@",
      " context",
      "-old",
      "+new",
      "+added",
    ].join("\n"));

    expect(diff.files).toHaveLength(1);
    expect(diff.files[0].path).toBe("demo.py");
    const [, context, removed, added, added2] = diff.files[0].lines;
    expect(context.oldLine).toBe(10);
    expect(context.newLine).toBe(10);
    expect(removed.oldLine).toBe(11);
    expect(added.newLine).toBe(11);
    expect(added2.newLine).toBe(12);
  });

  it("marks backend-trimmed patch text as truncated", () => {
    const diff = buildConversationPatchDiff("*** Begin Patch\n*** Update File: a.ts\n@@\n-old\n+new…");
    expect(diff.truncated).toBe(true);
  });

  it("returns an empty diff for blank input", () => {
    expect(buildConversationPatchDiff("   ").files).toEqual([]);
  });
});

describe("conversationToolPatchText", () => {
  const cellWithArguments = (argumentsRecord: Record<string, unknown>): CodexTranscriptCell => ({
    id: "cell-1",
    kind: "tool_call",
    messageId: "message-1",
    status: "completed",
    tone: "neutral",
    operationIds: ["op-1"],
    toolLifecycleModel: {
      toolCalls: [{
        toolCallId: "tool_call:op-1",
        rawOperationId: "op-1",
        status: "completed",
        title: "apply_patch_tool",
        rawToolName: "apply_patch_tool",
        runtimeKind: "tool",
        arguments: argumentsRecord,
      }],
      terminalOperations: [],
      terminalSessions: [],
      modelObservations: [],
    },
  });

  it("reads patch_text from the matched tool call arguments", () => {
    const cell = cellWithArguments({ patch_text: "*** Begin Patch\n*** End Patch" });
    expect(conversationToolPatchText(cell)).toBe("*** Begin Patch\n*** End Patch");
  });

  it("falls back to the cell-level tool arguments", () => {
    const cell: CodexTranscriptCell = {
      id: "cell-2",
      kind: "tool_call",
      messageId: "message-1",
      status: "running",
      tone: "running",
      toolArguments: { patch: "*** Begin Patch\n*** End Patch" },
    };
    expect(conversationToolPatchText(cell)).toBe("*** Begin Patch\n*** End Patch");
  });

  it("returns an empty string when no patch payload exists", () => {
    expect(conversationToolPatchText(cellWithArguments({ path: "a.ts" }))).toBe("");
  });
});
