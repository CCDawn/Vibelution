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

/** Launcher Agent creation grants no tools; require the complete warning. */
export function launcherAgentCreatePreviewIsValid(summary: Record<string, unknown> | null | undefined): boolean {
  if (!summary || summary.assistantAction !== "agent_create" || summary.assistantArgumentsInvalid) return false;
  const preset = summary.assistantCreatePreset;
  const noTools = preset === undefined && summary.assistantOperationDescription === "新 Agent 默认没有工具和读写范围，不能保证读取或修改项目；派遣写任务不会自动增加工具权限。";
  const expected = ["glob_tool", "grep_search_tool", "read_file_tool", "apply_diff_edit_tool", "write_file_tool"];
  const fileTools = preset === "project_files_v1" && summary.assistantOperationDescription === "固定文件工具权限持续生效；写入按当前权限和协作模式审批，edit/yolo 等模式可能自动批准。目标派遣任务的审批只有在完整预览、版本和执行参数均可验证时才能批准。平台允许的动态目录包括项目、Agent 工作区、项目存储、工具目录、系统临时目录和用户配置允许目录，未来可能变化。不能执行命令或测试。"
    && Array.isArray(summary.assistantCreateTools) && summary.assistantCreateTools.length === expected.length
    && expected.every((name, index) => (summary.assistantCreateTools as unknown[])[index] === name);
  if (!noTools && !fileTools) return false;
  const targets = summary.assistantTargets;
  if (!targets || typeof targets !== "object" || Array.isArray(targets)) return false;
  const { project_id: project, display_name: name, model_id: model } = targets as Record<string, unknown>;
  const displayable = (value: unknown, max: number) => typeof value === "string"
    && Array.from(value).length > 0 && Array.from(value).length <= max && !/[\p{Cc}\p{Cf}\p{Cs}]/u.test(value);
  return Object.keys(targets).length === 3
    && typeof project === "string" && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}(?![\s\S])/.test(project)
    && displayable(name, 120) && displayable(model, 200);
}

/** Validate the exact authorization details before rendering or enabling approval. */
export function authorizationUpgradePreviewIsValid(summary: Record<string, unknown> | null | undefined): boolean {
  if (!summary || summary.assistantAction !== "authorization_upgrade" || summary.assistantArgumentsInvalid) return false;
  const targets = summary.assistantTargets;
  const projectId = targets && typeof targets === "object" && !Array.isArray(targets)
    ? (targets as Record<string, unknown>).project_id : undefined;
  const scopes = summary.assistantAddedScopes;
  // Keep identifiers single-line and unambiguous without truncating them.
  return typeof projectId === "string" && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}(?![\s\S])/.test(projectId)
    && Array.isArray(scopes) && scopes.length > 0
    && Array.from(scopes).every((scope) => typeof scope === "string" && /^[A-Za-z0-9][A-Za-z0-9_.:-]*(?![\s\S])/.test(scope));
}

/** Lifecycle approval must show the complete bound request. */
export function projectLifecyclePreviewIsValid(summary: Record<string, unknown> | null | undefined): boolean {
  if (!summary || summary.assistantAction !== "project_lifecycle" || summary.assistantArgumentsInvalid) return false;
  const targets = summary.assistantTargets;
  if (!targets || typeof targets !== "object" || Array.isArray(targets)) return false;
  const values = targets as Record<string, unknown>;
  if (Object.keys(values).length !== 3) return false;
  return typeof values.project_id === "string" && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}(?![\s\S])/.test(values.project_id)
    && typeof values.request_id === "string" && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}(?![\s\S])/.test(values.request_id)
    && (values.operation === "start" || values.operation === "stop" || values.operation === "restart");
}

/** A write dispatch must show the same complete request that approval binds. */
export function dispatchWritePreviewIsValid(summary: Record<string, unknown> | null | undefined): boolean {
  if (!summary || summary.assistantAction !== "dispatch_write" || summary.assistantArgumentsInvalid
    || summary.assistantRequestedPermission !== "workspace_write") return false;
  const targets = summary.assistantTargets;
  if (!targets || typeof targets !== "object" || Array.isArray(targets)) return false;
  const { project_id: project, agent_id: agent, dispatch_id: dispatch } = targets as Record<string, unknown>;
  const idPattern = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}(?![\s\S])/;
  const dispatchPattern = /^[A-Za-z0-9][A-Za-z0-9_-]{0,119}(?![\s\S])/;
  const task = summary.assistantTask;
  return typeof project === "string" && idPattern.test(project)
    && typeof agent === "string" && idPattern.test(agent)
    && typeof dispatch === "string" && dispatchPattern.test(dispatch)
    && typeof task === "string" && !!task && task === task.trim()
    && Array.from(task).length <= 12000
    && !/[\p{Cc}\p{Cf}\p{Cs}]/u.test(task.replace(/[\n\t]/g, ""));
}

