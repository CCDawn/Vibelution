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
      team_create: ["创建团队", "Create team"], knowledge_ingest: ["知识入库", "Ingest knowledge"],
      team_run: ["创建团队并运行", "Create and run team"],
      config_update: ["修改偏好配置", "Update preferences config"],
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
    const plan = summary.assistantPlan;
    const teamPlan = plan && typeof plan === "object" && !Array.isArray(plan)
      ? plan as Record<string, unknown> : null;
    if (action === "team_run" && (!teamPlan || teamPlan.memberCount !== 4 || teamPlan.startsImmediately !== true
      || teamPlan.automaticRecovery !== false || teamPlan.localIntegration !== false)) {
      return `${title}\n${lang === "zh" ? "运行范围无法核对，请拒绝并重新发起。" : "Run scope cannot be verified. Decline and request again."}`;
    }
    const teamLines = action === "team_run" && teamPlan ? [
      `${lang === "zh" ? "目标" : "Goal"}: ${String(teamPlan.goalPreview || "").slice(0, 160)}`,
      lang === "zh" ? "创建 4 名成员：规划师 → 开发 A → 开发 B → 评审员；立即启动原生工作流。"
        : "Create 4 members: planner → developer A → developer B → reviewer; start the native workflow immediately.",
      lang === "zh" ? "沿用模板权限；不启用自动恢复、自动合入或部署。"
        : "Keep template permissions; no automatic recovery, integration, or deployment.",
    ] : [];
    return [title, ...targetLines, ...teamLines,
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
      toolSession: "本会话此工具",
      actionWindow: "同意并授权 4 小时",
      no: "否",
      resolving: "处理中…",
    };
  }
  return {
    yes: "Yes",
    always: "Always (this agent)",
    toolSession: "This tool, this session",
    actionWindow: "Allow for 4 hours",
    no: "No",
    resolving: "Resolving…",
  };
}

/** Human-readable remaining authorization window, e.g. "2 小时 13 分". */
export function formatActionWindowRemaining(seconds: number, lang: "zh" | "en") {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  if (lang === "zh") {
    if (hours > 0) return minutes > 0 ? `${hours} 小时 ${minutes} 分` : `${hours} 小时`;
    if (minutes > 0) return `${minutes} 分钟`;
    return "不足 1 分钟";
  }
  if (hours > 0) return minutes > 0 ? `${hours}h ${minutes}m` : `${hours}h`;
  if (minutes > 0) return `${minutes} min`;
  return "<1 min";
}

/** One line per already-delegated low-risk manage action for the approval card. */
export function assistantActionWindowSummary(
  window: {
    eligible?: boolean;
    durationSeconds?: number;
    activeWindows?: Array<{ action: string; remainingSeconds: number }>;
  } | null | undefined,
  lang: "zh" | "en",
): string {
  const active = Array.isArray(window?.activeWindows) ? window!.activeWindows : [];
  if (!active.length) return "";
  const labels: Record<string, [string, string]> = {
    session_create: ["创建会话", "Create session"],
    session_stop: ["停止会话任务", "Stop session turn"],
    session_update: ["更新会话", "Update session"],
  };
  return active
    .map((item) => {
      const label = labels[item.action]?.[lang === "zh" ? 0 : 1] ?? item.action;
      return lang === "zh"
        ? `${label}：授权剩余 ${formatActionWindowRemaining(item.remainingSeconds, lang)}`
        : `${label}: ${formatActionWindowRemaining(item.remainingSeconds, lang)} left`;
    })
    .join("\n");
}
