import { describe, expect, it } from "vitest";

import {
  completedToolPresentationSummary,
  conversationToolPresentationLabel,
} from "./conversationToolPresentation";

describe("conversation tool presentation", () => {
  it("uses the semantic lifecycle summary before a structured result preview", () => {
    expect(
      completedToolPresentationSummary({
        toolSummary: "工作区干净",
        cellSummary: "",
        resultPreview:
          '{"dirty_summary":"工作区干净","modified_paths":[]}',
        cellText: "",
        toolName: "get_git_status_summary_tool",
        language: "zh",
      }),
    ).toBe("工作区干净");
  });

  it("extracts a compact semantic value from a structured result", () => {
    expect(
      completedToolPresentationSummary({
        resultPreview:
          '{"dirty_summary":"工作区干净","modified_paths":[]}',
        language: "zh",
      }),
    ).toBe("工作区干净");
  });

  it("extracts a semantic value from a truncated structured preview", () => {
    expect(
      completedToolPresentationSummary({
        resultPreview:
          '{"dirty_summary":"工作区干净","modified_paths":[',
        language: "zh",
      }),
    ).toBe("工作区干净");
  });

  it("does not render an unreadable fragment for truncated structured arrays", () => {
    expect(
      completedToolPresentationSummary({
        resultPreview: '[{"commit_sha":"4533db9c6367',
        language: "zh",
      }),
    ).toBe("已返回结构化结果");
  });

  it.each([
    ["explain_current_worktree_tool", "工作树详情"],
    ["get_core_context_tool", "核心上下文"],
    ["get_current_goal_tool", "当前目标"],
    ["conversation_log_inspect_tool", "检查会话日志"],
  ])("maps %s to its Chinese display label", (toolName, expected) => {
    expect(conversationToolPresentationLabel(toolName, "zh")).toBe(expected);
  });

  it("uses the inspected query instead of a low-value ok status", () => {
    expect(
      completedToolPresentationSummary({
        toolSummary: '{"status":"ok",',
        resultPreview: JSON.stringify({
          status: "ok",
          query: "P1-ROW-STABILITY-20260717T2342",
        }),
        toolName: "conversation_log_inspect_tool",
        language: "zh",
      }),
    ).toBe("P1-ROW-STABILITY-20260717T2342");
  });

  it("uses the inspected log filename when no query is available", () => {
    expect(
      completedToolPresentationSummary({
        resultPreview: JSON.stringify({
          status: "ok",
          query: "",
          logPath: "log_info/conversation_20260717_234402__chat__你好.jsonl",
        }),
        toolName: "conversation_log_inspect_tool",
        language: "zh",
      }),
    ).toBe("conversation_20260717_234402__chat__你好.jsonl");
  });

  it.each(["ok", "done", "success", '{"status":"ok"}'])(
    "hides low-value completed summaries: %s",
    (resultPreview) => {
      expect(
        completedToolPresentationSummary({
          resultPreview,
          language: "zh",
        }),
      ).toBe("");
    },
  );
});
