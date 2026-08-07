import { describe, expect, it } from "vitest";

import {
  buildCodexToolActivityPills,
  completedToolPresentationSummary,
  conversationToolDetailPresentation,
  conversationToolPresentationLabel,
  extractToolDisplayCommand,
  formatCodexStyleToolActivityLine,
  normalizeToolActivityStatus,
  terminalSandboxPresentationDetail,
  terminalSandboxPresentationSummary,
} from "./conversationToolPresentation";

describe("conversation tool presentation", () => {
  it.each([
    ["web_search_tool", "网页搜索", "Web search"],
    ["web_fetch_tool", "网页读取", "Read web page"],
    ["source_collection_context_tool", "读取资料上下文", "Read source context"],
    ["source_collection_stage_writeback_tool", "资料阶段写回", "Write source-stage result"],
  ])("uses a product label for %s", (toolName, zh, en) => {
    expect(conversationToolPresentationLabel(toolName, "zh")).toBe(zh);
    expect(conversationToolPresentationLabel(toolName, "en")).toBe(en);
  });

  it("keeps completed terminal output out of the collapsed command summary", () => {
    expect(
      completedToolPresentationSummary({
        toolSummary: JSON.stringify({
          status: "running",
          terminalSessionId: "sandbox-1",
          sessionOpen: true,
        }),
        resultPreview: "# Vibelution Development Standard",
        toolName: "exec_command",
        status: "completed",
        language: "zh",
      }),
    ).toBe("");
  });

  it("keeps a completed terminal row quiet when it has no useful output", () => {
    expect(
      completedToolPresentationSummary({
        toolSummary: JSON.stringify({
          status: "running",
          terminalSessionId: "sandbox-1",
          sessionOpen: true,
        }),
        toolName: "exec_command",
        status: "completed",
        language: "zh",
      }),
    ).toBe("");
  });

  it("shows running only when the terminal tool lifecycle is actually active", () => {
    expect(
      completedToolPresentationSummary({
        toolSummary: JSON.stringify({
          status: "running",
          terminalSessionId: "sandbox-1",
          sessionOpen: true,
        }),
        resultPreview: "partial output",
        toolName: "exec_command",
        status: "running",
        language: "zh",
      }),
    ).toBe("正在运行");
  });

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
    ["exec_command", "执行命令"],
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

  it("summarizes write_stdin timeout JSON as 执行超时 without dumping stdout", () => {
    const payload = JSON.stringify({
      status: "timeout",
      terminalSessionId: "sandbox-abc",
      sessionOpen: false,
      exitCode: 1,
      outcomeStatus: "timeout",
      stdout: "    \"high\": \"?\",\n    \"xhigh\": \"超高\",\n".repeat(40),
      formattedOutput: "huge body ".repeat(80),
      timedOut: true,
    });
    expect(terminalSandboxPresentationSummary(payload, "zh")).toBe("执行超时");
    expect(
      completedToolPresentationSummary({
        toolSummary: payload,
        toolName: "write_stdin",
        status: "failed",
        language: "zh",
      }),
    ).toBe("执行超时");
    expect(conversationToolDetailPresentation({
      value: payload,
      toolName: "write_stdin",
      language: "zh",
    })).toContain("执行超时");
    expect(conversationToolDetailPresentation({
      value: payload,
      toolName: "write_stdin",
      language: "zh",
    })).not.toContain("terminalSessionId");
    expect(conversationToolDetailPresentation({
      value: payload,
      toolName: "write_stdin",
      language: "zh",
    }).length).toBeLessThan(200);
  });

  it("does not use embedded timeout JSON as the pill subject after 执行失败", () => {
    const payload = JSON.stringify({
      status: "timeout",
      terminalSessionId: "sandbox-1",
      sessionOpen: false,
      outcomeStatus: "timeout",
      stdout: "noise",
    });
    const pills = buildCodexToolActivityPills({
      toolName: "write_stdin",
      status: "failed",
      language: "zh",
      toolSummary: `执行失败 · ${payload}`,
      timedOut: true,
    });
    expect(pills.statusKind).toBe("timeout");
    expect(pills.statusLabel).toBe("超时");
    expect(pills.subject).not.toContain("terminalSessionId");
    expect(pills.subject).not.toContain("stdout");
  });

  it("collapses multi-search mashups into a short line", () => {
    expect(
      completedToolPresentationSummary({
        toolSummary:
          "[搜索] 正则: reasoning_effort_options [搜索] 目录: C:\\tests；[搜索] 未找到匹配项 正则: foo",
        toolName: "grep_search_tool",
        language: "zh",
      }),
    ).toBe("未找到匹配");
  });

  it("exposes bounded terminal detail helper for stdout-free timeout rows", () => {
    const detail = terminalSandboxPresentationDetail(
      JSON.stringify({
        status: "timeout",
        timedOut: true,
        exitCode: 1,
        stderr: "rg: command not found",
      }),
      "zh",
    );
    expect(detail).toContain("执行超时");
    expect(detail).toContain("退出码 1");
    expect(detail).toContain("rg: command not found");
  });

  it("keeps plain cli command/stdout literal instead of collapsing to 执行失败", () => {
    expect(conversationToolDetailPresentation({
      value: "git status --short",
      toolName: "cli_tool",
      language: "zh",
    })).toBe("git status --short");
    expect(conversationToolDetailPresentation({
      value: "M web/src/components/conversation/ConversationView.tsx",
      toolName: "exec_command",
      language: "zh",
    })).toBe("M web/src/components/conversation/ConversationView.tsx");
    expect(conversationToolDetailPresentation({
      value: "python -c \"print(1)\"",
      toolName: "run_terminal_command",
      language: "zh",
    })).not.toContain("执行失败");
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

describe("normalizeToolActivityStatus / extractToolDisplayCommand", () => {
  it("maps legacy agent statuses onto the pill vocabulary", () => {
    expect(normalizeToolActivityStatus("done")).toBe("completed");
    expect(normalizeToolActivityStatus("success")).toBe("completed");
    expect(normalizeToolActivityStatus("in_progress")).toBe("running");
    expect(normalizeToolActivityStatus("error")).toBe("failed");
    expect(normalizeToolActivityStatus("fallback")).toBe("degraded");
  });

  it("extracts display commands from argument bags", () => {
    expect(extractToolDisplayCommand({ displayCommand: "pnpm test" })).toBe("pnpm test");
    expect(extractToolDisplayCommand({ command: ["git", "status"] })).toBe("git status");
    expect(extractToolDisplayCommand({ cmd: "echo hi" })).toBe("echo hi");
    expect(extractToolDisplayCommand({})).toBe("");
  });
});

describe("buildCodexToolActivityPills", () => {
  it("builds shell action/status pills with muted subject and duration", () => {
    expect(buildCodexToolActivityPills({
      toolName: "cli_tool",
      status: "completed",
      language: "zh",
      durationLabel: "12s",
      displayCommand: "pnpm test",
    })).toEqual({
      actionLabel: "执行命令",
      statusLabel: "执行完成",
      statusKind: "completed",
      subject: "pnpm test",
      durationLabel: "12s",
    });

    expect(buildCodexToolActivityPills({
      toolName: "exec_command",
      status: "running",
      language: "zh",
      displayCommand: "type README.md",
    })).toEqual({
      actionLabel: "执行命令",
      statusLabel: "运行中",
      statusKind: "running",
      subject: "type README.md",
      durationLabel: "",
    });
  });

  it("maps failure and timeout to status pills", () => {
    expect(buildCodexToolActivityPills({
      toolName: "code_symbol_tool",
      status: "failed",
      language: "zh",
    })).toMatchObject({
      actionLabel: "代码图谱",
      statusLabel: "执行失败",
      statusKind: "failed",
    });

    expect(buildCodexToolActivityPills({
      toolName: "cli_tool",
      status: "completed",
      language: "en",
      timedOut: true,
    })).toMatchObject({
      actionLabel: "Run command",
      statusLabel: "Timed out",
      statusKind: "timeout",
    });
  });
});

describe("formatCodexStyleToolActivityLine", () => {
  it("formats completed shell runs with duration like Codex", () => {
    expect(formatCodexStyleToolActivityLine({
      toolName: "cli_tool",
      status: "completed",
      language: "zh",
      durationLabel: "12s",
      displayCommand: "pnpm test",
    })).toBe("已在 12s 内运行 pnpm test");

    expect(formatCodexStyleToolActivityLine({
      toolName: "exec_command",
      status: "completed",
      language: "en",
      durationLabel: "9s",
      displayCommand: "node test.mjs",
    })).toBe("Ran node test.mjs in 9s");
  });

  it("formats edit tools as edited file lines", () => {
    expect(formatCodexStyleToolActivityLine({
      toolName: "write_file_tool",
      status: "completed",
      language: "zh",
      filePath: "src/lanA2a/TaskStore.ts",
    })).toBe("已编辑 TaskStore.ts");
  });

  it("formats timeout and failure without spinner semantics", () => {
    expect(formatCodexStyleToolActivityLine({
      toolName: "code_symbol_tool",
      status: "running",
      language: "zh",
      cellSummary: "code_symbol_tool 执行超时 (30秒)",
      timedOut: true,
    })).toContain("超时");
    expect(formatCodexStyleToolActivityLine({
      toolName: "code_symbol_tool",
      status: "failed",
      language: "zh",
    })).toBe("失败 · 代码图谱");
  });
});
