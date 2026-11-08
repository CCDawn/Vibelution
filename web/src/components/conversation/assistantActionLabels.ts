export type AssistantActionLabelLanguage = "zh" | "en";

/** Presentation semantics only; never an authorization or execution decision. */
export type AssistantActionKind =
  | "inspect"
  | "source"
  | "search"
  | "change"
  | "dispatch"
  | "browser"
  | "execute"
  | "verify";

/**
 * Single source of truth for personal-assistant action short labels.
 *
 * The Launcher backend folds dozens of actions into the single
 * `personal_assistant_action_tool` / `personal_assistant_manage_tool` tools
 * (core/assistant_runtime/actions.py); the frontend must resolve the specific
 * action from `arguments.action` to avoid showing the generic "处理助理请求"
 * for every step. Process labels (conversationToolSemanticLabel) and approval
 * previews (routes/chat/toolApprovalPreview.ts) both read this table so the
 * wording cannot drift. Missing or unknown actions fall back to the tool-level
 * presentation label.
 */
const ASSISTANT_ACTION_DETAILS: Record<string, readonly [string, string, AssistantActionKind]> = {
  // Meta navigation of the action tool itself.
  index: ["查询动作导航", "Browse action index", "inspect"],
  describe: ["读取动作说明", "Read action details", "inspect"],

  // Read-only project / agent / session / task / source actions.
  projects: ["查询项目", "List projects", "inspect"],
  agents: ["查询可派遣 Agent", "List dispatchable agents", "inspect"],
  agent_list: ["列出 Agent 目录", "List agent catalog", "inspect"],
  agent_get: ["读取 Agent 配置", "Read agent config", "inspect"],
  agent_purge_preview: ["预览 Agent 删除", "Preview agent deletion", "inspect"],
  agent_dispatch_access_get: ["查询接单资格", "Check dispatch access", "inspect"],
  agent_tool_policy_get: ["读取工具策略", "Read tool policy", "inspect"],
  dispatch: ["派遣只读任务", "Dispatch read-only task", "dispatch"],
  dispatch_list: ["列出派遣记录", "List dispatched tasks", "inspect"],
  receipt: ["查询任务回执", "Check task receipt", "inspect"],
  task_list: ["列出活跃任务", "List active tasks", "inspect"],
  source_read: ["读取源码", "Read source", "source"],
  source_search: ["搜索源码", "Search source", "search"],
  session_list: ["列出会话", "List sessions", "inspect"],
  session_get: ["读取会话信息", "Read session info", "inspect"],
  session_config_get: ["读取会话配置", "Read session config", "inspect"],
  session_config_compare: ["比较会话配置", "Compare session config", "inspect"],
  session_parameters_get: ["读取会话参数", "Read session parameters", "inspect"],
  avatar_options: ["列出头像候选", "List avatar options", "inspect"],
  api_catalog: ["查询 API 目录", "Browse API catalog", "inspect"],
  api_describe: ["读取 API 文档", "Read API docs", "inspect"],

  // Read-only management reconciliation / receipts.
  management_receipt: ["查询管理回执", "Check management receipt", "inspect"],
  management_reconcile: ["对账管理操作", "Reconcile management action", "inspect"],
  management_requests: ["查找管理请求", "Find management requests", "inspect"],

  // Read-only team / flow / room / knowledge / research / runtime actions.
  team_list: ["列出团队", "List teams", "inspect"],
  team_get: ["读取团队信息", "Read team info", "inspect"],
  team_status: ["查询团队运行", "Check team run status", "inspect"],
  team_result: ["读取团队结果", "Read team result", "inspect"],
  team_asset_get: ["读取团队资产", "Read team assets", "inspect"],
  team_archive_preview: ["预览团队归档", "Preview team archive", "inspect"],
  team_knowledge_list: ["列出团队知识库", "List team knowledge bases", "inspect"],
  flow_list: ["列出团队 Flow", "List team flows", "inspect"],
  flow_get: ["读取团队 Flow", "Read team flow", "inspect"],
  room_list: ["列出群聊", "List chat rooms", "inspect"],
  room_get: ["读取群聊信息", "Read chat room", "inspect"],
  knowledge_list: ["查询知识库目录", "List knowledge bases", "inspect"],
  knowledge_acl_get: ["读取知识权限", "Read knowledge ACL", "inspect"],
  research_get: ["读取研究进度", "Read research progress", "inspect"],
  runtime_list: ["查询运行列表", "List runs", "inspect"],
  runtime_get: ["读取运行状态", "Read run status", "inspect"],

  // Authorization / legacy handover reads.
  authorization_status: ["查询项目授权", "Check project authorization", "inspect"],
  legacy_observers: ["查询旧任务观察", "List legacy observers", "inspect"],
  legacy_receipts: ["查询旧任务回执", "Check legacy receipts", "inspect"],
  history_source_preview: ["预览旧助理来源", "Preview previous assistant source", "inspect"],
  history_import_receipt: ["查询导入回执", "Check import receipt", "inspect"],
  initial_migration_receipt: ["查询迁移回执", "Check migration receipt", "inspect"],
  reminder_handoff_receipt: ["查询交接回执", "Check handoff receipt", "inspect"],
  knowledge_sync_receipt: ["查询知识同步回执", "Check knowledge sync receipt", "inspect"],
  affairs_sync_receipt: ["查询事务同步回执", "Check affairs sync receipt", "inspect"],
  episodic_sync_receipt: ["查询情景同步回执", "Check episodic sync receipt", "inspect"],

  // Read-only previous-memory discovery actions.
  history_list: ["列出旧历史", "List previous history", "inspect"],
  history_read: ["读取旧历史", "Read previous history", "inspect"],
  history_search: ["搜索旧历史", "Search previous history", "search"],
  history_commentary_read: ["读取旧旁白", "Read previous commentary", "inspect"],
  affairs_conflict_sets: ["查询事务冲突集合", "List affairs conflict sets", "inspect"],
  affairs_conflict_list: ["列出事务冲突", "List affairs conflicts", "inspect"],
  affairs_conflict_read: ["读取事务冲突", "Read affairs conflict", "inspect"],
  episodic_conflict_review: ["审查情景冲突", "Review episodic conflicts", "inspect"],
  personal_memory_list: ["查询个人记忆", "List personal memory", "inspect"],
  legacy_memory_list: ["列出旧记忆归档", "List legacy memory archives", "inspect"],
  legacy_memory_read: ["读取旧记忆", "Read legacy memory", "inspect"],
  preference_proposals: ["查询偏好建议", "List preference suggestions", "inspect"],
  operator_image_options: ["读取图片选项", "Read image options", "inspect"],

  // Browser / appearance reads.
  browser_state: ["查看浏览器状态", "Check browser state", "browser"],
  browser_open: ["打开网页", "Open webpage", "browser"],
  browser_ensure: ["复用或打开网页", "Reuse or open webpage", "browser"],
  browser_select: ["切换网页", "Switch webpage", "browser"],
  browser_show: ["显示网页", "Show webpage", "browser"],
  browser_read: ["读取网页", "Read webpage", "browser"],
  browser_navigate: ["导航网页", "Navigate webpage", "browser"],
  browser_back: ["返回上一页", "Go back", "browser"],
  browser_forward: ["前往下一页", "Go forward", "browser"],
  browser_reload: ["刷新页签", "Reload tab", "browser"],
  browser_scroll: ["滚动网页", "Scroll webpage", "browser"],
  launcher_theme_get: ["读取主题", "Read theme", "inspect"],
  project_status: ["查询项目状态", "Check project status", "inspect"],
  project_lifecycle_receipt: ["查询项目回执", "Check project receipt", "inspect"],

  // Autonomy approvals (kept in sync with routes/chat/autonomyApprovalPreview.ts).
  delegation_goal_create: ["授权有限目标派工", "Authorize bounded goal delegation", "change"],
  delegation_goal_revoke: ["撤销目标派工授权", "Revoke goal delegation", "change"],
  dispatch_derived: ["派遣目标内任务", "Dispatch work within an authorized goal", "dispatch"],
  research_command: ["推进研究任务", "Advance a research task", "execute"],
  authorization_reduce: ["减少当前项目授权", "Reduce current project authorization", "change"],
  authorization_revoke: ["撤销全部项目授权", "Revoke all project authorization", "change"],

  // Managed writes previously inlined in routes/chat/toolApprovalPreview.ts.
  dispatch_cancel: ["停止原派遣任务", "Stop original dispatched task", "dispatch"], runtime_command: ["控制原生运行", "Control native run", "execute"],
  agent_tool_policy_update: ["修改 Agent 工具权限", "Update agent tool permissions", "change"],
  knowledge_acl_revoke: ["撤销知识访问权限", "Revoke knowledge access", "change"],
  flow_save: ["保存团队 Flow 定义", "Save team Flow definition", "change"], flow_start: ["启动已有团队 Flow", "Start existing team Flow", "execute"],
  preference_proposal_accept: ["接受偏好建议", "Accept preference suggestion", "change"],
  preference_proposal_reject: ["拒绝偏好建议", "Reject preference suggestion", "change"],
  operator_image_upload: ["上传图片", "Upload image", "change"],
  operator_image_select: ["选择已有图片", "Select existing image", "change"],
  project_lifecycle: ["管理项目", "Manage project", "execute"],
  dispatch_write: ["派遣 Agent 修改项目", "Dispatch agent to modify project", "dispatch"],
  authorization_upgrade: ["新增项目权限", "Add project permissions", "change"],
  agent_create: ["创建 Agent", "Create agent", "change"], agent_update: ["修改 Agent", "Update agent", "change"],
  agent_parameters_update: ["修改 Agent 参数", "Update agent parameters", "change"],
  agent_prompt_update: ["修改 Agent 提示词", "Update agent prompt", "change"],
  agent_purge: ["永久删除 Agent", "Permanently delete agent", "change"],
  agent_archive: ["归档 Agent", "Archive agent", "change"], agent_dispatch_access_set: ["调整 Agent 接单资格", "Set agent dispatch access", "change"],
  session_create: ["创建会话", "Create session", "change"],
  session_update: ["修改会话", "Update session", "change"], session_stop: ["停止会话任务", "Stop session turn", "change"],
  session_delete: ["删除会话", "Delete session", "change"], knowledge_acl_grant: ["变更知识访问权限", "Change knowledge access", "change"],
  restart: ["重启平台", "Restart platform", "execute"], workflow_recovery_bind: ["绑定失败恢复流程", "Bind failure recovery", "change"],
  workflow_recovery_revoke: ["撤销失败恢复绑定", "Revoke failure recovery", "change"], workflow_start: ["启动工作流", "Start workflow", "execute"],
  team_create: ["创建团队", "Create team", "change"], knowledge_ingest: ["知识入库", "Ingest knowledge", "change"],
  team_run: ["创建团队并运行", "Create and run team", "execute"],
  config_update: ["修改偏好配置", "Update preferences config", "change"],
  provider_add: ["添加模型连接", "Add model provider", "change"], provider_update: ["修改模型连接", "Update model provider", "change"],
  provider_remove: ["移除模型连接", "Remove model provider", "change"], provider_test: ["测试模型连接", "Test model provider", "verify"],
  provider_discover: ["发现连接模型", "Discover provider models", "change"],
  provider_prepare: ["解析模型接入信息", "Parse provider connection details", "inspect"],
  provider_model_resolve: ["发现并配置连接模型", "Discover and configure provider model", "change"],
  provider_catalog: ["查询模型连接目录", "List model providers", "inspect"],
  provider_models: ["列出模型", "List provider models", "inspect"],
  model_update: ["修改模型", "Update model", "change"], model_remove: ["移除模型", "Remove model", "change"],
  model_default: ["设置默认模型", "Set default model", "change"],
  model_add: ["添加模型", "Add model", "change"],
  model_options: ["读取模型选项", "Read model options", "inspect"],
  model_details: ["读取模型详情", "Read model details", "inspect"],
  model_defaults: ["读取默认模型", "Read default models", "inspect"],
  session_pin: ["置顶会话", "Pin session", "change"], session_unpin: ["取消会话置顶", "Unpin session", "change"],
  session_reasoning_update: ["调整会话推理", "Update session reasoning", "change"],
  session_model_parameters_update: ["调整会话模型参数", "Update session model parameters", "change"],
  session_budget_update: ["调整会话预算", "Update session budget", "change"],
  session_archive: ["归档会话", "Archive session", "change"], session_unarchive: ["恢复归档会话", "Unarchive session", "change"],
  team_update: ["修改团队信息", "Update team", "change"], team_archive: ["归档团队及成员", "Archive team and members", "change"],
  room_update: ["修改群聊信息", "Update chat room", "change"],
  assistant_settings: ["读取助理设置", "Read assistant settings", "inspect"],
  assistant_settings_update: ["修改助理偏好", "Update assistant preferences", "change"],
  assistant_model_set: ["切换助理模型", "Change assistant model", "change"],
  dialogue_settings: ["读取对话设置", "Read dialogue settings", "inspect"],
  dialogue_settings_update: ["调整对话偏好", "Update dialogue preferences", "change"],
  settings_catalog: ["读取平台设置", "Read platform settings", "inspect"],
  settings_update: ["修改平台设置", "Update platform settings", "change"],
  configuration_references: ["核对模型引用", "Check model references", "inspect"],
  history_import: ["导入旧助理历史", "Import previous assistant history", "change"],
  affairs_sync: ["同步旧助理事务", "Sync previous assistant affairs", "change"],
  episodic_sync: ["同步情景记忆", "Sync episodic memory", "change"],
  initial_migration_queue: ["开始旧助理迁移", "Start previous assistant migration", "change"],
  knowledge_sync_queue: ["同步旧助理知识", "Sync previous assistant knowledge", "change"],
  knowledge_sync_recover: ["恢复知识同步", "Recover knowledge sync", "change"],
  reminder_handoff_queue: ["交接旧助理提醒", "Transfer previous assistant reminders", "change"],
  reminder_handoff_recover: ["重新授权旧提醒交接", "Reauthorize previous reminder handoff", "change"],
  browser_interact: ["操作网页元素", "Interact with webpage element", "browser"],
  launcher_theme_set: ["设置主题", "Set theme", "change"],
};

