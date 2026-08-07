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

/** Terminal sandbox payload: status / stdout / timeout JSON dumped into process rows. */
function isTerminalSandboxPayload(parsed: Record<string, unknown>) {
  const keys = Object.keys(parsed);
  const hasStatus = "status" in parsed || "outcomeStatus" in parsed;
  const hasTerminalShape = keys.some((key) =>
    [
      "terminalSessionId",
      "sessionOpen",
      "formattedOutput",
      "stdout",
      "stderr",
      "exitCode",
      "timedOut",
      "outcomeStatus",
    ].includes(key)
  );
  return hasStatus && hasTerminalShape;
}

function extractJsonObject(value: string): Record<string, unknown> | null {
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  const tryParse = (text: string) => {
    try {
      const parsed = JSON.parse(text) as unknown;
      return objectRecord(parsed);
    } catch {
      return null;
    }
  };
  const direct = tryParse(trimmed);
  if (direct) {
    return direct;
  }
  // Human prefix before JSON: "执行失败 · {\"status\":...}" or search mashups.
  const start = trimmed.indexOf("{");
  const end = trimmed.lastIndexOf("}");
  if (start >= 0 && end > start) {
    return tryParse(trimmed.slice(start, end + 1));
  }
  return null;
}

function firstTextLine(value: unknown, maxLen = 96) {
  const text = String(value ?? "")
    .replace(/\r\n/g, "\n")
    .split("\n")
    .map((line) => line.replace(/\s+/g, " ").trim())
    .find(Boolean);
  if (!text) {
    return "";
  }
  // Drop heavily escaped / mojibake fragments from broken console encodings.
  if ((text.match(/\\n/g) || []).length >= 2 || /[?]{2,}|�/.test(text)) {
    return "";
  }
  return text.length > maxLen ? `${text.slice(0, maxLen - 1).trimEnd()}…` : text;
}

/**
 * Codex-style one-line summary for terminal/write_stdin sandbox payloads.
 * Never returns raw JSON or multi-kilobyte stdout.
 */
export function terminalSandboxPresentationSummary(
  value: string | undefined,
  language: ConversationToolPresentationLanguage,
): string {
  const parsed = extractJsonObject(String(value ?? ""));
  if (!parsed || !isTerminalSandboxPayload(parsed)) {
    return "";
  }
  const status = String(parsed.status || parsed.outcomeStatus || "").trim().toLowerCase();
  const outcome = String(parsed.outcomeStatus || "").trim().toLowerCase();
  const timedOut = Boolean(parsed.timedOut)
    || status === "timeout"
    || outcome === "timeout"
    || String(parsed.failureClass || "").toLowerCase().includes("timeout");
  const exitCodeRaw = parsed.exitCode;
  const exitCode = typeof exitCodeRaw === "number" && Number.isFinite(exitCodeRaw)
    ? exitCodeRaw
    : Number(String(exitCodeRaw ?? "").trim());
  const hasExit = Number.isFinite(exitCode);

  if (timedOut || status === "timeout" || outcome === "timeout") {
    return language === "zh" ? "执行超时" : "Timed out";
  }
  if (status === "running" || outcome === "running") {
    return language === "zh" ? "正在运行" : "Running";
  }
  if (status === "failed" || status === "error" || (hasExit && exitCode !== 0)) {
    const errLine = firstTextLine(parsed.stderr || parsed.error || parsed.message);
    if (errLine) {
      return language === "zh" ? `执行失败 · ${errLine}` : `Failed · ${errLine}`;
    }
    if (hasExit && exitCode !== 0) {
      return language === "zh" ? `执行失败 · 退出码 ${exitCode}` : `Failed · exit ${exitCode}`;
    }
    return language === "zh" ? "执行失败" : "Failed";
  }
  if (status === "completed" || status === "done" || status === "ok" || (hasExit && exitCode === 0)) {
    const outLine = firstTextLine(parsed.formattedOutput || parsed.stdout || parsed.summary);
    return outLine || "";
  }
  const fallback = firstTextLine(parsed.formattedOutput || parsed.stdout || parsed.stderr);
  return fallback || (language === "zh" ? "终端结果" : "Terminal result");
}