const MANAGE_ACTIONS: Record<string, [string, string]> = {
      project_lifecycle: ["管理项目", "Manage project"],
      dispatch_write: ["派遣 Agent 修改项目", "Dispatch agent to modify project"],
      authorization_upgrade: ["新增项目权限", "Add project permissions"],
      agent_create: ["创建 Agent", "Create agent"], agent_update: ["修改 Agent", "Update agent"],
      agent_archive: ["归档 Agent", "Archive agent"], session_create: ["创建会话", "Create session"],
      session_update: ["修改会话", "Update session"], session_stop: ["停止会话任务", "Stop session turn"],
      session_delete: ["删除会话", "Delete session"], knowledge_acl_grant: ["变更知识访问权限", "Change knowledge access"],
      restart: ["重启平台", "Restart platform"], workflow_recovery_bind: ["绑定失败恢复流程", "Bind failure recovery"],
      workflow_recovery_revoke: ["撤销失败恢复绑定", "Revoke failure recovery"], workflow_start: ["启动工作流", "Start workflow"],
      team_create: ["创建团队", "Create team"], knowledge_ingest: ["知识入库", "Ingest knowledge"],
      team_run: ["创建团队并运行", "Create and run team"],
      config_update: ["修改偏好配置", "Update preferences config"],
      provider_add: ["添加模型连接", "Add model provider"], provider_update: ["修改模型连接", "Update model provider"],
      provider_remove: ["移除模型连接", "Remove model provider"], provider_test: ["测试模型连接", "Test model provider"],
      provider_discover: ["发现连接模型", "Discover provider models"],
      model_update: ["修改模型", "Update model"], model_remove: ["移除模型", "Remove model"],
      model_default: ["设置默认模型", "Set default model"],
      session_pin: ["置顶会话", "Pin session"], session_unpin: ["取消会话置顶", "Unpin session"],
      session_reasoning_update: ["调整会话推理", "Update session reasoning"],
      session_model_parameters_update: ["调整会话模型参数", "Update session model parameters"],
      session_budget_update: ["调整会话预算", "Update session budget"],
      session_archive: ["归档会话", "Archive session"], session_unarchive: ["恢复归档会话", "Unarchive session"],
      team_update: ["修改团队信息", "Update team"], team_archive: ["归档团队及成员", "Archive team and members"],
      room_update: ["修改群聊信息", "Update chat room"],
      assistant_settings_update: ["修改助理偏好", "Update assistant preferences"],
      assistant_model_set: ["切换助理模型", "Change assistant model"],
      dialogue_settings_update: ["调整对话偏好", "Update dialogue preferences"],
      history_import: ["导入旧助理历史", "Import previous assistant history"],
      affairs_sync: ["同步旧助理事务", "Sync previous assistant affairs"],
      episodic_sync: ["同步情景记忆", "Sync episodic memory"],
      initial_migration_queue: ["开始旧助理迁移", "Start previous assistant migration"],
      knowledge_sync_queue: ["同步旧助理知识", "Sync previous assistant knowledge"],
      knowledge_sync_recover: ["恢复知识同步", "Recover knowledge sync"],
      reminder_handoff_queue: ["交接旧助理提醒", "Transfer previous assistant reminders"],
};

export function managementApprovalActionIsKnown(value: unknown): boolean {
  return typeof value === "string" && Object.hasOwn(MANAGE_ACTIONS, value);
}

