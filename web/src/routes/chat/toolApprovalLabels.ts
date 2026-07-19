import type { AgentToolGovernanceRequest } from "../../api/types";

export const TOOL_APPROVAL_LABELS: Record<string, string> = {
  agent_message_tool: "助手消息",
  agent_tool_permission_request_tool: "权限申请",
  apply_diff_edit_tool: "差异编辑",
  apply_patch_tool: "补丁编辑",
  clean_workspace_debris_tool: "清理工作区",
  cli_tool: "命令行",
  code_symbol_tool: "代码结构",
  compress_context_tool: "压缩上下文",
  conversation_log_inspect_tool: "会话日志",
  create_child_session_tool: "创建子会话",
  get_core_context_tool: "核心记忆",
  get_current_goal_tool: "当前目标",
  get_entity_history_tool: "实体历史",
  get_git_status_summary_tool: "仓库状态",
  get_recent_changes_tool: "近期变更",
  glob_tool: "列文件",
  grep_search_tool: "搜索代码",
  image2_generate_tool: "生成图片",
  knowledge_proposal_tool: "知识提案",
  knowledge_query_tool: "知识查询",
  list_child_sessions_tool: "子会话列表",
  plan_update_tool: "更新计划",
  python_lint_tool: "代码检查",
  read_file_tool: "读文件",
  record_learning_tool: "记录学习",
  run_test_for_tool: "运行测试",
  search_error_archive_tool: "错误档案",
  search_memory_tool: "搜索记忆",
  session_reference_query_tool: "引用会话",
  task_create_tool: "创建任务",
  task_list_tool: "任务列表",
  task_start_tool: "开始任务",
  task_stop_tool: "停止任务",
  task_update_tool: "更新任务",
  trigger_self_restart_tool: "重启应用",
  web_fetch_tool: "读取网页",
  web_search_tool: "网页搜索",
  write_file_tool: "写文件",
};

export function toolApprovalLabels(request: AgentToolGovernanceRequest | null | undefined) {
  const delta = request?.policyDelta;
  const tools = [
    ...(delta?.grantTools ?? []),
    ...(delta?.unblockTools ?? []),
    ...(delta?.revokeTools ?? []),
    ...(delta?.blockTools ?? []),
  ]
    .map((tool) => String(tool ?? "").trim())
    .filter(Boolean);
  const seen = new Set<string>();
  const unique = tools.filter((tool) => {
    if (seen.has(tool)) {
      return false;
    }
    seen.add(tool);
    return true;
  });
  return unique.map((tool) => ({
    id: tool,
    label: TOOL_APPROVAL_LABELS[tool] ?? "工具能力",
  }));
}

export function toolApprovalScopeLabel(scope: string | undefined, lang: "zh" | "en") {
  const normalized = String(scope ?? "persistent").trim().toLowerCase();
  if (normalized === "session") {
    return lang === "zh" ? "本会话" : "This session";
  }
  if (normalized === "turn") {
    return lang === "zh" ? "本轮" : "This turn";
  }
  return lang === "zh" ? "长期策略" : "Persistent";
}

export function toolApprovalRiskLabel(level: string | undefined, lang: "zh" | "en") {
  const normalized = String(level ?? "low").trim().toLowerCase();
  if (normalized === "high") {
    return lang === "zh" ? "高风险" : "High risk";
  }
  if (normalized === "medium") {
    return lang === "zh" ? "中风险" : "Medium risk";
  }
  return lang === "zh" ? "低风险" : "Low risk";
}