/**
 * Expanded detail for terminal payloads: short human lines only, no session ids / raw protocol.
 */
export function terminalSandboxPresentationDetail(
  value: string | undefined,
  language: ConversationToolPresentationLanguage,
): string {
  const parsed = extractJsonObject(String(value ?? ""));
  if (!parsed || !isTerminalSandboxPayload(parsed)) {
    return "";
  }
  const lines: string[] = [];
  const summary = terminalSandboxPresentationSummary(value, language);
  if (summary) {
    lines.push(summary);
  }
  const exitCodeRaw = parsed.exitCode;
  const exitCode = typeof exitCodeRaw === "number" && Number.isFinite(exitCodeRaw)
    ? exitCodeRaw
    : Number(String(exitCodeRaw ?? "").trim());
  if (Number.isFinite(exitCode)) {
    lines.push(language === "zh" ? `退出码 ${exitCode}` : `Exit code ${exitCode}`);
  }
  const stderr = String(parsed.stderr || "").trim();
  if (stderr) {
    const clipped = stderr
      .replace(/\r\n/g, "\n")
      .split("\n")
      .slice(0, 8)
      .join("\n")
      .slice(0, 600);
    lines.push(clipped + (stderr.length > clipped.length ? "\n…" : ""));
  } else {
    const stdout = String(parsed.formattedOutput || parsed.stdout || "").trim();
    if (stdout && !/timeout|执行超时/i.test(summary)) {
      const clipped = stdout
        .replace(/\r\n/g, "\n")
        .replace(/\\n/g, "\n")
        .split("\n")
        .slice(0, 12)
        .join("\n")
        .slice(0, 800);
      if (clipped && !/[?]{3,}|�/.test(clipped)) {
        lines.push(clipped + (stdout.length > clipped.length ? "\n…" : ""));
      }
    }
  }
  return lines.filter(Boolean).join("\n");
}

/** Collapse multi-tool search mashups into a short activity line. */
function searchMashupPresentationSummary(
  value: string,
  language: ConversationToolPresentationLanguage,
) {
  const text = value.replace(/\s+/g, " ").trim();
  if (!text.includes("[搜索]") && !text.includes("[Search]")) {
    return "";
  }
  const noMatch = /未找到匹配|no matches|0 results/i.test(text);
  const hitFiles = text.match(/'path'\s*:\s*'([^']+)'/g) || text.match(/"path"\s*:\s*"([^"]+)"/g);
  const fileCount = hitFiles?.length ?? 0;
  if (noMatch && fileCount === 0) {
    return language === "zh" ? "未找到匹配" : "No matches";
  }
  if (fileCount > 0) {
    return language === "zh" ? `搜索完成 · ${fileCount} 个命中` : `Search done · ${fileCount} hits`;
  }
  return language === "zh" ? "搜索完成" : "Search complete";
}

