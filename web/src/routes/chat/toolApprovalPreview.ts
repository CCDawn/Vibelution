import { TOOL_APPROVAL_LABELS } from "./toolApprovalLabels";

/**
 * Codex-style approval preview helpers.
 * Codex CLI prompts "Allow command?" with Yes / Always / No and shows the action body.
 */

export function toolApprovalDisplayName(toolName: string | undefined | null, lang: "zh" | "en") {
  const key = String(toolName || "").trim();
  if (!key) {
    return lang === "zh" ? "工具操作" : "tool action";
  }
  return TOOL_APPROVAL_LABELS[key] ?? key;
}

export function toolApprovalActionPreview(
  argumentSummary: Record<string, unknown> | null | undefined,
  toolName?: string | null,
): string {
  const summary = argumentSummary && typeof argumentSummary === "object" ? argumentSummary : {};
  const command = String(summary.commandPreview || summary.command || summary.cmd || "").trim();
  const cwd = String(summary.cwdPreview || summary.cwd || "").trim();
  const terminalSessionId = String(summary.terminalSessionId || "").trim();
  const stdinPreview = String(summary.stdinPreview ?? "");
  const stdinChars = Number(summary.stdinChars ?? stdinPreview.length);
  if (command) {
    return [`$ ${command}`, cwd ? `cwd: ${cwd}` : ""].filter(Boolean).join("\n");
  }
  if (terminalSessionId || "stdinPreview" in summary) {
    return [
      terminalSessionId ? `terminal: ${terminalSessionId}` : "",
      `stdin (${Number.isFinite(stdinChars) ? stdinChars : stdinPreview.length} chars):`,
      stdinPreview || "(empty)",
    ].filter(Boolean).join("\n");
  }
  const path = String(summary.pathPreview || summary.file_path || summary.path || "").trim();
  if (path) {
    return path;
  }
  const keys = Array.isArray(summary.argumentKeys)
    ? summary.argumentKeys.map((item) => String(item || "").trim()).filter(Boolean)
    : [];
  if (keys.length) {
    return keys.slice(0, 8).join(", ");
  }
  return toolApprovalDisplayName(toolName, "en");
}

export function toolApprovalSessionGrantDescription(
  scope: Record<string, unknown> | null | undefined,
  lang: "zh" | "en",
) {
  const kind = String(scope?.kind || "").trim();
  if (kind === "terminal_session") {
    return lang === "zh"
      ? "始终：仅允许本会话中同一终端的后续输入"
      : "Always: allow later input only for this terminal in this session";
  }
  return lang === "zh"
    ? "始终：仅允许本会话中参数完全相同的调用"
    : "Always: allow only calls with identical arguments in this session";
}

export function toolApprovalCodexTitle(lang: "zh" | "en") {
  return lang === "zh" ? "允许执行？" : "Allow this action?";
}

export function toolApprovalCodexButtonLabels(lang: "zh" | "en") {
  if (lang === "zh") {
    return {
      yes: "是",
      always: "始终（本会话）",
      no: "否",
      resolving: "处理中…",
    };
  }
  return {
    yes: "Yes",
    always: "Always (session)",
    no: "No",
    resolving: "Resolving…",
  };
}
