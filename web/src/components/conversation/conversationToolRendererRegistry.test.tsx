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
