export type ConversationToolPresentationLanguage = "zh" | "en";

interface CompletedToolPresentationSummaryInput {
  toolSummary?: string;
  cellSummary?: string;
  resultPreview?: string;
  cellText?: string;
  toolName?: string;
  language: ConversationToolPresentationLanguage;
}

const TOOL_RESULT_SUMMARY_MAX_LENGTH = 180;
const LOW_VALUE_TOOL_RESULTS = new Set([
  "ok",
  "done",
  "completed",
  "success",
  "succeeded",
  "true",
]);

function compactToolPresentationText(value: string) {
  return value.length > TOOL_RESULT_SUMMARY_MAX_LENGTH
    ? `${value.slice(0, TOOL_RESULT_SUMMARY_MAX_LENGTH - 1).trimEnd()}…`
    : value;
}

function isLowValueToolResult(value: string) {
  return LOW_VALUE_TOOL_RESULTS.has(value.trim().toLowerCase());
}

function conversationLogInspectTarget(value: string) {
  if (!value.startsWith("{")) {
    return "";
  }
  try {
    const parsed = JSON.parse(value) as Record<string, unknown>;
    const query = typeof parsed.query === "string" ? parsed.query.trim() : "";
    if (query) {
      return compactToolPresentationText(query);
    }
    const logPath = typeof parsed.logPath === "string" ? parsed.logPath.trim() : "";
    if (!logPath) {
      return "";
    }
    const fileName = logPath.split(/[\\/]/).filter(Boolean).at(-1) ?? logPath;
    return compactToolPresentationText(fileName);
  } catch {
    return "";
  }
}

function extractTruncatedStructuredSummary(value: string) {
  const match = value.match(
    /"(?:dirty_summary|message|summary|result|status)"\s*:\s*"((?:\\.|[^"\\])*)/i,
  );
  if (!match?.[1]) {
    return "";
  }
  try {
    return JSON.parse(`"${match[1]}"`) as string;
  } catch {
    return match[1]
      .replace(/\\"/g, '"')
      .replace(/\\n/g, " ")
      .replace(/\\t/g, " ")
      .trim();
  }
}

function compactToolPresentationCandidate(
  value: string | undefined,
  toolName: string | undefined,
  language: ConversationToolPresentationLanguage,
) {
  const normalized = String(value ?? "").replace(/\s+/g, " ").trim();
  if (!normalized || normalized === String(toolName ?? "").trim()) {
    return "";
  }
  if (String(toolName ?? "").trim().toLowerCase() === "conversation_log_inspect_tool") {
    const target = conversationLogInspectTarget(normalized);
    if (target) {
      return target;
    }
  }
  if (normalized.startsWith("{") || normalized.startsWith("[")) {
    try {
      const parsed = JSON.parse(normalized) as Record<string, unknown>;
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        const semantic = [
          parsed.dirty_summary,
          parsed.message,
          parsed.summary,
          parsed.result,
          parsed.status,
        ].find((item) => typeof item === "string" && item.trim());
        if (typeof semantic === "string") {
          return isLowValueToolResult(semantic)
            ? ""
            : compactToolPresentationText(semantic);
        }
      }
      return language === "zh"
        ? "已返回结构化结果"
        : "Structured result returned";
    } catch {
      const semantic = extractTruncatedStructuredSummary(normalized);
      if (semantic) {
        return isLowValueToolResult(semantic)
          ? ""
          : compactToolPresentationText(semantic);
      }
      return language === "zh"
        ? "已返回结构化结果"
        : "Structured result returned";
    }
  }
  return isLowValueToolResult(normalized)
    ? ""
    : compactToolPresentationText(normalized);
}

export function completedToolPresentationSummary({
  toolSummary,
  cellSummary,
  resultPreview,
  cellText,
  toolName,
  language,
}: CompletedToolPresentationSummaryInput) {
  for (const candidate of [
    toolSummary,
    cellSummary,
    resultPreview,
    cellText,
  ]) {
    const summary = compactToolPresentationCandidate(
      candidate,
      toolName,
      language,
    );
    if (summary) {
      return summary;
    }
  }
  return "";
}

export function conversationToolPresentationLabel(
  name: string,
  language: ConversationToolPresentationLanguage,
) {
  const normalized = String(name ?? "").trim();
  const lower = normalized.toLowerCase();
  const labels: Record<
    string,
    Record<ConversationToolPresentationLanguage, string>
  > = {
    cli_tool: { zh: "命令", en: "Command" },
    grep_search_tool: { zh: "搜索", en: "Search" },
    read_file_tool: { zh: "读取文件", en: "Read file" },
    glob_tool: { zh: "列出文件", en: "List files" },
    code_symbol_tool: { zh: "代码图谱", en: "Code graph" },
    explain_current_worktree_tool: {
      zh: "工作树详情",
      en: "Worktree details",
    },
    get_core_context_tool: { zh: "核心上下文", en: "Core context" },
    get_current_goal_tool: { zh: "当前目标", en: "Current goal" },
    search_code_tool: { zh: "搜索代码", en: "Search code" },
    get_git_status_summary_tool: { zh: "Git 状态", en: "Git status" },
    get_recent_changes_tool: { zh: "查看最近改动", en: "Recent changes" },
    conversation_log_inspect_tool: {
      zh: "检查会话日志",
      en: "Inspect conversation log",
    },
  };
  if (labels[lower]) {
    return labels[lower][language];
  }
  if (lower.includes("read") || lower.includes("file")) {
    return language === "zh" ? "读取" : "Read";
  }
  if (lower.includes("search")) {
    return language === "zh" ? "搜索" : "Search";
  }
  return normalized || (language === "zh" ? "工具调用" : "Tool call");
}
