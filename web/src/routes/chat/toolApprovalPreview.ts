import { TOOL_APPROVAL_LABELS } from "./toolApprovalLabels";

/**
 * Codex-style approval preview helpers.
 * Codex CLI prompts "Allow command?" with Yes / Always / No and shows the action body.
 */

export function toolApprovalDisplayName(toolName: string | undefined | null, lang: "zh" | "en") {
  const key = String(toolName || "").trim();
  if (key === "personal_assistant_manage_tool") return lang === "zh" ? "平台管理" : "Platform management";
  if (!key) {
    return lang === "zh" ? "工具操作" : "tool action";
  }
  return TOOL_APPROVAL_LABELS[key] ?? key;
}

export function toolApprovalActionPreview(
  argumentSummary: Record<string, unknown> | null | undefined,
  toolName?: string | null,
  lang: "zh" | "en" = "zh",
): string {
  const summary = argumentSummary && typeof argumentSummary === "object" ? argumentSummary : {};
  if (toolName === "personal_assistant_manage_tool") {
    const actions: Record<string, [string, string]> = {
      agent_create: ["创建 Agent", "Create agent"], agent_update: ["修改 Agent", "Update agent"],
      agent_archive: ["归档 Agent", "Archive agent"], session_create: ["创建会话", "Create session"],
      session_update: ["修改会话", "Update session"], session_stop: ["停止会话任务", "Stop session turn"],
      session_delete: ["删除会话", "Delete session"], knowledge_acl_grant: ["变更知识访问权限", "Change knowledge access"],
      restart: ["重启平台", "Restart platform"], workflow_recovery_bind: ["绑定失败恢复流程", "Bind failure recovery"],
      workflow_recovery_revoke: ["撤销失败恢复绑定", "Revoke failure recovery"], workflow_start: ["启动工作流", "Start workflow"],
    };
    const action = String(summary.assistantAction || "");
    const title = actions[action]?.[lang === "zh" ? 0 : 1] ?? toolApprovalDisplayName(toolName, lang);
    if (summary.assistantArgumentsInvalid || !Object.hasOwn(actions, action)) {
      return `${title}\n${lang === "zh" ? "参数无法核对，请拒绝并重新发起。" : "Arguments cannot be verified. Decline and request again."}`;
    }
    const targets = summary.assistantTargets;
    const targetLines = targets && typeof targets === "object" && !Array.isArray(targets)
      ? Object.entries(targets).filter(([, value]) => typeof value === "string")
        .slice(0, 20).map(([key, value]) => `${key}: ${String(value).slice(0, 160)}`) : [];
    const fields = Array.isArray(summary.assistantChangedFields) ? summary.assistantChangedFields.slice(0, 20) : [];
    const permissions = Array.isArray(summary.assistantPermissions) ? summary.assistantPermissions.slice(0, 3) : [];
    return [title, ...targetLines,
      permissions.length ? `${lang === "zh" ? "授予权限" : "Grant permissions"}: ${permissions.join(", ")}` : "",
      fields.length ? `${lang === "zh" ? "修改字段" : "Changed fields"}: ${fields.join(", ")}` : "",
      summary.assistantDetailsOmitted ? (lang === "zh" ? "部分参数值未展示，请核对本次指令。" : "Values omitted; verify the requested scope.") : "",
    ].filter(Boolean).join("\n");
  }
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
      ? "始终：永久允许此 Agent 对同一终端的后续输入（跨会话、重启后仍有效）"
      : "Always: permanently allow later input for this terminal on this agent (survives sessions and restarts)";
  }
  return lang === "zh"
    ? "始终：永久允许此 Agent 参数完全相同的调用（跨会话、重启后仍有效）"
    : "Always: permanently allow identical-argument calls on this agent (survives sessions and restarts)";
}

export function toolApprovalCodexTitle(lang: "zh" | "en") {
  return lang === "zh" ? "允许执行？" : "Allow this action?";
}

export function toolApprovalCodexButtonLabels(lang: "zh" | "en") {
  if (lang === "zh") {
    return {
      yes: "是",
      always: "始终（此 Agent）",
      no: "否",
      resolving: "处理中…",
    };
  }
  return {
    yes: "Yes",
    always: "Always (this agent)",
    no: "No",
    resolving: "Resolving…",
  };
}
