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
  it.each(["[patch] 格式错误: 缺少结束标记", "[patch] 错误: hunk 不匹配", "[patch] 错误: 原子应用失败"])("excludes completed calls returning %s", (resultPreview) => {
    const failed = cell("patch-error", "apply_patch_tool", { patch_text: "*** Begin Patch\n*** Add File: missing.html\n+wrong\n*** End Patch" });
    failed.toolLifecycleModel!.toolCalls[0].resultPreview = resultPreview;
    expect(collectConversationFileDeliveries([failed])).toEqual({ files: [], patches: [] });
  });
  it("invalidates full content after a patch update and keeps ordered patches", () => {
    const write = cell("a", "write_file_tool", { file_path: "a.html", content: "before" });
    const patch = cell("b", "apply_patch_tool", { patch_text: "*** Begin Patch\n*** Update File: a.html\n@@\n-before\n+after\n*** End Patch" });
    const result = collectConversationFileDeliveries([write, patch]);
    expect(result.files).toEqual([{ path: "a.html", content: undefined, deleted: false }]);
    expect(result.patches).toHaveLength(1);
  });
  it("includes native SEARCH/REPLACE and edit_file calls, but excludes their returned failures", () => {
    const edited = cell("replace", "apply_diff_edit_tool", {
      file_path: "report.html", diff_text: "<<<<<<< SEARCH\nold\n=======\nnew\n>>>>>>> REPLACE\n<<<<<<< SEARCH\nsecond\n=======\nupdated\n>>>>>>> REPLACE",
    });
    const failed = cell("failed", "apply_diff_edit_tool", { file_path: "bad.html", diff_text: "bad" });
    failed.toolLifecycleModel!.toolCalls[0].resultPreview = "[编辑] 错误: 找不到匹配的代码块";
    const malformed = cell("invalid", "apply_diff_edit_tool", { file_path: "invalid.html", diff_text: "bad" });
    malformed.toolLifecycleModel!.toolCalls[0].resultPreview = "[编辑] 格式验证失败: 缺少 SEARCH";
    const legacy = cell("edit", "edit_file", { file_path: "legacy.txt", search_string: "before", replace_string: "after" });
    const result = collectConversationFileDeliveries([edited, failed, malformed, legacy]);
    expect(result.files.map((file) => file.path)).toEqual(["report.html", "legacy.txt"]);
    expect(result.files.every((file) => file.content === undefined)).toBe(true);
    expect(result.patches[0].text).toContain("-old\n+new\n@@\n-second\n+updated");
    expect(result.patches[1].text).toContain("-before\n+after");
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
