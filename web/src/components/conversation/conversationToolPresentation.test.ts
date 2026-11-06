import { describe, expect, it } from "vitest";

import {
  buildCodexToolActivityPills,
  completedToolPresentationSummary,
  conversationToolDetailPresentation,
  conversationToolPresentationLabel,
  extractToolDisplayCommand,
  formatCodexStyleToolActivityLine,
  normalizeToolActivityStatus,
  subjectFromToolArguments,
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

  it("uses the same normalized assistant action labels for presentation and activity rows", () => {
    expect(conversationToolPresentationLabel("personal_assistant_action_tool", "zh", { action: "SOURCE-SEARCH" }))
      .toBe("搜索源码");
    expect(conversationToolPresentationLabel("personal_assistant_manage_tool", "en", [{ action: "session_create" }]))
      .toBe("Create session");
    expect(conversationToolPresentationLabel("personal_assistant_manage_tool", "en", { action: "future_action" }))
      .toBe("Run assistant action");
    expect(conversationToolPresentationLabel("read_file_tool", "zh", { action: "session_create" }))
      .toBe("读取文件");
  });

  it("matches whole name tokens so research tools are not read as search", () => {
    // "research" contains the substring "search", which made every research tool
    // read "搜索" — including the one that applies a proposal.
    expect(conversationToolPresentationLabel("research_proposal_apply_tool", "zh"))
      .toBe("Apply Research Proposal");
    expect(conversationToolPresentationLabel("research_agent_creation_proposal_tool", "zh"))
      .not.toBe("搜索");
    // Genuine search tools keep the short label; the row's subject names the target.
    expect(conversationToolPresentationLabel("news_search_tool", "zh")).toBe("搜索");
    expect(conversationToolPresentationLabel("history_search_tool", "zh")).toBe("搜索");
  });

  it.each([
    ["task_create_tool", "Create Task"],
    ["session_delete_tool", "Delete Session"],
    ["virtual_human_diary_tool", "Virtual Human Diary"],
    ["knowledge_governance_plan_tool", "Knowledge Governance Plan"],
    ["get_session_files_tool", "Get Session Files"],
    ["trigger_self_restart_tool", "Trigger Self Restart"],
    ["cli_agent_run_tool", "Run CLI Agent"],
    ["github_project_library_clone_tool", "Clone GitHub Project Library"],
  ])("derives a readable label for the unlabelled tool %s", (toolName, expected) => {
    expect(conversationToolPresentationLabel(toolName, "en")).toBe(expected);
  });

  it("never shows a raw tool identifier, for either language", () => {
    const catalogTools = [
      "agent_inbox_list_tool", "agent_tool_permission_request_tool", "append_episodic_memory_tool",
      "challenge_cup_experiment_writeback_tool", "close_evolution_transaction_tool",
      "commit_compressed_memory_tool", "computer_use_session_tool", "create_child_session_tool",
      "get_evolution_fitness_tool", "history_timeline_tool", "knowledge_steward_workbench_tool",
      "list_workspace_debris_tool", "open_evolution_transaction_tool", "record_learning_tool",
      "session_reference_query_tool", "supersede_personal_memory_tool", "task_output_tool",
      "unified_memory_search_tool", "update_diagnosis_rules_tool", "virtual_human_schedule_tool",
    ];
    for (const toolName of catalogTools) {
      expect(conversationToolPresentationLabel(toolName, "zh")).not.toBe(toolName);
      expect(conversationToolPresentationLabel(toolName, "en")).not.toBe(toolName);
    }
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

  it("maps cancelled/stopped onto the neutral terminal family and unknown onto failure", () => {
    expect(normalizeToolActivityStatus("cancelled")).toBe("cancelled");
    expect(normalizeToolActivityStatus("stopped")).toBe("cancelled");
    expect(normalizeToolActivityStatus("denied")).toBe("cancelled");
    // 宁红不绿: unknown vocabulary never silently resolves completed.
    expect(normalizeToolActivityStatus("mystery_status")).toBe("failed");
  });

  it("extracts display commands from argument bags", () => {
    expect(extractToolDisplayCommand({ displayCommand: "pnpm test" })).toBe("pnpm test");
    expect(extractToolDisplayCommand({ command: ["git", "status"] })).toBe("git status");
    expect(extractToolDisplayCommand({ cmd: "echo hi" })).toBe("echo hi");
    expect(extractToolDisplayCommand({})).toBe("");
  });

  it("strips ANSI artifacts from terminal payload text at the presentation boundary", () => {
    expect(completedToolPresentationSummary({
      toolSummary: "生成计划[1m加粗[0m正文",
      toolName: "exec_command",
      status: "completed",
      language: "zh",
    })).not.toContain("[1m");

    const pills = buildCodexToolActivityPills({
      toolName: "exec_command",
      status: "running",
      language: "zh",
      displayCommand: "pnpm test[1m",
      toolSummary: "运行[0m中",
    });
    expect(pills.subject).not.toContain("[1m");
    expect(pills.subject).not.toContain("[0m");
    expect(pills.statusLabel).not.toContain("[0m");
  });
});

describe("buildCodexToolActivityPills", () => {
  it("keeps a completed read identifiable by file instead of replacing its target with source output", () => {
    expect(buildCodexToolActivityPills({ toolName: "read_file_tool", status: "completed", language: "zh",
      toolArguments: { path: "src/alpha.ts" }, resultPreview: "export const paintState = { phase: 'idle' };" }))
      .toMatchObject({ subject: "alpha.ts", statusKind: "completed" });
    expect(buildCodexToolActivityPills({ toolName: "personal_assistant_action_tool", status: "completed", language: "zh",
      toolArguments: { action: "source_read", parameters: { path: "src/beta.ts" } }, resultPreview: "source text preview" }))
      .toMatchObject({ subject: "beta.ts", statusKind: "completed" });
  });
  it("names a running search by its term instead of its directory scope", () => {
    for (const toolName of ["grep_search_tool", "search_code_tool", "query_tool"]) {
      expect(buildCodexToolActivityPills({ toolName, status: "running", language: "zh",
        toolArguments: { path: ".", pattern: "paintState" } }).subject).toBe("paintState");
    }
    expect(subjectFromToolArguments({ toolName: "read_file_tool", language: "zh",
      toolArguments: { path: "src/alpha.ts", pattern: "paintState" } })).toBe("alpha.ts");
    for (const toolName of ["personal_assistant_action_tool", "personal_assistant_manage_tool"]) {
      expect(buildCodexToolActivityPills({ toolName, status: "running", language: "zh",
        toolArguments: { action: "source_search", path: ".", query: "paintState" } }))
        .toMatchObject({ actionLabel: "搜索源码", subject: "paintState" });
    }
  });

  it.each(["personal_assistant_action_tool", "personal_assistant_manage_tool"])(
    "names actual source action parameter envelopes for %s",
    (toolName) => {
      for (const path of [
        "web/src/components/conversation/grouping.ts",
        "web/src/components/conversation/conversationToolPresentation.ts",
      ]) {
        expect(buildCodexToolActivityPills({
          toolName, status: "running", language: "zh",
          toolArguments: {
            action: "source_read",
            parameters: { path, project_id: "project-a", line: 10, max_lines: 30 },
          },
        })).toMatchObject({ actionLabel: "读取源码", subject: path.split("/").at(-1) });
      }
      for (const search of [{ query: "paintState" }, { pattern: "paintState" }]) {
        expect(buildCodexToolActivityPills({
          toolName, status: "running", language: "zh",
          toolArguments: { action: "source_search", path: ".", parameters: { ...search, path: "." } },
        })).toMatchObject({ actionLabel: "搜索源码", subject: "paintState" });
      }
    },
  );

  it("preserves top-level subjects before matching assistant parameter fields", () => {
    expect(subjectFromToolArguments({
      toolName: "personal_assistant_action_tool", language: "zh",
      toolArguments: { action: "source_read", path: "src/outer.ts", parameters: { path: "src/inner.ts" } },
    })).toBe("outer.ts");
    expect(subjectFromToolArguments({
      toolName: "personal_assistant_action_tool", language: "zh",
      toolArguments: { action: "source_read", target: { path: "src/outer-target.ts" }, parameters: { path: "src/inner.ts" } },
    })).toBe("outer-target.ts");
    expect(subjectFromToolArguments({
      toolName: "personal_assistant_manage_tool", language: "zh",
      toolArguments: { action: "source_search", query: "outerTerm", parameters: { query: "innerTerm", path: "." } },
    })).toBe("outerTerm");
    expect(subjectFromToolArguments({
      toolName: "personal_assistant_manage_tool", language: "en",
      toolArguments: { action: "session_get", session_id: "outer-session", parameters: { session_id: "inner-session", project_id: "project-a" } },
    })).toBe("Session outer-session · Project project-a");
  });

  it("opens parameter envelopes only for recognized assistant tools and actions", () => {
    for (const toolName of ["unknown_tool", "read_file_tool", undefined]) {
      expect(subjectFromToolArguments({
        toolName, language: "zh",
        toolArguments: { action: "source_read", parameters: { path: "private.ts" } },
      })).toBe("");
    }
    expect(subjectFromToolArguments({
      toolName: "personal_assistant_action_tool", language: "zh",
      toolArguments: { action: "future_unknown_action", parameters: { query: "private query", path: "private.ts" } },
    })).toBe("");
  });

  it("keeps assistant envelope extraction shallow and limited to subject fields", () => {
    const privateFields = {
      prompt: "private complete prompt",
      body: "private message body",
      content: "private document content",
      api_key: "private-api-key",
      credential_token: "private-credential-token",
      arbitrary: { path: "private-nested.ts" },
      parameters: { path: "private-recursive.ts" },
    };
    expect(subjectFromToolArguments({
      toolName: "personal_assistant_action_tool", language: "zh",
      toolArguments: { action: "source_read", parameters: privateFields },
    })).toBe("");
    expect(subjectFromToolArguments({
      toolName: "personal_assistant_manage_tool", language: "zh",
      toolArguments: { action: "source_read", parameters: { ...privateFields, path: "src/public.ts" } },
    })).toBe("public.ts");
    for (const parameters of [[{ path: "private-array.ts" }], JSON.stringify({ path: "private-json.ts" })]) {
      expect(subjectFromToolArguments({
        toolName: "personal_assistant_action_tool", language: "zh",
        toolArguments: { action: "source_read", parameters },
      })).toBe("");
    }
  });

  it("names assistant entity targets without displaying prompts, bodies or credentials", () => {
    const toolArguments = {
      action: "session_update",
      project_id: "project-alpha",
      session_id: "session-42",
      prompt: "private complete prompt",
      body: "private message body",
      content: "private document content",
      api_key: "private-api-key",
      credential_token: "private-credential-token",
      parameters: { token: "private-token" },
    };
    expect(buildCodexToolActivityPills({
      toolName: "personal_assistant_manage_tool",
      status: "running",
      language: "zh",
      toolArguments,
    })).toMatchObject({
      actionLabel: "修改会话",
      subject: "会话 session-42 · 项目 project-alpha",
      statusKind: "running",
    });
    expect(subjectFromToolArguments({ toolArguments, language: "en" }))
      .toBe("Session session-42 · Project project-alpha");
    expect(subjectFromToolArguments({ toolArguments: { prompt: toolArguments.prompt, content: toolArguments.content, api_key: toolArguments.api_key }, language: "zh" }))
      .toBe("");
  });

  it("supports bounded direct and nested entity ids while preserving specific source targets", () => {
    expect(subjectFromToolArguments({ toolArguments: { agentId: "reviewer", projectId: "project-a" }, language: "zh" }))
      .toBe("Agent reviewer · 项目 project-a");
    expect(subjectFromToolArguments({ toolArguments: { target: { team_id: "team-a", flow_id: "flow-b" } }, language: "en" }))
      .toBe("Team team-a · Flow flow-b");
    expect(subjectFromToolArguments({ toolArguments: { project_id: "p".repeat(200) }, language: "zh" }))
      .toHaveLength(72);
    expect(subjectFromToolArguments({ toolArguments: { path: "src/agent.ts", agent_id: "reviewer" }, language: "zh" }))
      .toBe("agent.ts");
    expect(subjectFromToolArguments({ toolArguments: { query: "session state", project_id: "project-a" }, language: "en" }))
      .toBe("session state");
    expect(subjectFromToolArguments({ toolArguments: { projectId: { prompt: "private" }, sessionId: ["private"] }, language: "en" }))
      .toBe("");
  });

  it.each(["personal_assistant_action_tool", "personal_assistant_manage_tool"])(
    "names the specific assistant action for %s while preserving status and target",
    (toolName) => {
      expect(buildCodexToolActivityPills({
        toolName,
        status: "running",
        language: "zh",
        toolArguments: { action: "source_read", path: "README.md" },
      })).toMatchObject({ actionLabel: "读取源码", statusKind: "running", subject: "README.md" });
      expect(buildCodexToolActivityPills({
        toolName, status: "completed", language: "zh", resultPreview: "已完成。",
        toolArguments: { action: "source_read", path: "README.md" },
      })).toMatchObject({ actionLabel: "读取源码", statusKind: "completed", subject: "README.md" });
      expect(buildCodexToolActivityPills({
        toolName,
        status: "failed",
        language: "en",
        toolArguments: { action: "session_create" },
      })).toMatchObject({ actionLabel: "Create session", statusKind: "failed" });
    },
  );

  it("keeps unknown assistant actions and unrelated tool actions on their generic fallback", () => {
    expect(buildCodexToolActivityPills({
      toolName: "personal_assistant_action_tool", status: "completed", language: "zh",
      toolArguments: { action: "future_unknown_action" },
    }).actionLabel).toBe("处理助理请求");
    expect(buildCodexToolActivityPills({
      toolName: "personal_assistant_manage_tool", status: "completed", language: "en",
    }).actionLabel).toBe("Run assistant action");
    expect(buildCodexToolActivityPills({
      toolName: "read_file_tool", status: "completed", language: "zh",
      toolArguments: { action: "session_create" },
    }).actionLabel).toBe("读取文件");
  });

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

  it("renders cancelled/stopped as a grey neutral chip instead of red or green", () => {
    expect(buildCodexToolActivityPills({
      toolName: "cli_tool",
      status: "cancelled",
      language: "zh",
      displayCommand: "pnpm test",
    })).toMatchObject({
      statusLabel: "已取消",
      statusKind: "cancelled",
    });
    expect(buildCodexToolActivityPills({
      toolName: "cli_tool",
      status: "stopped",
      language: "en",
    })).toMatchObject({
      statusLabel: "Stopped",
      statusKind: "cancelled",
    });
  });

  it("renders unknown statuses as failure pills (宁红不绿)", () => {
    expect(buildCodexToolActivityPills({
      toolName: "code_symbol_tool",
      status: "mystery_status",
      language: "zh",
    })).toMatchObject({
      statusLabel: "执行失败",
      statusKind: "failed",
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
