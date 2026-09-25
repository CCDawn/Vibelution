import type { CodexTranscriptCell } from "./codexTranscriptCells";
import { codexTranscriptToolRawName } from "./conversationToolActivityModel";
import type { ConversationToolPresentationLanguage } from "./conversationToolPresentation";

/**
 * Category-level tool grouping vocabulary, aligned with ZCode's assistant work
 * item switches (packages/ui conversationAssistantWorkItems.ts):
 * - "explore"  → ZCode Explore group (continuous read-only tools)
 * - "execute"  → ZCode Execute/Terminal group (shell / verification commands)
 * - "changes"  → ZCode Changes group (file writes)
 * - "cua"      → ZCode CUA group (computer/browser use)
 * - "agent"    → ZCode agent tool rows (never grouped; rendered standalone with
 *                a stable colored name, see conversationSubagentColor.ts)
 *
 * Tools that map to no category stay ungrouped plain rows — same as ZCode, where
 * only recognized tool kinds take part in grouping.
 */
export type ConversationToolCategory = "explore" | "execute" | "changes" | "cua" | "agent";

/**
 * Curated mapping over the project's tool vocabulary (the same inventory the
 * presentation label table curates). Exact names win before any token rule so
 * look-alike ids stay predictable — e.g. cli_agent_run_tool runs a command and
 * must not read as an agent spawn.
 */
const TOOL_CATEGORY_EXACT: Readonly<Record<string, ConversationToolCategory>> = {
  // Explore — read-only inspection and search.
  read_file_tool: "explore",
  glob_tool: "explore",
  grep_search_tool: "explore",
  search_code_tool: "explore",
  web_search_tool: "explore",
  batch_web_search_tool: "explore",
  web_fetch_tool: "explore",
  source_collection_context_tool: "explore",
  code_symbol_tool: "explore",
  code_graph_tool: "explore",
  explain_current_worktree_tool: "explore",
  get_core_context_tool: "explore",
  get_current_goal_tool: "explore",
  get_git_status_summary_tool: "explore",
  get_recent_changes_tool: "explore",
  conversation_log_inspect_tool: "explore",
  // Execute — commands and verification runs (ZCode Execute/Terminal).
  cli_tool: "execute",
  exec_command: "execute",
  run_terminal_command: "execute",
  shell_tool: "execute",
  bash: "execute",
  write_stdin: "execute",
  cli_agent_run_tool: "execute",
  python_lint_tool: "execute",
  run_test_for_tool: "execute",
  // Changes — file writes (ZCode Changes).
  apply_patch_tool: "changes",
  apply_diff_edit_tool: "changes",
  write_file_tool: "changes",
  source_collection_stage_writeback_tool: "changes",
  // CUA — computer/browser use.
  computer_use: "cua",
  // Agent — subagent spawn (never grouped; colored name row).
  spawn_agent_tool: "agent",
};

/**
 * Token fallback for tools added later, mirroring the curated-label table's
 * lesson: match whole underscore-delimited tokens (or explicit substrings for
 * spawn semantics), never loose substrings — "research" must not read "search".
 * Order matters: agent/cua win before write/execute so delegate-like ids are
 * not misfiled as commands.
 */
const AGENT_NAME_TOKENS = new Set(["spawn", "delegate", "subagent"]);
const AGENT_EXACT_NAMES = new Set(["agent", "task", "subagent"]);
const CUA_NAME_TOKENS = new Set(["computer", "browser"]);
const CHANGES_NAME_TOKENS = new Set(["patch", "edit", "writeback"]);
const EXECUTE_NAME_TOKENS = new Set([
  "command",
  "terminal",
  "shell",
  "bash",
  "exec",
  "stdin",
  "lint",
  "test",
  "run",
  "cmd",
]);
const EXPLORE_NAME_TOKENS = new Set([
  "read",
  "file",
  "files",
  "glob",
  "grep",
  "list",
  "search",
  "query",
  "fetch",
  "graph",
  "symbol",
  "code",
  "git",
  "log",
  "inspect",
  "status",
  "explain",
  "context",
  "goal",
  "web",
]);

