import { TOOL_APPROVAL_LABELS } from "./toolApprovalLabels";

export function toolApprovalDisplayName(toolName: string | null | undefined, lang: "zh" | "en") {
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
  const lines: string[] = [];
  const command = String(summary.commandPreview || "").trim();
  const cwd = String(summary.cwdPreview || "").trim();
  const terminalSessionId = String(summary.terminalSessionId || "").trim();
  const stdinPreview = String(summary.stdinPreview ?? "");
  const stdinChars = Number(summary.stdinChars ?? stdinPreview.length);
  const path = String(summary.pathPreview || "").trim();
  if (command) {
    lines.push(`$ ${command}`);
  }
  if (cwd) {
    lines.push(`cwd: ${cwd}`);
  }
  if (terminalSessionId) {
    lines.push(`terminal: ${terminalSessionId}`);
  }
  if ("stdinPreview" in summary) {
    lines.push(`stdin (${Number.isFinite(stdinChars) ? stdinChars : stdinPreview.length} chars):`);
    lines.push(stdinPreview || "(empty)");
  }
  if (!lines.length && path) {
    lines.push(path);
  }
  return lines.join("\n") || toolApprovalDisplayName(toolName, "en");
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
  return lang === "zh"
    ? { yes: "是", always: "始终（本会话）", no: "否", resolving: "处理中…" }
    : { yes: "Yes", always: "Always (session)", no: "No", resolving: "Resolving…" };
}
