import { describe, expect, it } from "vitest";
import { Bot, ListFilter, MonitorSmartphone } from "lucide-react";

import {
  conversationToolRendererFor,
  conversationToolRendererForPresentationLabel,
  conversationToolRendererLabel,
} from "./conversationToolRendererRegistry";

describe("conversation tool renderer registry", () => {
  it.each([
    ["get_git_status_summary_tool", "git", "Git 状态"],
    ["code_symbol_tool", "code", "代码图谱"],
    ["exec_command", "command", "执行命令"],
    ["write_stdin", "command", "写入终端"],
    ["web_search_tool", "search", "网页搜索"],
    ["web_fetch_tool", "files", "网页读取"],
    ["source_collection_context_tool", "files", "读取资料上下文"],
    ["source_collection_stage_writeback_tool", "edit", "资料阶段写回"],
    ["conversation_log_inspect_tool", "conversation", "检查会话日志"],
    // Unregistered tools still resolve to the generic family (the label is only
    // display text and matches no curated family), but they no longer echo their
    // raw id — the label is derived from it instead.
    ["unregistered_vendor_tool", "generic", "Unregistered Vendor"],
  ])("maps %s to a stable family and label", (toolName, family, label) => {
    expect(conversationToolRendererFor(toolName).family).toBe(family);
    expect(conversationToolRendererLabel(toolName, "zh")).toBe(label);
  });

  it("uses the displayed semantic label as a fallback for normalized lifecycle names", () => {
    expect(conversationToolRendererForPresentationLabel("代码图谱", "zh").family).toBe("code");
  });

  it.each([
    ["source_read", "files", "read_file_tool", "读取源码"],
    ["source_search", "search", "search_code_tool", "搜索源码"],
    ["session_list", "conversation", "conversation_log_inspect_tool", "列出会话"],
    ["agent_update", "edit", "apply_patch_tool", "修改 Agent"],
    ["dispatch_write", "conversation", "conversation_log_inspect_tool", "派遣 Agent 修改项目"],
    ["browser_read", "generic", "unregistered_vendor_tool", "读取网页"],
    ["runtime_command", "command", "exec_command", "控制原生运行"],
    ["provider_test", "verify", "run_test_for_tool", "测试模型连接"],
  ])("uses the real assistant action %s for its family, icon and label", (action, family, iconTool, label) => {
    for (const toolName of ["personal_assistant_action_tool", "personal_assistant_manage_tool"]) {
      const descriptor = conversationToolRendererFor(toolName, { action });
      expect(descriptor.family).toBe(family);
      const actionIcon = action === "session_list" ? ListFilter : action === "dispatch_write" ? Bot : action === "browser_read" ? MonitorSmartphone : null;
      expect(descriptor.icon).toBe(actionIcon ?? conversationToolRendererFor(iconTool).icon);
      expect(conversationToolRendererLabel(toolName, "zh", { action })).toBe(label);
    }
  });

  it("preserves the original descriptor for missing, unknown and unrelated action arguments", () => {
    const name = "personal_assistant_action_tool";
    for (const args of [{}, { action: "future_source_read" }, { action: "constructor" }]) {
      expect(conversationToolRendererFor(name, args)).toBe(conversationToolRendererFor(name));
    }
    expect(conversationToolRendererFor("read_file_tool", { action: "agent_update" }).family).toBe("files");
    expect(conversationToolRendererLabel(name, "zh", { action: "future_action" })).toBe("处理助理请求");
  });
});
