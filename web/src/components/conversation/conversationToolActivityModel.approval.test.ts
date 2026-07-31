import { describe, expect, it } from "vitest";

import type { CodexTranscriptCell } from "./codexTranscriptCells";
import {
  createCodexTranscriptToolActivity,
  shouldAttachToolApprovalToActivity,
} from "./conversationToolActivityModel";

function toolCell(
  name: string,
  status: CodexTranscriptCell["status"],
): CodexTranscriptCell {
  return {
    id: `${name}-${status}`,
    kind: "tool_call",
    messageId: "m1",
    status,
    tone: status === "running" ? "running" : "neutral",
    title: name,
    toolLifecycleModel: {
      toolCalls: [{
        toolCallId: "c1",
        rawOperationId: "op-1",
        rawToolName: name,
        title: name,
        summary: "",
        resultPreview: "",
        runtimeKind: "tool",
        status,
      }],
      terminalOperations: [],
      terminalSessions: [],
      modelObservations: [],
    },
  };
}

describe("shouldAttachToolApprovalToActivity", () => {
  it("attaches to an open tool cell that matches the pending tool name", () => {
    const activity = createCodexTranscriptToolActivity([
      toolCell("read_file_tool", "completed"),
      toolCell("web_fetch_tool", "running"),
    ]);
    expect(shouldAttachToolApprovalToActivity(activity, "web_fetch_tool")).toBe(true);
    expect(shouldAttachToolApprovalToActivity(activity, "cli_tool")).toBe(false);
  });

  it("can fall back to any open tool when the name is not yet projected", () => {
    const activity = createCodexTranscriptToolActivity([
      toolCell("cli_tool", "running"),
    ]);
    expect(shouldAttachToolApprovalToActivity(activity, "web_fetch_tool", {
      preferAnyOpenWhenUnmatched: true,
    })).toBe(true);
  });
});