export function toolApprovalActionPreview(
  argumentSummary: Record<string, unknown> | null | undefined,
  toolName?: string | null,
  lang: "zh" | "en" = "zh",
): string {
  const summary = argumentSummary && typeof argumentSummary === "object" ? argumentSummary : {};
  if (toolName === "personal_assistant_manage_tool") {
    const action = String(summary.assistantAction || "");
    const title = MANAGE_ACTIONS[action]?.[lang === "zh" ? 0 : 1] ?? toolApprovalDisplayName(toolName, lang);
    if (summary.assistantArgumentsInvalid || !managementApprovalActionIsKnown(action)) {
      return `${title}\n${lang === "zh" ? "参数无法核对，请拒绝并重新发起。" : "Arguments cannot be verified. Decline and request again."}`;
    }
    const targets = summary.assistantTargets;
    if (action === "agent_create" && (summary.assistantCreatePreset !== undefined || summary.assistantOperationDescription === "新 Agent 默认没有工具和读写范围，不能保证读取或修改项目；派遣写任务不会自动增加工具权限。")) {
      if (!launcherAgentCreatePreviewIsValid(summary)) {
        return `${title}\n${lang === "zh" ? "参数无法核对，请拒绝并重新发起。" : "Arguments cannot be verified. Decline and request again."}`;
      }
      const identity = targets as Record<string, string>;
      const lines = [title, `${lang === "zh" ? "项目" : "Project"}: ${identity.project_id}`,
        `${lang === "zh" ? "名称" : "Name"}: ${identity.display_name}`,
        `${lang === "zh" ? "模型" : "Model"}: ${identity.model_id}`];
      if (summary.assistantCreatePreset === "project_files_v1") return [...lines,
        `${lang === "zh" ? "工具预设" : "Tool preset"}: project_files_v1`,
        ...(summary.assistantCreateTools as string[]).map(name => `- ${name}`),
        lang === "zh" ? "固定文件工具权限持续生效；写入按当前权限和协作模式审批，edit/yolo 等模式可能自动批准。目标派遣任务的审批只有在完整预览、版本和执行参数均可验证时才能批准。平台允许的动态目录包括项目、Agent 工作区、项目存储、工具目录、系统临时目录和用户配置允许目录，未来可能变化。不能执行命令或测试。"
          : "The file tool permission persists; write approval depends on current permissions and collaboration mode. Edit/yolo modes may approve automatically. Target task approval requires a verifiable complete preview, revision, and execution arguments. Platform allowed directories can include the project, agent workspace, project storage, tools directory, system temporary directories, and user-configured allowed directories; they may change. No command execution or tests."].join("\n");
      return [...lines,
        lang === "zh" ? "新 Agent 默认没有工具和读写范围，不能保证读取或修改项目；派遣写任务不会自动增加工具权限。"
          : "The new agent has no tools or read/write scopes by default, so it cannot be assumed to read or modify the project. Dispatching a write task does not grant tools."].join("\n");
    }
    if (action === "project_lifecycle") {
      if (!projectLifecyclePreviewIsValid(summary)) {
        return `${title}\n${lang === "zh" ? "参数无法核对，请拒绝并重新发起。" : "Arguments cannot be verified. Decline and request again."}`;
      }
      const identity = targets as Record<string, string>;
      const operations: Record<string, [string, string]> = { start: ["启动", "Start"], stop: ["停止", "Stop"], restart: ["重启", "Restart"] };
      return [title, `${lang === "zh" ? "项目" : "Project"}: ${identity.project_id}`,
        `${lang === "zh" ? "操作" : "Operation"}: ${operations[identity.operation][lang === "zh" ? 0 : 1]}`,
        `${lang === "zh" ? "请求 ID" : "Request ID"}: ${identity.request_id}`].join("\n");
    }
    if (action === "dispatch_write") {
      if (!dispatchWritePreviewIsValid(summary)) {
        return `${title}\n${lang === "zh" ? "参数无法核对，请拒绝并重新发起。" : "Arguments cannot be verified. Decline and request again."}`;
      }
      const identity = targets as Record<string, string>;
      return [title, `${lang === "zh" ? "项目" : "Project"}: ${identity.project_id}`,
        `Agent: ${identity.agent_id}`, `${lang === "zh" ? "派遣 ID" : "Dispatch ID"}: ${identity.dispatch_id}`,
        `${lang === "zh" ? "申请权限" : "Requested permission"}: workspace_write`,
        lang === "zh" ? "目标项目可能限制实际权限，请以回执为准。" : "The project may restrict effective permission; check the receipt.",
        `${lang === "zh" ? "任务原文" : "Original task"}:`, summary.assistantTask as string].join("\n");
    }
    if (action === "authorization_upgrade") {
      const projectId = targets && typeof targets === "object" && !Array.isArray(targets)
        ? (targets as Record<string, unknown>).project_id : undefined;
      const scopes = summary.assistantAddedScopes;
      if (!authorizationUpgradePreviewIsValid(summary)) {
        return `${title}\n${lang === "zh" ? "参数无法核对，请拒绝并重新发起。" : "Arguments cannot be verified. Decline and request again."}`;
      }
      return [title, `${lang === "zh" ? "项目" : "Project"}: ${projectId}`,
        lang === "zh" ? "新增权限:" : "Added permissions:", ...(scopes as string[]).map((scope) => `- ${scope}`)].join("\n");
    }
    const targetLines = targets && typeof targets === "object" && !Array.isArray(targets)
      ? Object.entries(targets).filter(([, value]) => typeof value === "string")
        .slice(0, 20).map(([key, value]) => {
          const historyLabels: Record<string, [string, string]> = {
            sourceProjectId: ["项目", "Project"], instanceId: ["实例", "Instance"], assistantAgentId: ["旧助理", "Previous assistant"], syncId: ["原回执", "Original receipt"],
          };
          const label = (action === "history_import" || action === "affairs_sync") && historyLabels[key] ? historyLabels[key][lang === "zh" ? 0 : 1] : key;
          return `${label}: ${String(value).slice(0, key === "base_url" ? 512 : 160)}`;
        }) : [];
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
    const operationDescription = typeof summary.assistantOperationDescription === "string"
      ? summary.assistantOperationDescription.slice(0, 300) : "";
    return [title, operationDescription, ...targetLines, ...teamLines,
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