/** Keep the approval-preview label-pair contract while sharing the curated action metadata. */
export const ASSISTANT_ACTION_LABELS: Record<string, readonly [string, string]> = Object.fromEntries(
  Object.entries(ASSISTANT_ACTION_DETAILS).map(([action, [zh, en]]) => [action, [zh, en] as const]),
);

const ACTION_AWARE_ASSISTANT_TOOLS = new Set([
  "personal_assistant_action_tool",
  "personal_assistant_manage_tool",
]);

function normalizeAssistantAction(action: unknown): string {
  return typeof action === "string" ? action.trim().toLowerCase().replace(/-/g, "_") : "";
}

function assistantActionDetails(action: unknown) {
  const key = normalizeAssistantAction(action);
  return Object.prototype.hasOwnProperty.call(ASSISTANT_ACTION_DETAILS, key)
    ? ASSISTANT_ACTION_DETAILS[key]
    : null;
}

/** Resolve a specific action label; null preserves the tool-level fallback. */
export function assistantActionLabel(
  action: unknown,
  lang: AssistantActionLabelLanguage = "zh",
): string | null {
  const entry = assistantActionDetails(action);
  return entry ? entry[lang === "en" ? 1 : 0] : null;
}

/**
 * Resolve only an actual action argument on the two multi-action tools. Native
 * transcript command sources can be an array of argument objects. Do not parse
 * summaries, prompt text or JSON strings into an execution fact. Unknown action
 * ids are retained so a caller cannot replace them with stale lifecycle data.
 */
export function assistantActionFromToolArguments(toolName: string, toolArguments: unknown): string | null {
  if (!ACTION_AWARE_ASSISTANT_TOOLS.has(toolName.trim().toLowerCase())) {
    return null;
  }
  const sources = Array.isArray(toolArguments) ? toolArguments : [toolArguments];
  for (const source of sources) {
    if (!source || typeof source !== "object" || Array.isArray(source)) {
      continue;
    }
    const action = normalizeAssistantAction((source as Record<string, unknown>).action);
    if (action) {
      return action;
    }
  }
  return null;
}

export function assistantActionKindForTool(toolName: string, toolArguments: unknown): AssistantActionKind | null {
  return assistantActionDetails(assistantActionFromToolArguments(toolName, toolArguments))?.[2] ?? null;
}

export function assistantActionLabelForTool(
  toolName: string,
  toolArguments: unknown,
  lang: AssistantActionLabelLanguage = "zh",
): string | null {
  return assistantActionLabel(assistantActionFromToolArguments(toolName, toolArguments), lang);
}
