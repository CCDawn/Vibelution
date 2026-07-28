export type ConversationToolPresentationLanguage = "zh" | "en";

interface CompletedToolPresentationSummaryInput {
  toolSummary?: string;
  cellSummary?: string;
  resultPreview?: string;
  cellText?: string;
  toolName?: string;
  status?: string;
  language: ConversationToolPresentationLanguage;
}

interface ConversationToolDetailPresentationInput {
  value: string;
  toolName?: string;
  language: ConversationToolPresentationLanguage;
}

const TOOL_RESULT_SUMMARY_MAX_LENGTH = 180;
const TOOL_DETAIL_MAX_ITEMS = 6;
const LOW_VALUE_TOOL_RESULTS = new Set([
  "ok",
  "done",
  "completed",
  "success",
  "succeeded",
  "true",
  "完成",
  "已完成",
  "执行完成",
]);

function compactToolPresentationText(value: string) {
  return value.length > TOOL_RESULT_SUMMARY_MAX_LENGTH
    ? `${value.slice(0, TOOL_RESULT_SUMMARY_MAX_LENGTH - 1).trimEnd()}…`
    : value;
}

function isLowValueToolResult(value: string) {
  return LOW_VALUE_TOOL_RESULTS.has(value.trim().toLowerCase());
}

function objectRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function compactScalar(value: unknown) {
  return typeof value === "string" || typeof value === "number"
    ? String(value).replace(/\s+/g, " ").trim()
    : "";
}

function firstScalar(record: Record<string, unknown>, keys: string[]) {
  for (const key of keys) {
    const value = compactScalar(record[key]);
    if (value) {
      return value;
    }
  }
  return "";
}

function codeSymbolResultItems(parsed: Record<string, unknown>) {
  for (const key of ["results", "symbols", "files", "tests", "contexts"]) {
    const items = parsed[key];
    if (Array.isArray(items) && items.length > 0) {
      return items;
    }
  }
  return [];
}

function codeSymbolItemLine(item: unknown) {
  const record = objectRecord(item);
  if (!record) {
    return compactScalar(item);
  }
  const range = objectRecord(record.range);
  const line = firstScalar(record, ["line", "lineNumber", "startLine", "start_line"])
    || (range ? firstScalar(range, ["startLine", "start_line", "line"]) : "");
  const text = firstScalar(record, [
    "preview",
    "snippet",
    "text",
    "summary",
    "qualifiedName",
    "name",
    "path",
  ]);
  if (!text) {
    return "";
  }
  return line ? `${line.padStart(4, " ")}  ${text}` : text;
}

function codeSymbolStructuredSummary(
  parsed: Record<string, unknown>,
  language: ConversationToolPresentationLanguage,
) {
  const target = objectRecord(parsed.target);
  const file = objectRecord(parsed.file);
  const query = firstScalar(parsed, ["query"])
    || (target ? firstScalar(target, ["symbol"]) : "");
  const filePath = (target ? firstScalar(target, ["filePath", "path"]) : "")
    || (file ? firstScalar(file, ["path"]) : "");
  const items = codeSymbolResultItems(parsed);
  const count = compactScalar(parsed.count)
    || compactScalar(parsed.totalCount)
    || (items.length > 0 ? String(items.length) : "");

  if (query && filePath) {
    return language === "zh"
      ? `搜索 ${filePath} 中的 ${query}${count ? ` · ${count} 个结果` : ""}`
      : `Search ${filePath} for ${query}${count ? ` · ${count} results` : ""}`;
  }
  if (query) {
    return language === "zh"
      ? `搜索 ${query}${count ? ` · ${count} 个结果` : ""}`
      : `Search ${query}${count ? ` · ${count} results` : ""}`;
  }
  if (filePath) {
    return language === "zh" ? `检查 ${filePath}` : `Inspect ${filePath}`;
  }
  return "";
}

function codeSymbolStructuredDetail(
  parsed: Record<string, unknown>,
  language: ConversationToolPresentationLanguage,
) {
  const items = codeSymbolResultItems(parsed);
  const lines = items
    .slice(0, TOOL_DETAIL_MAX_ITEMS)
    .map(codeSymbolItemLine)
    .filter(Boolean);
  if (lines.length > 0) {
    const omitted = Math.max(0, items.length - lines.length);
    if (omitted > 0) {
      lines.push(language === "zh" ? `… 另有 ${omitted} 个结果` : `… ${omitted} more results`);
    }
    return lines.join("\n");
  }
  const snippet = compactScalar(parsed.snippet);
  if (snippet) {
    return snippet;
  }
  return firstScalar(parsed, ["message", "summary", "error"]);
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
        if (String(toolName ?? "").trim().toLowerCase() === "code_symbol_tool") {
          const codeSummary = codeSymbolStructuredSummary(parsed, language);
          if (codeSummary) {
            return compactToolPresentationText(codeSummary);
          }
        }
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
      if (normalized.startsWith("[") && !/^\[\s*[{"]/.test(normalized)) {
        return isLowValueToolResult(normalized)
          ? ""
          : compactToolPresentationText(normalized);
      }
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
  status,
  language,
}: CompletedToolPresentationSummaryInput) {
  const normalizedToolName = String(toolName ?? "").trim().toLowerCase();
  const normalizedStatus = String(status ?? "").trim().toLowerCase();
  const terminalTool = normalizedToolName === "exec_command"
    || normalizedToolName === "write_stdin";
  if (terminalTool && (normalizedStatus === "running" || normalizedStatus === "pending")) {
    return language === "zh" ? "正在运行" : "Running";
  }
  if (terminalTool && normalizedStatus === "completed") {
    return "";
  }
  const candidates = [toolSummary, cellSummary, resultPreview, cellText];
  for (const candidate of candidates) {
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

export function conversationToolDetailPresentation({
  value,
  toolName,
  language,
}: ConversationToolDetailPresentationInput) {
  const normalized = String(value ?? "").trim();
  if (!normalized) {
    return "";
  }
  if (String(toolName ?? "").trim().toLowerCase() !== "code_symbol_tool" || !normalized.startsWith("{")) {
    return normalized;
  }
  try {
    const parsed = JSON.parse(normalized) as Record<string, unknown>;
    return codeSymbolStructuredDetail(parsed, language)
      || codeSymbolStructuredSummary(parsed, language)
      || (language === "zh" ? "已返回结构化结果" : "Structured result returned");
  } catch {
    return normalized;
  }
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
    exec_command: { zh: "运行命令", en: "Run command" },
    write_stdin: { zh: "写入终端", en: "Write to terminal" },
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
    source_collection_context_tool: { zh: "读取资料上下文", en: "Read source context" },
    source_collection_stage_writeback_tool: { zh: "资料提炼回写", en: "Write source extraction" },
    get_git_status_summary_tool: { zh: "Git 状态", en: "Git status" },
    get_recent_changes_tool: { zh: "查看最近改动", en: "Recent changes" },
    conversation_log_inspect_tool: {
      zh: "检查会话日志",
      en: "Inspect conversation log",
    },
    apply_patch_tool: { zh: "修改文件", en: "Apply patch" },
    apply_diff_edit_tool: { zh: "修改文件", en: "Edit file" },
    write_file_tool: { zh: "写入文件", en: "Write file" },
    python_lint_tool: { zh: "代码检查", en: "Lint" },
    run_test_for_tool: { zh: "运行测试", en: "Run tests" },
    computer_use: { zh: "浏览器操作", en: "Computer use" },
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