function normalizeToolCategoryName(name: string) {
  return String(name ?? "").trim().toLowerCase().replace(/[\s-]+/g, "_");
}

export function conversationToolCategoryForName(name: string): ConversationToolCategory | null {
  const normalized = normalizeToolCategoryName(name);
  if (!normalized) {
    return null;
  }
  const exact = TOOL_CATEGORY_EXACT[normalized];
  if (exact) {
    return exact;
  }
  if (AGENT_EXACT_NAMES.has(normalized)) {
    return "agent";
  }
  const tokens = normalized.split("_").filter(Boolean);
  if (tokens.some((token) => AGENT_NAME_TOKENS.has(token)) || normalized.includes("spawn")) {
    return "agent";
  }
  if (tokens.some((token) => CUA_NAME_TOKENS.has(token))) {
    return "cua";
  }
  if (
    tokens.some((token) => CHANGES_NAME_TOKENS.has(token))
    || (tokens.includes("write") && tokens.includes("file"))
  ) {
    return "changes";
  }
  if (tokens.some((token) => EXECUTE_NAME_TOKENS.has(token))) {
    return "execute";
  }
  if (tokens.some((token) => EXPLORE_NAME_TOKENS.has(token))) {
    return "explore";
  }
  return null;
}

export function conversationToolCategoryForCell(
  cell: CodexTranscriptCell,
): ConversationToolCategory | null {
  return conversationToolCategoryForName(codexTranscriptToolRawName(cell));
}

export function conversationToolCategoryLabel(
  category: ConversationToolCategory,
  language: ConversationToolPresentationLanguage,
) {
  const labels: Record<ConversationToolCategory, Record<ConversationToolPresentationLanguage, string>> = {
    explore: { zh: "探索", en: "Explore" },
    execute: { zh: "执行", en: "Execute" },
    changes: { zh: "修改", en: "Changes" },
    cua: { zh: "浏览器操作", en: "Computer use" },
    agent: { zh: "子代理", en: "Agent" },
  };
  return labels[category][language];
}

const AGENT_DISPLAY_ARGUMENT_KEYS = [
  "task_type",
  "agent_name",
  "agent",
  "subagent",
  "role",
  "name",
] as const;

function firstNonEmptyString(source: Record<string, unknown>, keys: readonly string[]): string {
  for (const key of keys) {
    const value = source[key];
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
  }
  return "";
}

/**
 * Stable display name for an agent-spawning tool row: the subagent role/id the
 * model asked for. This name (not the tool id) is what gets hash-mapped onto a
 * color bucket, so the same agent always lands on the same color.
 */
export function conversationAgentDisplayName(cell: CodexTranscriptCell): string {
  const sources: Array<Record<string, unknown>> = [];
  const args = cell.toolArguments;
  if (args && typeof args === "object" && !Array.isArray(args)) {
    sources.push(args as Record<string, unknown>);
  }
  const toolCallArguments = cell.toolLifecycleModel?.toolCalls?.[0]?.arguments;
  if (toolCallArguments && typeof toolCallArguments === "object" && !Array.isArray(toolCallArguments)) {
    sources.push(toolCallArguments as Record<string, unknown>);
  }
  for (const source of sources) {
    const direct = firstNonEmptyString(source, AGENT_DISPLAY_ARGUMENT_KEYS);
    if (direct) {
      return direct;
    }
    const target = source.target;
    if (target && typeof target === "object" && !Array.isArray(target)) {
      const nested = firstNonEmptyString(target as Record<string, unknown>, AGENT_DISPLAY_ARGUMENT_KEYS);
      if (nested) {
        return nested;
      }
    }
  }
  return "";
}
