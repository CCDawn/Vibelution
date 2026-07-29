import { describe, expect, it } from "vitest";

import {
  conversationToolRendererFor,
  conversationToolRendererForPresentationLabel,
  conversationToolRendererLabel,
} from "./conversationToolRendererRegistry";

describe("conversation tool renderer registry", () => {
  it.each([
    ["get_git_status_summary_tool", "git", "Git 状态"],
    ["code_symbol_tool", "code", "代码图谱"],
    ["exec_command", "command", "运行命令"],
    ["write_stdin", "command", "写入终端"],
    ["web_search_tool", "search", "网页搜索"],
    ["web_fetch_tool", "files", "网页读取"],
    ["source_collection_context_tool", "files", "读取资料上下文"],
    ["source_collection_stage_writeback_tool", "edit", "资料提炼回写"],
    ["conversation_log_inspect_tool", "conversation", "检查会话日志"],
    ["unregistered_vendor_tool", "generic", "unregistered_vendor_tool"],
  ])("maps %s to a stable family and label", (toolName, family, label) => {
    expect(conversationToolRendererFor(toolName).family).toBe(family);
    expect(conversationToolRendererLabel(toolName, "zh")).toBe(label);
  });

  it("uses the displayed semantic label as a fallback for normalized lifecycle names", () => {
    expect(conversationToolRendererForPresentationLabel("代码图谱", "zh").family).toBe("code");
  });
});
