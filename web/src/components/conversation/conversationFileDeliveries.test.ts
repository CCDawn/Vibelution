import { describe, expect, it } from "vitest";
import type { CodexTranscriptCell } from "./codexTranscriptCells";
import { buildCodexTranscriptCells } from "./codexTranscriptCells";
import { collectConversationFileDeliveries, fileDeliveryFollowupDraft } from "./conversationFileDeliveryModel";

function cell(id: string, name: string, args: Record<string, unknown>, status: "completed" | "failed" | "running" = "completed"): CodexTranscriptCell {
  return { id, messageId: "turn1", kind: "tool_call", status, tone: "neutral", toolLifecycleModel: {
    toolCalls: [{ toolCallId: id, rawOperationId: id, rawToolName: name, arguments: args, status, title: name, runtimeKind: "tool" }],
    terminalOperations: [], terminalSessions: [], modelObservations: [],
  } };
}

describe("turn file deliveries", () => {
  it("consumes canonical operation projections without depending on synthetic cell ids", () => {
    const cells = buildCodexTranscriptCells({
      id: "turn1", role: "assistant", createdAt: "2026-09-29T00:00:00Z", streaming: false,
      source: { kind: "conversation-message", id: "turn1" }, parts: [],
    }, { operations: [{
      id: "native-op", kind: "tool", label: "写入文件", rawLabel: "write_file_tool",
      status: "completed", summary: "Written", durationSeconds: 1,
      arguments: { file_path: "report.html", content: "<h1>Report</h1>" },
      resultPreview: "[创建文件] [OK] 成功",
    }] });
    expect(collectConversationFileDeliveries(cells).files).toEqual([
      { path: "report.html", content: "<h1>Report</h1>", deleted: false },
    ]);
  });
  it("uses only successful known writes, deduplicates replayed calls and never reads another turn", () => {
    const write = cell("a", "write_file_tool", { file_path: "demo.html", content: "<h1>Hello</h1>" });
    const read = cell("b", "read_file_tool", { file_path: "secret.txt", content: "secret" });
    const fail = cell("c", "write_file_tool", { file_path: "bad.html", content: "bad" }, "failed");
    const pending = cell("d", "write_file_tool", { file_path: "pending.html", content: "partial" }, "running");
    expect(collectConversationFileDeliveries([write, write, read, fail, pending]).files).toEqual([
      { path: "demo.html", content: "<h1>Hello</h1>", deleted: false },
    ]);
    expect(collectConversationFileDeliveries([]).files).toEqual([]);
  });
  it("does not turn a tool-returned error into an artifact", () => {
    const failed = cell("a", "write_file_tool", { file_path: "bad.html", content: "bad" });
    failed.toolLifecycleModel!.toolCalls[0].resultPreview = "[创建文件] [SECURITY] denied";
    expect(collectConversationFileDeliveries([failed]).files).toEqual([]);
  });
  it("invalidates full content after a patch update and keeps ordered patches", () => {
    const write = cell("a", "write_file_tool", { file_path: "a.html", content: "before" });
    const patch = cell("b", "apply_patch_tool", { patch_text: "*** Begin Patch\n*** Update File: a.html\n@@\n-before\n+after\n*** End Patch" });
    const result = collectConversationFileDeliveries([write, patch]);
    expect(result.files).toEqual([{ path: "a.html", content: undefined, deleted: false }]);
    expect(result.patches).toHaveLength(1);
  });
  it("can preview a complete add, but cannot preview a deletion or truncated write", () => {
    const patch = cell("a", "apply_patch", { patch: "*** Begin Patch\n*** Add File: new.html\n+<h1>New</h1>\n*** Delete File: old.html\n*** End Patch" });
    const large = cell("b", "write_file_tool", { file_path: "large.html", content: "x".repeat(200001) });
    const result = collectConversationFileDeliveries([patch, large]);
    expect(result.files[0].content).toBe("<h1>New</h1>");
    expect(result.files[1].deleted).toBe(true);
    expect(result.files[2].content).toBeUndefined();
  });
  it("preserves the existing draft, safely quotes paths, and never auto-submits", () => {
    expect(fileDeliveryFollowupDraft("保留这句", "a\n.html", "zh")).toBe('保留这句\n\n请继续修改文件 "a\\n.html"：');
  });
});
