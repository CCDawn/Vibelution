import { describe, expect, it } from "vitest";

import type { CodexTranscriptCell } from "./codexTranscriptCells";
import {
  conversationAgentDisplayName,
  conversationToolCategoryForCell,
  conversationToolCategoryForName,
  conversationToolCategoryLabel,
} from "./conversationToolCategory";

function cellWithToolName(title: string, toolArguments?: Record<string, unknown>): CodexTranscriptCell {
  return {
    id: `cell-${title}`,
    kind: "tool_call",
    messageId: "message-1",
    status: "completed",
    tone: "neutral",
    title,
    summary: "",
    toolArguments,
  };
}

describe("conversationToolCategory", () => {
  it("maps the curated tool vocabulary onto ZCode-aligned categories", () => {
    // Explore — read-only inspection and search.
    for (const name of [
      "read_file_tool",
      "glob_tool",
      "grep_search_tool",
      "search_code_tool",
      "web_search_tool",
      "batch_web_search_tool",
      "web_fetch_tool",
      "source_collection_context_tool",
      "code_symbol_tool",
      "explain_current_worktree_tool",
      "get_git_status_summary_tool",
      "conversation_log_inspect_tool",
    ]) {
      expect(conversationToolCategoryForName(name), name).toBe("explore");
    }
    // Execute — commands and verification runs.
    for (const name of [
      "cli_tool",
      "exec_command",
      "run_terminal_command",
      "shell_tool",
      "bash",
      "write_stdin",
      "cli_agent_run_tool",
      "python_lint_tool",
      "run_test_for_tool",
    ]) {
      expect(conversationToolCategoryForName(name), name).toBe("execute");
    }
    // Changes — file writes.
    for (const name of [
      "apply_patch_tool",
      "apply_diff_edit_tool",
      "write_file_tool",
      "source_collection_stage_writeback_tool",
    ]) {
      expect(conversationToolCategoryForName(name), name).toBe("changes");
    }
    expect(conversationToolCategoryForName("computer_use")).toBe("cua");
    expect(conversationToolCategoryForName("spawn_agent_tool")).toBe("agent");
  });

  it("never misfiles look-alike ids: command runners are not agent spawns", () => {
    expect(conversationToolCategoryForName("cli_agent_run_tool")).toBe("execute");
    expect(conversationToolCategoryForName("write_stdin")).toBe("execute");
  });

  it("classifies unseen tools with whole-token fallbacks and leaves the rest ungrouped", () => {
    expect(conversationToolCategoryForName("agent_spawn_helper_tool")).toBe("agent");
    expect(conversationToolCategoryForName("delegate_review_tool")).toBe("agent");
    expect(conversationToolCategoryForName("subagent_dispatch_tool")).toBe("agent");
    expect(conversationToolCategoryForName("computer_use_v2")).toBe("cua");
    expect(conversationToolCategoryForName("browser_snapshot_tool")).toBe("cua");
    expect(conversationToolCategoryForName("apply_config_patch_tool")).toBe("changes");
    expect(conversationToolCategoryForName("get_user_files_tool")).toBe("explore");
    // Token equality, not substrings: research is not search; task_create is not an agent.
    expect(conversationToolCategoryForName("research_proposal_apply_tool")).toBeNull();
    expect(conversationToolCategoryForName("task_create_tool")).toBeNull();
    expect(conversationToolCategoryForName("virtual_human_diary_tool")).toBeNull();
    expect(conversationToolCategoryForName("")).toBeNull();
    expect(conversationToolCategoryForName("   ")).toBeNull();
  });

  it("resolves the category from the transcript cell identity", () => {
    expect(conversationToolCategoryForCell(cellWithToolName("grep_search_tool"))).toBe("explore");
    expect(conversationToolCategoryForCell(cellWithToolName("unknown_thing_tool"))).toBeNull();
  });

  it("labels categories for both presentation languages", () => {
    expect(conversationToolCategoryLabel("explore", "zh")).toBe("探索");
    expect(conversationToolCategoryLabel("explore", "en")).toBe("Explore");
    expect(conversationToolCategoryLabel("execute", "zh")).toBe("执行");
    expect(conversationToolCategoryLabel("execute", "en")).toBe("Execute");
    expect(conversationToolCategoryLabel("changes", "zh")).toBe("修改");
    expect(conversationToolCategoryLabel("changes", "en")).toBe("Changes");
    expect(conversationToolCategoryLabel("cua", "zh")).toBe("浏览器操作");
    expect(conversationToolCategoryLabel("cua", "en")).toBe("Computer use");
  });

  it("extracts the stable subagent display name from spawn arguments", () => {
    expect(conversationAgentDisplayName(cellWithToolName("spawn_agent_tool", { task_type: "research" })))
      .toBe("research");
    const lifecycleCell = cellWithToolName("spawn_agent_tool");
    lifecycleCell.toolArguments = undefined;
    lifecycleCell.toolLifecycleModel = {
      toolCalls: [
        {
          toolCallId: "call-1",
          rawOperationId: "op-1",
          status: "completed",
          title: "spawn_agent_tool",
          rawToolName: "spawn_agent_tool",
          runtimeKind: "tool",
          arguments: { role: "inspect" },
        },
      ],
      terminalOperations: [],
      terminalSessions: [],
      modelObservations: [],
    };
    expect(conversationAgentDisplayName(lifecycleCell)).toBe("inspect");
    const nestedCell = cellWithToolName("spawn_agent_tool", { target: { name: "reviewer" } });
    expect(conversationAgentDisplayName(nestedCell)).toBe("reviewer");
    expect(conversationAgentDisplayName(cellWithToolName("spawn_agent_tool", {}))).toBe("");
    expect(conversationAgentDisplayName(cellWithToolName("read_file_tool"))).toBe("");
  });
});