function compactToolPresentationCandidate(
  value: string | undefined,
  toolName: string | undefined,
  language: ConversationToolPresentationLanguage,
) {
  const raw = String(value ?? "").trim();
  if (!raw || raw === String(toolName ?? "").trim()) {
    return "";
  }
  // Prefer one-line sandbox summary before collapsing whitespace (keeps structure for JSON extract).
  const terminalSummary = terminalSandboxPresentationSummary(raw, language);
  if (terminalSummary) {
    return terminalSummary;
  }
  const searchSummary = searchMashupPresentationSummary(raw, language);
  if (searchSummary) {
    return searchSummary;
  }

  const normalized = raw.replace(/\s+/g, " ").trim();
  if (String(toolName ?? "").trim().toLowerCase() === "conversation_log_inspect_tool") {
    const target = conversationLogInspectTarget(normalized);
    if (target) {
      return target;
    }
  }
  // Embedded JSON after a human prefix (e.g. "执行失败 · {\"status\":...}").
  const embeddedTerminal = terminalSandboxPresentationSummary(normalized, language);
  if (embeddedTerminal) {
    return embeddedTerminal;
  }
  if (normalized.startsWith("{") || normalized.startsWith("[") || normalized.includes('{"status"')) {
    try {
      const parsed = extractJsonObject(normalized) ?? (JSON.parse(normalized) as Record<string, unknown>);
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        if (isTerminalSandboxPayload(parsed)) {
          return terminalSandboxPresentationSummary(JSON.stringify(parsed), language);
        }
        if (String(toolName ?? "").trim().toLowerCase() === "code_symbol_tool") {
          const codeSummary = codeSymbolStructuredSummary(parsed, language);
          if (codeSummary) {
            return compactToolPresentationText(codeSummary);
          }
        }
        const semantic = [
          parsed.dirty_summary,
          parsed.message,
          // Prefer short semantic fields; never promote huge stdout-like "summary" blobs.
          typeof parsed.summary === "string" && parsed.summary.length <= 160 ? parsed.summary : "",
          typeof parsed.result === "string" && parsed.result.length <= 160 ? parsed.result : "",
        ].find((item) => typeof item === "string" && item.trim());
        if (typeof semantic === "string" && semantic.trim()) {
          return isLowValueToolResult(semantic)
            ? ""
            : compactToolPresentationText(semantic);
        }
        const statusOnly = compactScalar(parsed.status);
        if (statusOnly && ["timeout", "failed", "error", "running", "ok", "done", "completed", "success"].includes(statusOnly.toLowerCase())) {
          if (statusOnly.toLowerCase() === "timeout") {
            return language === "zh" ? "执行超时" : "Timed out";
          }
          if (statusOnly.toLowerCase() === "running") {
            return language === "zh" ? "正在运行" : "Running";
          }
          if (["ok", "done", "completed", "success"].includes(statusOnly.toLowerCase())) {
            return "";
          }
          return language === "zh" ? "执行失败" : "Failed";
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
      if (semantic && semantic.length <= 120 && !semantic.includes("\\n")) {
        return isLowValueToolResult(semantic)
          ? ""
          : compactToolPresentationText(semantic);
      }
      return language === "zh"
        ? "已返回结构化结果"
        : "Structured result returned";
    }
  }
  // Never surface multi-line protocol dumps as the collapsed row summary.
  if (normalized.length > 240 && (normalized.includes("terminalSessionId") || normalized.includes("formattedOutput"))) {
    return language === "zh" ? "终端结果" : "Terminal result";
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
    || normalizedToolName === "write_stdin"
    || normalizedToolName === "cli_tool"
    || normalizedToolName === "run_terminal_command"
    || normalizedToolName === "shell_tool";
  if (terminalTool && (normalizedStatus === "running" || normalizedStatus === "pending")) {
    // Prefer payload-derived summary when available (timeout/running/exit).
    for (const candidate of [toolSummary, cellSummary, resultPreview, cellText]) {
      const fromPayload = terminalSandboxPresentationSummary(String(candidate || ""), language);
      if (fromPayload) {
        return fromPayload;
      }
    }
    return language === "zh" ? "正在运行" : "Running";
  }
  if (terminalTool && normalizedStatus === "completed") {
    for (const candidate of [toolSummary, cellSummary, resultPreview, cellText]) {
      const fromPayload = terminalSandboxPresentationSummary(String(candidate || ""), language);
      if (fromPayload && fromPayload !== (language === "zh" ? "正在运行" : "Running")) {
        return fromPayload === (language === "zh" ? "执行超时" : "Timed out")
          || fromPayload.startsWith(language === "zh" ? "执行失败" : "Failed")
          ? fromPayload
          : "";
      }
    }
    return "";
  }
  if (terminalTool && (normalizedStatus === "failed" || normalizedStatus === "error" || normalizedStatus === "timeout")) {
    for (const candidate of [toolSummary, cellSummary, resultPreview, cellText]) {
      const fromPayload = terminalSandboxPresentationSummary(String(candidate || ""), language);
      if (fromPayload) {
        return fromPayload;
      }
    }
    return normalizedStatus === "timeout" || /timeout|超时/i.test(`${toolSummary || ""} ${cellSummary || ""}`)
      ? (language === "zh" ? "执行超时" : "Timed out")
      : (language === "zh" ? "执行失败" : "Failed");
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

const EDIT_TOOL_NAMES = new Set([
  "apply_patch_tool",
  "apply_diff_edit_tool",
  "write_file_tool",
  "edit_file_tool",
  "str_replace_tool",
]);

const SHELL_TOOL_NAMES = new Set([
  "cli_tool",
  "exec_command",
  "write_stdin",
  "run_terminal_command",
  "shell_tool",
]);

function basenamePath(value: string) {
  const normalized = value.replace(/\\/g, "/").trim();
  if (!normalized) {
    return "";
  }
  const parts = normalized.split("/").filter(Boolean);
  return parts.at(-1) || normalized;
}

function extractToolSubject(options: {
  toolName: string;
  toolSummary?: string;
  cellSummary?: string;
  resultPreview?: string;
  displayCommand?: string;
  filePath?: string;
  language?: ConversationToolPresentationLanguage;
}) {
  const filePath = String(options.filePath || "").trim();
  if (filePath) {
    return basenamePath(filePath);
  }
  const command = String(options.displayCommand || "").trim();
  if (command) {
    return command.length > 72 ? `${command.slice(0, 71).trimEnd()}…` : command;
  }
  const language = options.language || "zh";
  for (const candidate of [options.toolSummary, options.cellSummary, options.resultPreview]) {
    const terminal = terminalSandboxPresentationSummary(String(candidate || ""), language);
    if (terminal) {
      // Subject stays empty for pure status lines; status pill already shows failure/timeout.
      if (
        terminal === "执行超时"
        || terminal === "Timed out"
        || terminal === "执行失败"
        || terminal === "Failed"
        || terminal === "正在运行"
        || terminal === "Running"
        || terminal === "终端结果"
        || terminal === "Terminal result"
      ) {
        continue;
      }
      return terminal;
    }
    const text = String(candidate || "").replace(/\s+/g, " ").trim();
    if (!text || isLowValueToolResult(text)) {
      continue;
    }
    // Skip raw JSON / protocol noise that is not human-readable subject text.
    // Keep human diagnostics that merely start with a bracket tag, e.g. "[超时] …".
    if (
      text.startsWith("{")
      || text.includes("terminalSessionId")
      || text.includes("formattedOutput")
      || (text.startsWith("[") && /^\[\s*[{"]/.test(text))
      || /^["']?status["']?\s*[:=]/i.test(text)
    ) {
      continue;
    }
    // Prefer path-looking fragments for edit tools.
    const pathMatch = text.match(/(?:^|[\s`"'])((?:[\w.-]+\/)+[\w.-]+\.[A-Za-z0-9]{1,12})/);
    if (pathMatch?.[1] && EDIT_TOOL_NAMES.has(options.toolName)) {
      return basenamePath(pathMatch[1]);
    }
    if (text.length > 72) {
      return `${text.slice(0, 71).trimEnd()}…`;
    }
    return text;
  }
  return "";
}

export type CodexToolActivityPillStatusKind =
  | "running"
  | "completed"
  | "failed"
  | "timeout"
  | "attention"
  | "idle";

export type CodexToolActivityPills = {
  actionLabel: string;
  statusLabel: string;
  statusKind: CodexToolActivityPillStatusKind;
  subject: string;
  durationLabel: string;
};

/**
 * Normalize legacy agent-operation statuses (done/success/in_progress/…) onto the
 * pill status vocabulary so both render paths share one mapper.
 */
export function normalizeToolActivityStatus(status: string | undefined | null) {
  const normalized = String(status || "").trim().toLowerCase();
  if (["done", "success", "completed", "succeeded", "ok"].includes(normalized)) {
    return "completed";
  }
  if (["running", "in_progress", "active", "working"].includes(normalized)) {
    return "running";
  }
  if (["pending", "queued", "waiting"].includes(normalized)) {
    return "pending";
  }
  if (["failed", "error", "cancelled", "canceled"].includes(normalized)) {
    return "failed";
  }
  if (["degraded", "fallback", "partial", "unavailable", "recovered"].includes(normalized)) {
    return "degraded";
  }
  return normalized;
}

/** Pull a human command string from tool argument bags used by legacy ops. */
export function extractToolDisplayCommand(args?: Record<string, unknown> | null) {
  if (!args) {
    return "";
  }
  for (const key of ["displayCommand", "command", "cmd"]) {
    const value = args[key];
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
    if (Array.isArray(value) && value.length > 0) {
      return value.map(String).join(" ").trim();
    }
  }
  return "";
}

/**
 * Codex tool-row model: action + optional status + muted subject/duration.
 * UI must not render dual status chips for running/completed — the leading
 * icon carries those states (see ConversationToolActivityPills).
 */
export function buildCodexToolActivityPills(options: {
  toolName: string;
  status?: string;
  language: ConversationToolPresentationLanguage;
  durationSeconds?: number | null;
  durationLabel?: string;
  toolSummary?: string;
  cellSummary?: string;
  resultPreview?: string;
  displayCommand?: string;
  filePath?: string;
  timedOut?: boolean;
  noMatch?: boolean;
  nonzeroExit?: boolean;
}): CodexToolActivityPills {
  const language = options.language;
  const toolName = String(options.toolName || "").trim().toLowerCase();
  const status = normalizeToolActivityStatus(options.status);
  const actionLabel = conversationToolPresentationLabel(toolName, language);
  // Prefer payload timeout signal over generic status text.
  const payloadTimedOut = [options.toolSummary, options.cellSummary, options.resultPreview]
    .some((value) => {
      const line = terminalSandboxPresentationSummary(String(value || ""), language);
      return line === "执行超时" || line === "Timed out";
    });
  const timedOut = Boolean(options.timedOut)
    || payloadTimedOut
    || /超时|timed?\s*out/i.test(`${options.toolSummary || ""} ${options.cellSummary || ""}`);
  let subject = extractToolSubject({
    toolName,
    toolSummary: options.toolSummary,
    cellSummary: options.cellSummary,
    resultPreview: options.resultPreview,
    displayCommand: options.displayCommand,
    filePath: options.filePath,
    language,
  });
  const subjectKey = subject.trim().toLowerCase().replace(/[\s-]+/g, "_");
  if (
    !subject
    || subjectKey === toolName
    || subjectKey === actionLabel.toLowerCase().replace(/[\s-]+/g, "_")
    || subjectKey.endsWith("_tool")
  ) {
    subject = "";
  }
  const durationLabel = String(options.durationLabel || "").trim();

  if (options.noMatch) {
    return {
      actionLabel,
      statusLabel: language === "zh" ? "无匹配" : "No matches",
      statusKind: "attention",
      subject,
      durationLabel,
    };
  }

  // Preserve fine-grained degraded states before the generic mapper.
  const rawStatus = String(options.status || "").trim().toLowerCase();
  if (rawStatus === "fallback") {
    return {
      actionLabel,
      statusLabel: language === "zh" ? "备用路径" : "Fallback",
      statusKind: "attention",
      subject,
      durationLabel,
    };
  }
  if (rawStatus === "partial") {
    return {
      actionLabel,
      statusLabel: language === "zh" ? "部分结果" : "Partial",
      statusKind: "attention",
      subject,
      durationLabel,
    };
  }
  if (rawStatus === "unavailable") {
    return {
      actionLabel,
      statusLabel: language === "zh" ? "不可用" : "Unavailable",
      statusKind: "attention",
      subject,
      durationLabel,
    };
  }
  if (rawStatus === "recovered") {
    return {
      actionLabel,
      statusLabel: language === "zh" ? "已恢复" : "Recovered",
      statusKind: "attention",
      subject,
      durationLabel,
    };
  }

  if (status === "running" || status === "pending") {
    return {
      actionLabel,
      statusLabel: language === "zh" ? "运行中" : "Running",
      statusKind: "running",
      subject,
      durationLabel,
    };
  }

  // Explicit / payload timeout outranks generic "failed" (write_stdin often status=failed + timedOut).
  if (timedOut) {
    return {
      actionLabel,
      statusLabel: language === "zh" ? "超时" : "Timed out",
      statusKind: "timeout",
      subject,
      durationLabel,
    };
  }
  if (status === "failed") {
    return {
      actionLabel,
      statusLabel: language === "zh" ? "执行失败" : "Failed",
      statusKind: "failed",
      subject,
      durationLabel,
    };
  }

  if (options.nonzeroExit) {
    return {
      actionLabel,
      statusLabel: language === "zh" ? "退出异常" : "Non-zero exit",
      statusKind: "attention",
      subject,
      durationLabel,
    };
  }

  if (status === "degraded") {
    return {
      actionLabel,
      statusLabel: language === "zh" ? "降级完成" : "Degraded",
      statusKind: "attention",
      subject,
      durationLabel,
    };
  }

  return {
    actionLabel,
    statusLabel: language === "zh" ? "执行完成" : "Done",
    statusKind: "completed",
    subject,
    durationLabel,
  };
}

/**
 * Codex-style one-line tool activity title (legacy prose; prefer pills in UI).
 * Examples: "已在 12s 内运行 pnpm test", "已编辑 foo.ts", "失败 · 代码图谱".
 */
export function formatCodexStyleToolActivityLine(options: {
  toolName: string;
  status?: string;
  language: ConversationToolPresentationLanguage;
  durationSeconds?: number | null;
  durationLabel?: string;
  toolSummary?: string;
  cellSummary?: string;
  resultPreview?: string;
  displayCommand?: string;
  filePath?: string;
  timedOut?: boolean;
}) {
  const language = options.language;
  const toolName = String(options.toolName || "").trim().toLowerCase();
  const status = String(options.status || "").trim().toLowerCase();
  const label = conversationToolPresentationLabel(toolName, language);
  let subject = extractToolSubject({
    toolName,
    toolSummary: options.toolSummary,
    cellSummary: options.cellSummary,
    resultPreview: options.resultPreview,
    displayCommand: options.displayCommand,
    filePath: options.filePath,
  });
  // Avoid "列出文件 · glob_tool" noise when subject is just the raw tool id / label.
  const subjectKey = subject.trim().toLowerCase().replace(/[\s-]+/g, "_");
  if (
    !subject
    || subjectKey === toolName
    || subjectKey === label.toLowerCase().replace(/[\s-]+/g, "_")
    || subjectKey.endsWith("_tool")
  ) {
    subject = "";
  }
  const durationLabel = String(options.durationLabel || "").trim();
  const isEdit = EDIT_TOOL_NAMES.has(toolName);
  const isShell = SHELL_TOOL_NAMES.has(toolName);
  const timedOut = Boolean(options.timedOut)
    || /超时|timed?\s*out/i.test(`${options.toolSummary || ""} ${options.cellSummary || ""}`);

  if (status === "running" || status === "pending") {
    if (subject && /^(正在|Running\b)/i.test(subject)) {
      return subject;
    }
    if (isShell && subject) {
      return language === "zh" ? `正在运行 ${subject}` : `Running ${subject}`;
    }
    if (subject) {
      return language === "zh" ? `正在${label} · ${subject}` : `${label} · ${subject}`;
    }
    return language === "zh" ? `正在${label}` : label;
  }

  if (status === "failed" || timedOut) {
    const failLabel = timedOut
      ? (language === "zh" ? "超时" : "Timed out")
      : (language === "zh" ? "失败" : "Failed");
    if (subject) {
      return language === "zh" ? `${failLabel} · ${label} · ${subject}` : `${failLabel} · ${label} · ${subject}`;
    }
    return language === "zh" ? `${failLabel} · ${label}` : `${failLabel} · ${label}`;
  }

  if (isEdit) {
    if (subject) {
      return language === "zh" ? `已编辑 ${subject}` : `Edited ${subject}`;
    }
    return language === "zh" ? "已编辑文件" : "Edited file";
  }

  if (isShell) {
    if (durationLabel && subject) {
      return language === "zh"
        ? `已在 ${durationLabel} 内运行 ${subject}`
        : `Ran ${subject} in ${durationLabel}`;
    }
    if (subject) {
      return language === "zh" ? `已运行 ${subject}` : `Ran ${subject}`;
    }
    if (durationLabel) {
      return language === "zh"
        ? `已在 ${durationLabel} 内运行命令`
        : `Ran command in ${durationLabel}`;
    }
    return language === "zh" ? "已运行命令" : "Ran command";
  }

  if (durationLabel && subject) {
    return language === "zh"
      ? `已在 ${durationLabel} 内完成 ${label} · ${subject}`
      : `${label} · ${subject} in ${durationLabel}`;
  }
  if (durationLabel) {
    return language === "zh"
      ? `已在 ${durationLabel} 内完成 ${label}`
      : `${label} in ${durationLabel}`;
  }
  if (subject) {
    return language === "zh" ? `${label} · ${subject}` : `${label} · ${subject}`;
  }
  return label;
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
  const lowerTool = String(toolName ?? "").trim().toLowerCase();
  // Terminal / write_stdin: never dump raw protocol JSON into the expanded panel.
  const terminalDetail = terminalSandboxPresentationDetail(normalized, language);
  if (terminalDetail) {
    return terminalDetail;
  }
  if (
    lowerTool === "exec_command"
    || lowerTool === "write_stdin"
    || lowerTool === "cli_tool"
    || lowerTool === "run_terminal_command"
    || lowerTool === "shell_tool"
  ) {
    // Plain command lines / stdout must stay literal. Never force the failed-summary
    // path (it collapses "git status --short" into "执行失败").
    const looksLikeProtocolJson = normalized.startsWith("{")
      || normalized.startsWith("[")
      || normalized.includes("terminalSessionId")
      || normalized.includes("\"status\"");
    if (!looksLikeProtocolJson) {
      return normalized.length > 1600
        ? `${normalized.slice(0, 1600).trimEnd()}…`
        : normalized;
    }
    const summary = terminalSandboxPresentationSummary(normalized, language);
    if (summary) {
      return summary;
    }
    // Last resort: bounded plain text, never multi-KB protocol blobs.
    if (normalized.length > 400 || normalized.includes("terminalSessionId")) {
      return language === "zh" ? "终端输出已折叠（展开源数据见日志）" : "Terminal output collapsed (see logs for raw data)";
    }
  }
  if (lowerTool === "code_symbol_tool" && (normalized.startsWith("{") || normalized.includes("{"))) {
    try {
      const parsed = extractJsonObject(normalized) ?? (JSON.parse(normalized) as Record<string, unknown>);
      if (parsed) {
        return codeSymbolStructuredDetail(parsed, language)
          || codeSymbolStructuredSummary(parsed, language)
          || (language === "zh" ? "已返回结构化结果" : "Structured result returned");
      }
    } catch {
      return language === "zh" ? "已返回结构化结果" : "Structured result returned";
    }
  }
  if (normalized.startsWith("{") || normalized.includes("terminalSessionId") || normalized.includes("formattedOutput")) {
    const asTerminal = terminalSandboxPresentationDetail(normalized, language)
      || terminalSandboxPresentationSummary(normalized, language);
    if (asTerminal) {
      return asTerminal;
    }
    if (normalized.length > 280) {
      return language === "zh" ? "已返回结构化结果" : "Structured result returned";
    }
  }
  return normalized;
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
    cli_tool: { zh: "执行命令", en: "Run command" },
    exec_command: { zh: "执行命令", en: "Run command" },
    run_terminal_command: { zh: "执行命令", en: "Run command" },
    shell_tool: { zh: "执行命令", en: "Run command" },
    write_stdin: { zh: "写入终端", en: "Write to terminal" },
    grep_search_tool: { zh: "搜索", en: "Search" },
    read_file_tool: { zh: "读取文件", en: "Read file" },
    glob_tool: { zh: "列出文件", en: "List files" },
    code_symbol_tool: { zh: "代码图谱", en: "Code graph" },
    code_graph_tool: { zh: "代码图谱", en: "Code graph" },
    explain_current_worktree_tool: {
      zh: "工作树详情",
      en: "Worktree details",
    },
    get_core_context_tool: { zh: "核心上下文", en: "Core context" },
    get_current_goal_tool: { zh: "当前目标", en: "Current goal" },
    search_code_tool: { zh: "搜索代码", en: "Search code" },
    web_search_tool: { zh: "网页搜索", en: "Web search" },
    batch_web_search_tool: { zh: "网页搜索", en: "Web search" },
    web_fetch_tool: { zh: "网页读取", en: "Read web page" },
    source_collection_context_tool: { zh: "读取资料上下文", en: "Read source context" },
    source_collection_stage_writeback_tool: { zh: "资料阶段写回", en: "Write source-stage result" },
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
    image2_generate_tool: { zh: "生成图片", en: "Generate image" },
    spawn_agent_tool: { zh: "派生代理", en: "Spawn agent" },
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
