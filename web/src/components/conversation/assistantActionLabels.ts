export type AssistantActionLabelLanguage = "zh" | "en";

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
export const ASSISTANT_ACTION_LABELS: Record<string, readonly [string, string]> = {
  // Meta navigation of the action tool itself.
  index: ["查询动作导航", "Browse action index"],
  describe: ["读取动作说明", "Read action details"],

  // Read-only project / agent / session / task / source actions.
  projects: ["查询项目", "List projects"],
  agents: ["查询可派遣 Agent", "List dispatchable agents"],
  agent_list: ["列出 Agent 目录", "List agent catalog"],
  agent_get: ["读取 Agent 配置", "Read agent config"],
  agent_purge_preview: ["预览 Agent 删除", "Preview agent deletion"],
  agent_dispatch_access_get: ["查询接单资格", "Check dispatch access"],
  agent_tool_policy_get: ["读取工具策略", "Read tool policy"],
  dispatch: ["派遣只读任务", "Dispatch read-only task"],
  dispatch_list: ["列出派遣记录", "List dispatched tasks"],
  receipt: ["查询任务回执", "Check task receipt"],
  task_list: ["列出活跃任务", "List active tasks"],
  source_read: ["读取源码", "Read source"],
  source_search: ["搜索源码", "Search source"],
  session_list: ["列出会话", "List sessions"],
  session_get: ["读取会话信息", "Read session info"],
  session_config_get: ["读取会话配置", "Read session config"],
  session_config_compare: ["比较会话配置", "Compare session config"],
  session_parameters_get: ["读取会话参数", "Read session parameters"],
  avatar_options: ["列出头像候选", "List avatar options"],
  api_catalog: ["查询 API 目录", "Browse API catalog"],
  api_describe: ["读取 API 文档", "Read API docs"],

  // Read-only management reconciliation / receipts.
  management_receipt: ["查询管理回执", "Check management receipt"],
  management_reconcile: ["对账管理操作", "Reconcile management action"],
  management_requests: ["查找管理请求", "Find management requests"],

  // Read-only team / flow / room / knowledge / research / runtime actions.
  team_list: ["列出团队", "List teams"],
  team_get: ["读取团队信息", "Read team info"],
  team_status: ["查询团队运行", "Check team run status"],
  team_result: ["读取团队结果", "Read team result"],
  team_asset_get: ["读取团队资产", "Read team assets"],
  team_archive_preview: ["预览团队归档", "Preview team archive"],
  team_knowledge_list: ["列出团队知识库", "List team knowledge bases"],
  flow_list: ["列出团队 Flow", "List team flows"],
  flow_get: ["读取团队 Flow", "Read team flow"],
  room_list: ["列出群聊", "List chat rooms"],
  room_get: ["读取群聊信息", "Read chat room"],
  knowledge_list: ["查询知识库目录", "List knowledge bases"],
  knowledge_acl_get: ["读取知识权限", "Read knowledge ACL"],
  research_get: ["读取研究进度", "Read research progress"],
  runtime_list: ["查询运行列表", "List runs"],
  runtime_get: ["读取运行状态", "Read run status"],

  // Authorization / legacy handover reads.
  authorization_status: ["查询项目授权", "Check project authorization"],
  legacy_observers: ["查询旧任务观察", "List legacy observers"],
  legacy_receipts: ["查询旧任务回执", "Check legacy receipts"],
  history_source_preview: ["预览旧助理来源", "Preview previous assistant source"],
  history_import_receipt: ["查询导入回执", "Check import receipt"],
  initial_migration_receipt: ["查询迁移回执", "Check migration receipt"],
  reminder_handoff_receipt: ["查询交接回执", "Check handoff receipt"],
  knowledge_sync_receipt: ["查询知识同步回执", "Check knowledge sync receipt"],
  affairs_sync_receipt: ["查询事务同步回执", "Check affairs sync receipt"],
  episodic_sync_receipt: ["查询情景同步回执", "Check episodic sync receipt"],

  // Read-only previous-memory discovery actions.
  history_list: ["列出旧历史", "List previous history"],
  history_read: ["读取旧历史", "Read previous history"],
  history_search: ["搜索旧历史", "Search previous history"],
  history_commentary_read: ["读取旧旁白", "Read previous commentary"],
  affairs_conflict_sets: ["查询事务冲突集合", "List affairs conflict sets"],
  affairs_conflict_list: ["列出事务冲突", "List affairs conflicts"],
  affairs_conflict_read: ["读取事务冲突", "Read affairs conflict"],
  episodic_conflict_review: ["审查情景冲突", "Review episodic conflicts"],
  personal_memory_list: ["查询个人记忆", "List personal memory"],
  legacy_memory_list: ["列出旧记忆归档", "List legacy memory archives"],
  legacy_memory_read: ["读取旧记忆", "Read legacy memory"],
  preference_proposals: ["查询偏好建议", "List preference suggestions"],
  operator_image_options: ["读取图片选项", "Read image options"],

  // Browser / appearance reads.
  browser_state: ["查看浏览器状态", "Check browser state"],
  browser_open: ["打开网页", "Open webpage"],
  browser_read: ["读取网页", "Read webpage"],
  browser_navigate: ["导航网页", "Navigate webpage"],
  browser_back: ["返回上一页", "Go back"],
  browser_forward: ["前往下一页", "Go forward"],
  browser_reload: ["刷新页签", "Reload tab"],
  browser_scroll: ["滚动网页", "Scroll webpage"],
  launcher_theme_get: ["读取主题", "Read theme"],
  project_status: ["查询项目状态", "Check project status"],
  project_lifecycle_receipt: ["查询项目回执", "Check project receipt"],

  // Autonomy approvals (kept in sync with routes/chat/autonomyApprovalPreview.ts).
  delegation_goal_create: ["授权有限目标派工", "Authorize bounded goal delegation"],
  delegation_goal_revoke: ["撤销目标派工授权", "Revoke goal delegation"],
  dispatch_derived: ["派遣目标内任务", "Dispatch work within an authorized goal"],
  research_command: ["推进研究任务", "Advance a research task"],
  authorization_reduce: ["减少当前项目授权", "Reduce current project authorization"],
  authorization_revoke: ["撤销全部项目授权", "Revoke all project authorization"],

  // Managed writes previously inlined in routes/chat/toolApprovalPreview.ts.
  dispatch_cancel: ["停止原派遣任务", "Stop original dispatched task"], runtime_command: ["控制原生运行", "Control native run"],
  agent_tool_policy_update: ["修改 Agent 工具权限", "Update agent tool permissions"],
  knowledge_acl_revoke: ["撤销知识访问权限", "Revoke knowledge access"],
  flow_save: ["保存团队 Flow 定义", "Save team Flow definition"], flow_start: ["启动已有团队 Flow", "Start existing team Flow"],
  preference_proposal_accept: ["接受偏好建议", "Accept preference suggestion"],
  preference_proposal_reject: ["拒绝偏好建议", "Reject preference suggestion"],
  operator_image_upload: ["上传图片", "Upload image"],
  operator_image_select: ["选择已有图片", "Select existing image"],
  project_lifecycle: ["管理项目", "Manage project"],
  dispatch_write: ["派遣 Agent 修改项目", "Dispatch agent to modify project"],
  authorization_upgrade: ["新增项目权限", "Add project permissions"],
  agent_create: ["创建 Agent", "Create agent"], agent_update: ["修改 Agent", "Update agent"],
  agent_parameters_update: ["修改 Agent 参数", "Update agent parameters"],
  agent_prompt_update: ["修改 Agent 提示词", "Update agent prompt"],
  agent_purge: ["永久删除 Agent", "Permanently delete agent"],
  agent_archive: ["归档 Agent", "Archive agent"], agent_dispatch_access_set: ["调整 Agent 接单资格", "Set agent dispatch access"],
  session_create: ["创建会话", "Create session"],
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
  provider_prepare: ["解析模型接入信息", "Parse provider connection details"],
  provider_model_resolve: ["发现并配置连接模型", "Discover and configure provider model"],
  provider_catalog: ["查询模型连接目录", "List model providers"],
  provider_models: ["列出模型", "List provider models"],
  model_update: ["修改模型", "Update model"], model_remove: ["移除模型", "Remove model"],
  model_default: ["设置默认模型", "Set default model"],
  model_add: ["添加模型", "Add model"],
  model_options: ["读取模型选项", "Read model options"],
  model_details: ["读取模型详情", "Read model details"],
  model_defaults: ["读取默认模型", "Read default models"],
  session_pin: ["置顶会话", "Pin session"], session_unpin: ["取消会话置顶", "Unpin session"],
  session_reasoning_update: ["调整会话推理", "Update session reasoning"],
  session_model_parameters_update: ["调整会话模型参数", "Update session model parameters"],
  session_budget_update: ["调整会话预算", "Update session budget"],
  session_archive: ["归档会话", "Archive session"], session_unarchive: ["恢复归档会话", "Unarchive session"],
  team_update: ["修改团队信息", "Update team"], team_archive: ["归档团队及成员", "Archive team and members"],
  room_update: ["修改群聊信息", "Update chat room"],
  assistant_settings: ["读取助理设置", "Read assistant settings"],
  assistant_settings_update: ["修改助理偏好", "Update assistant preferences"],
  assistant_model_set: ["切换助理模型", "Change assistant model"],
  dialogue_settings: ["读取对话设置", "Read dialogue settings"],
  dialogue_settings_update: ["调整对话偏好", "Update dialogue preferences"],
  settings_catalog: ["读取平台设置", "Read platform settings"],
  settings_update: ["修改平台设置", "Update platform settings"],
  configuration_references: ["核对模型引用", "Check model references"],
  history_import: ["导入旧助理历史", "Import previous assistant history"],
  affairs_sync: ["同步旧助理事务", "Sync previous assistant affairs"],
  episodic_sync: ["同步情景记忆", "Sync episodic memory"],
  initial_migration_queue: ["开始旧助理迁移", "Start previous assistant migration"],
  knowledge_sync_queue: ["同步旧助理知识", "Sync previous assistant knowledge"],
  knowledge_sync_recover: ["恢复知识同步", "Recover knowledge sync"],
  reminder_handoff_queue: ["交接旧助理提醒", "Transfer previous assistant reminders"],
  reminder_handoff_recover: ["重新授权旧提醒交接", "Reauthorize previous reminder handoff"],
  browser_interact: ["操作网页元素", "Interact with webpage element"],
  launcher_theme_set: ["设置主题", "Set theme"],
};

/** Resolve a specific action label; returns null so callers can fall back to the tool-level label. */
export function assistantActionLabel(
  action: unknown,
  lang: AssistantActionLabelLanguage = "zh",
): string | null {
  if (typeof action !== "string") {
    return null;
  }
  const key = action.trim().toLowerCase().replace(/-/g, "_");
  const entry = key ? ASSISTANT_ACTION_LABELS[key] : undefined;
  return entry ? entry[lang === "en" ? 1 : 0] : null;
}
