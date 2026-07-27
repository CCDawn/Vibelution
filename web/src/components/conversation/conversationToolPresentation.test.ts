import { describe, expect, it } from "vitest";

import {
  completedToolPresentationSummary,
  conversationToolDetailPresentation,
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
    ["exec_command", "运行命令"],
    ["write_stdin", "写入终端"],
  ])("maps %s to its Chinese display label", (toolName, expected) => {
    expect(conversationToolPresentationLabel(toolName, "zh")).toBe(expected);
  });

  it("maps source-collection tools instead of exposing their internal names", () => {
    expect(conversationToolPresentationLabel("source_collection_context_tool", "zh"))
      .not.toBe("source_collection_context_tool");
    expect(conversationToolPresentationLabel("source_collection_stage_writeback_tool", "zh"))
      .not.toBe("source_collection_stage_writeback_tool");
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

  it.each(["ok", "done", "success", "执行完成", '{"status":"ok"}'])(
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

  it("keeps bracket-prefixed human-readable failures instead of treating them as broken JSON", () => {
    expect(completedToolPresentationSummary({
      toolSummary: "[超时] 命令执行超时",
      toolName: "exec_command",
      language: "zh",
    })).toBe("[超时] 命令执行超时");
  });

  it("turns a code-symbol payload into one semantic activity summary", () => {
    expect(
      completedToolPresentationSummary({
        resultPreview: JSON.stringify({
          status: "ok",
          mode: "search",
          query: "savedDraft",
          count: 4,
          results: [],
        }),
        toolName: "code_symbol_tool",
        language: "zh",
      }),
    ).toBe("搜索 savedDraft · 4 个结果");
  });

  it("renders code-symbol results as compact hit lines instead of raw JSON", () => {
    const presented = conversationToolDetailPresentation({
      value: JSON.stringify({
        status: "ok",
        mode: "search",
        query: "savedDraft",
        count: 3,
        results: [
          { line: 183, preview: "const [savedDraft, setSavedDraft] = useState..." },
          { line: 947, preview: "setSavedDraft(nextSnapshot)" },
          { line: 1294, preview: "savedDraft?.providerWorkspace" },
        ],
      }),
      toolName: "code_symbol_tool",
      language: "zh",
    });

    expect(presented).toContain(" 183  const [savedDraft");
    expect(presented).toContain(" 947  setSavedDraft(nextSnapshot)");
    expect(presented).not.toContain('"status"');
    expect(presented).not.toContain('"results"');
  });
});
