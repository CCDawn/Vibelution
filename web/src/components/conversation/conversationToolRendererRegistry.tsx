import {
  BadgeCheck,
  Bot,
  FileSearch,
  GitBranch,
  Network,
  ListFilter,
  MonitorSmartphone,
  PencilLine,
  Search,
  TerminalSquare,
  Wrench,
  type LucideIcon,
} from "lucide-react";

import { assistantActionKindForTool, type AssistantActionKind } from "./assistantActionLabels";
import {
  conversationToolPresentationLabel,
  type ConversationToolPresentationLanguage,
} from "./conversationToolPresentation";

export type ConversationToolRendererFamily =
  | "git"
  | "code"
  | "files"
  | "search"
  | "command"
  | "edit"
  | "verify"
  | "conversation"
  | "generic";

export type ConversationToolRendererDescriptor = {
  family: ConversationToolRendererFamily;
  icon: LucideIcon;
  groupLabel: Record<ConversationToolPresentationLanguage, string>;
};

const TOOL_RENDERER_REGISTRY: Record<ConversationToolRendererFamily, ConversationToolRendererDescriptor> = {
  git: {
    family: "git",
    icon: GitBranch,
    groupLabel: { zh: "Git 检查", en: "Git checks" },
  },
  code: {
    family: "code",
    icon: Network,
    groupLabel: { zh: "代码分析", en: "Code analysis" },
  },
  files: {
    family: "files",
    icon: FileSearch,
    groupLabel: { zh: "文件浏览", en: "File browsing" },
  },
  search: {
    family: "search",
    icon: Search,
    groupLabel: { zh: "搜索", en: "Search" },
  },
  command: {
    family: "command",
    icon: TerminalSquare,
    groupLabel: { zh: "命令执行", en: "Commands" },
  },
  edit: {
    family: "edit",
    icon: PencilLine,
    groupLabel: { zh: "修改文件", en: "File changes" },
  },
  verify: {
    family: "verify",
    icon: BadgeCheck,
    groupLabel: { zh: "验证", en: "Verification" },
  },
  conversation: {
    family: "conversation",
    icon: Wrench,
    groupLabel: { zh: "会话诊断", en: "Conversation diagnostics" },
  },
  generic: {
    family: "generic",
    icon: Wrench,
    groupLabel: { zh: "工具调用", en: "Tool activity" },
  },
};

const ASSISTANT_ACTION_RENDERER_FAMILIES: Record<AssistantActionKind, ConversationToolRendererFamily> = {
  inspect: "conversation",
  source: "files",
  search: "search",
  change: "edit",
  dispatch: "conversation",
  browser: "generic",
  execute: "command",
  verify: "verify",
};

const ASSISTANT_ACTION_RENDERERS: Partial<Record<AssistantActionKind, ConversationToolRendererDescriptor>> = {
  inspect: { family: "conversation", icon: ListFilter, groupLabel: { zh: "平台查询", en: "Platform queries" } },
  dispatch: { family: "conversation", icon: Bot, groupLabel: { zh: "任务派遣", en: "Delegation" } },
  browser: { family: "generic", icon: MonitorSmartphone, groupLabel: { zh: "浏览器操作", en: "Browser actions" } },
  change: { family: "edit", icon: PencilLine, groupLabel: { zh: "修改", en: "Changes" } },
};

function familyForToolName(name: string, toolArguments?: unknown): ConversationToolRendererFamily {
  const actionKind = assistantActionKindForTool(name, toolArguments);
  if (actionKind) {
    return ASSISTANT_ACTION_RENDERER_FAMILIES[actionKind];
  }
  const normalized = name.trim().toLowerCase();
  if (["get_git_status_summary_tool", "get_recent_changes_tool", "explain_current_worktree_tool"].includes(normalized)) {
    return "git";
  }
  if (normalized === "code_symbol_tool" || normalized.includes("symbol") || normalized.includes("graph")) {
    return "code";
  }
  if (
    ["apply_patch_tool", "apply_diff_edit_tool", "write_file_tool"].includes(normalized)
    || normalized === "source_collection_stage_writeback_tool"
    || normalized.includes("patch")
    || normalized.includes("edit")
  ) {
    return "edit";
  }
  if (
    ["read_file_tool", "glob_tool", "web_fetch_tool", "source_collection_context_tool"].includes(normalized)
    || normalized.includes("file")
  ) {
    return "files";
  }
  if (
    ["grep_search_tool", "search_code_tool", "web_search_tool"].includes(normalized)
    || normalized.includes("search")
  ) {
    return "search";
  }
  if (
    ["python_lint_tool", "run_test_for_tool"].includes(normalized)
    || normalized.includes("lint")
    || normalized.includes("test")
  ) {
    return "verify";
  }
  if (
    ["cli_agent_run_tool", "cli_tool", "exec_command", "write_stdin"].includes(normalized)
    || normalized.includes("command")
    || normalized.includes("terminal")
  ) {
    return "command";
  }
  if (normalized === "conversation_log_inspect_tool" || normalized.includes("conversation_log")) {
    return "conversation";
  }
  return "generic";
}

export function conversationToolRendererFor(name: string, toolArguments?: unknown) {
  const kind = assistantActionKindForTool(name, toolArguments);
  const actionRenderer = kind ? ASSISTANT_ACTION_RENDERERS[kind] : undefined;
  if (actionRenderer) return actionRenderer;
  return TOOL_RENDERER_REGISTRY[familyForToolName(name, toolArguments)];
}

export function conversationToolRendererForPresentationLabel(
  label: string,
  language: ConversationToolPresentationLanguage,
) {
  const groupDescriptor = Object.values(TOOL_RENDERER_REGISTRY)
    .find((descriptor) => descriptor.groupLabel[language] === label);
  if (groupDescriptor) {
    return groupDescriptor;
  }
  const knownFamilies: Array<[ConversationToolRendererFamily, string]> = [
    ["git", "get_git_status_summary_tool"],
    ["code", "code_symbol_tool"],
    ["files", "read_file_tool"],
    ["search", "search_code_tool"],
    ["command", "cli_tool"],
    ["edit", "apply_patch_tool"],
    ["verify", "run_test_for_tool"],
    ["conversation", "conversation_log_inspect_tool"],
  ];
  const matched = knownFamilies.find(([, toolName]) => conversationToolPresentationLabel(toolName, language) === label);
  return matched ? TOOL_RENDERER_REGISTRY[matched[0]] : TOOL_RENDERER_REGISTRY.generic;
}

export function conversationToolRendererLabel(
  name: string,
  language: ConversationToolPresentationLanguage,
  toolArguments?: unknown,
) {
  return conversationToolPresentationLabel(name, language, toolArguments);
}
