/** Complete native approval metadata; execution remains bound by native argumentsHash. */
export const AUTONOMY_APPROVAL_LABELS = {
  delegation_goal_create: ["授权有限目标派工", "Authorize bounded goal delegation"],
  delegation_goal_revoke: ["撤销目标派工授权", "Revoke goal delegation"],
  dispatch_derived: ["派遣目标内任务", "Dispatch work within an authorized goal"],
  research_command: ["推进研究任务", "Advance a research task"],
  authorization_reduce: ["减少当前项目授权", "Reduce current project authorization"],
  authorization_revoke: ["撤销全部项目授权", "Revoke all project authorization"],
} as const;
type AutonomyAction = keyof typeof AUTONOMY_APPROVAL_LABELS;
type Rule = (value: unknown) => boolean;
type Summary = Record<string, unknown> | null | undefined;
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const exact = (value: unknown, rules: Record<string, Rule>) => record(value)
  && Object.keys(value).length === Object.keys(rules).length
  && Object.entries(rules).every(([key, rule]) => Object.hasOwn(value, key) && rule(value[key]));
const id: Rule = value => typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}(?![\s\S])/.test(value);
const goalId: Rule = value => typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9_-]{0,95}(?![\s\S])/.test(value);
const dispatchId: Rule = value => typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9_-]{0,119}(?![\s\S])/.test(value);
const optionalId: Rule = value => value === "" || id(value);
const digest: Rule = value => typeof value === "string" && /^[a-f0-9]{64}(?![\s\S])/.test(value);
const permission: Rule = value => value === "read_only" || value === "workspace_write";
const decimal = (minimum: bigint, maximum: bigint): Rule => value => typeof value === "string" && value.length <= 19
  && /^(0|[1-9][0-9]*)(?![\s\S])/.test(value) && BigInt(value) >= minimum && BigInt(value) <= maximum;
const singleLine: Rule = value => typeof value === "string" && value.length > 0 && value.length <= 320
  && Array.from(value).length <= 160 && !/[\p{Cc}\p{Cf}\p{Cs}]/u.test(value);
const oneOf = (...values: unknown[]): Rule => value => values.includes(value);
const scopeLabels: Record<string, readonly [string, string]> = {
  "agents:read": ["读取 Agent", "Read agents"], "agents:create": ["创建 Agent", "Create agents"],
  "agents:create:files": ["创建带固定文件工具的 Agent", "Create agents with fixed file tools"],
  "agents:update": ["修改 Agent", "Update agents"], "agents:avatar": ["修改 Agent 头像", "Change agent avatars"],
  "agents:archive": ["归档 Agent", "Archive agents"], "agents:purge": ["永久删除 Agent", "Permanently delete agents"],
  "agents:directory:read": ["发现 Agent 目录", "Read the agent directory"],
  "teams:run": ["创建团队并运行", "Create and run teams"], "teams:read": ["读取团队运行", "Read team runs"],
  "teams:results:read": ["读取团队结果", "Read team results"], "teams:directory:read": ["发现团队目录", "Read the team directory"],
  "teams:manage:read": ["读取团队资产", "Read team assets"], "teams:write": ["修改团队资产", "Update team assets"],
  "rooms:read": ["读取群聊元数据", "Read room metadata"], "platform:describe": ["查询平台接口契约", "Describe platform contracts"],
  "sessions:read": ["读取会话元数据", "Read session metadata"], "sessions:pin": ["置顶会话", "Pin sessions"],
  "sessions:parameters:read": ["读取会话参数", "Read session parameters"],
  "legacy:receipts:read": ["读取旧任务回执", "Read legacy receipts"], "tasks:read": ["读取任务元数据", "Read task metadata"],
  "source:read": ["读取任务来源引用", "Read task source references"], "knowledge:catalog:read": ["发现知识库目录", "Read the knowledge catalog"],
  "operations:read": ["读取平台运行", "Read platform operations"], "operations:control": ["控制平台运行", "Control platform operations"],
  "agents:tool-policy:read": ["读取 Agent 工具权限", "Read agent tool policies"],
  "agents:tool-policy:write": ["修改 Agent 工具权限", "Update agent tool policies"],
  "knowledge:acl:read": ["读取知识访问权限", "Read knowledge access"], "knowledge:acl:write": ["修改知识访问权限", "Update knowledge access"],
  "teams:flows:read": ["读取团队 Flow", "Read team flows"], "teams:flows:write": ["保存团队 Flow", "Save team flows"],
  "teams:flows:run": ["启动团队 Flow", "Start team flows"],
};
const scopes: Rule = value => Array.isArray(value) && value.length > 0 && value.length <= 128
  && value.every(item => typeof item === "string" && Object.hasOwn(scopeLabels, item))
  && value.every((item, index) => index === 0 || value[index - 1] < item);

export function autonomyActionIsKnown(value: unknown): value is AutonomyAction {
  return typeof value === "string" && Object.hasOwn(AUTONOMY_APPROVAL_LABELS, value);
}

function validTargets(action: AutonomyAction, value: unknown): boolean {
  if (action === "delegation_goal_revoke") return exact(value, { goal_id: goalId });
  if (action === "delegation_goal_create") {
    if (!exact(value, { goal_id: goalId, permission_profile: permission, max_tasks: decimal(1n, 32n), ttl_minutes: decimal(1n, 1440n),
      targets: rows => Array.isArray(rows) && rows.length > 0 && rows.length <= 16
        && rows.every(row => exact(row, { project_id: id, agent_id: id })) })) return false;
    const rows = (value as Record<string, unknown>).targets as Record<string, unknown>[];
    return new Set(rows.map(row => JSON.stringify([row.project_id, row.agent_id]))).size === rows.length;
  }
  if (action === "dispatch_derived") return exact(value, {
    goal_id: goalId, project_id: id, agent_id: id, dispatch_id: dispatchId, permission_profile: permission });
  const common = { project_id: id, request_id: goalId };
  if (action === "research_command") {
    if (!exact(value, { ...common, run_id: id, team_id: id, flow_id: id,
      command: oneOf("retry_node", "resolve_human_task", "reconcile_run"), expected_revision: decimal(1n, 9223372036854775807n),
      node_id: optionalId, task_id: optionalId, decision: oneOf("", "accept", "reject", "revise"), checkpoint_id: optionalId })) return false;
    const row = value as Record<string, unknown>;
    return row.command === "retry_node" ? !!row.node_id && !row.task_id && !row.decision && !row.checkpoint_id
      : row.command === "reconcile_run" ? !row.node_id && !row.task_id && !row.decision && !row.checkpoint_id
        : !!row.node_id && !!row.task_id && !!row.decision && Boolean(row.checkpoint_id) === (row.decision === "revise");
  }
  if (!exact(value, { ...common, expected_scopes: scopes, expected_grant_revision: decimal(0n, 9007199254740990n),
    ...(action === "authorization_reduce" ? { remove_scopes: scopes } : {}) })) return false;
  const row = value as Record<string, unknown>;
  return action === "authorization_revoke" || (row.remove_scopes as string[]).length < (row.expected_scopes as string[]).length
    && (row.remove_scopes as string[]).every(scope => (row.expected_scopes as string[]).includes(scope));
}

/** Checks review completeness; native argumentsHash remains the approval authority. */
export function autonomyApprovalPreviewIsValid(summary: Summary): boolean {
  try {
    if (!summary || !autonomyActionIsKnown(summary.assistantAction) || summary.assistantAutonomyPreviewVersion !== 1
      || summary.assistantDetailsOmitted !== false || summary.assistantArgumentsInvalid
      || !digest(summary.assistantParametersDigest) || !validTargets(summary.assistantAction, summary.assistantTargets)) return false;
    const allowed = new Set(["assistantAction", "assistantAutonomyPreviewVersion", "assistantParametersDigest", "assistantDetailsOmitted",
      "assistantTargets", "argumentKeys", "assistantArgumentsInvalid"]);
    if (summary.assistantAction === "dispatch_derived") {
      for (const key of ["assistantTask", "assistantTaskChars", "assistantTaskDigest", "assistantRequestedPermission"]) allowed.add(key);
      const task = summary.assistantTask;
      if (typeof task !== "string" || task.length === 0 || task.length > 24000 || task !== task.trim()
        || /[\p{Cc}\p{Cf}\p{Cs}]/u.test(task.replace(/[\n\t]/g, "")) || !decimal(1n, 12000n)(summary.assistantTaskChars)
        || BigInt(summary.assistantTaskChars as string) !== BigInt(Array.from(task).length) || !digest(summary.assistantTaskDigest)
        || summary.assistantRequestedPermission !== (summary.assistantTargets as Record<string, unknown>).permission_profile) return false;
    }
    if (Object.keys(summary).some(key => !allowed.has(key))
      || Object.hasOwn(summary, "assistantArgumentsInvalid") && summary.assistantArgumentsInvalid !== false
      || Object.hasOwn(summary, "argumentKeys") && (!Array.isArray(summary.argumentKeys) || summary.argumentKeys.length > 32
        || !summary.argumentKeys.every(singleLine) || new Set(summary.argumentKeys).size !== summary.argumentKeys.length)) return false;
    return JSON.stringify(summary).length <= 64000;
  } catch { return false; }
}

/** Plain text inside the existing full-action VUI approval surface; no JSON dump. */
export function autonomyApprovalText(summary: Summary, lang: "zh" | "en" = "zh"): string {
  if (!autonomyApprovalPreviewIsValid(summary)) return lang === "zh"
    ? "参数无法核对，请拒绝并重新发起。关键授权缺少或没有完整展示时不能批准。"
    : "Arguments cannot be verified. Decline and request again; missing or omitted authorization details cannot be approved.";
  const source = summary!;
  const action = source.assistantAction as AutonomyAction, target = source.assistantTargets as Record<string, unknown>;
  const choose = (zh: string, en: string) => lang === "zh" ? zh : en;
  const lines: string[] = [AUTONOMY_APPROVAL_LABELS[action][lang === "zh" ? 0 : 1]];
  const line = (zh: string, en: string, value: unknown) => lines.push(`${choose(zh, en)}: ${String(value)}`);
  const permissionText = (value: unknown) => value === "read_only" ? choose("只读（read_only）", "Read only (read_only)")
    : choose("申请工作区写入（workspace_write）", "Request workspace write (workspace_write)");
  const scopeLines = (zh: string, en: string, values: string[]) => {
    lines.push(`${choose(zh, en)} (${values.length}):`);
    for (const scope of values) lines.push(`- ${scopeLabels[scope][lang === "zh" ? 0 : 1]} (${scope})`);
  };
  if (action === "delegation_goal_create") {
    line("目标 ID", "Goal ID", target.goal_id);
    lines.push(choose("仅授权以下目标范围：", "Authorized targets only:"));
    for (const [index, row] of (target.targets as Record<string, unknown>[]).entries()) {
      lines.push(`${index + 1}. ${choose("项目", "Project")}: ${row.project_id}\n   Agent: ${row.agent_id}`);
    }
    line("权限上限", "Permission ceiling", permissionText(target.permission_profile));
    line("最多派遣任务数", "Maximum dispatched tasks", target.max_tasks);
    line("有效期（分钟）", "Lifetime (minutes)", target.ttl_minutes);
    lines.push(choose("重复请求不延长有效期。每次派工仍受目标权限及原生审批约束，不自动增加工具权限。",
      "Repeats do not extend this lifetime. Each dispatch remains subject to target permissions and native approval; no tool permissions are added automatically."));
  } else if (action === "delegation_goal_revoke") {
    line("撤销目标 ID", "Revoke goal ID", target.goal_id);
    lines.push(choose("停止该目标的新派工授权。已有任务不会被取消，仍需查询原回执或单独停止。",
      "Revoke new dispatches for this goal. Existing tasks are not cancelled; inspect their original receipts or stop them separately."));
  } else if (action === "dispatch_derived") {
    line("绑定授权目标", "Bound authorization goal", target.goal_id);
    line("项目", "Project", target.project_id); line("Agent", "Agent", target.agent_id); line("派遣 ID", "Dispatch ID", target.dispatch_id);
    line("请求权限", "Requested permission", permissionText(target.permission_profile));
    lines.push(choose("实际执行仍受目标权限和本次原生审批约束。", "Execution remains subject to target permissions and this native approval."));
    line("任务全文（码点数）", "Complete task (code points)", source.assistantTaskChars);
    lines.push(source.assistantTask as string);
  } else if (action === "research_command") {
    line("项目", "Project", target.project_id); line("请求 ID", "Request ID", target.request_id);
    line("运行 ID", "Run ID", target.run_id); line("团队", "Team", target.team_id); line("Flow", "Flow", target.flow_id);
    const commands: Record<string, string> = { retry_node: choose("重试节点", "Retry node"),
      resolve_human_task: choose("人工任务裁决", "Resolve human task"), reconcile_run: choose("运行对账", "Reconcile run") };
    line("命令", "Command", commands[target.command as string]);
    if (target.node_id) line("节点", "Node", target.node_id);
    if (target.task_id) line("人工任务", "Human task", target.task_id);
    if (target.decision) line("裁决", "Decision", { accept: choose("接受", "Accept"), reject: choose("拒绝", "Reject"),
      revise: choose("要求修订并创建后继运行", "Request revision and create a successor run") }[target.decision as string]);
    if (target.checkpoint_id) line("修订 checkpoint", "Revision checkpoint", target.checkpoint_id);
    line("预期运行版本", "Expected run revision", target.expected_revision);
    lines.push(choose("受理不代表业务完成；未知结果仅查询原请求，不重复执行。", "Acceptance does not prove business completion. Query the original request for unknown outcomes; do not repeat execution."));
  } else {
    line("项目", "Project", target.project_id); line("请求 ID", "Request ID", target.request_id);
    line("预期授权版本", "Expected grant revision", target.expected_grant_revision);
    const previous = target.expected_scopes as string[];
    scopeLines("原权限", "Previous permissions", previous);
    if (action === "authorization_reduce") {
      const removed = target.remove_scopes as string[];
      scopeLines("撤销权限", "Permissions to remove", removed);
      scopeLines("保留权限", "Permissions retained", previous.filter(scope => !removed.includes(scope)));
      lines.push(choose("仅减少当前已认证主体在此项目的授权。", "Reduce only the current authenticated subject's authorization in this project."));
    } else lines.push(choose("撤销以上全部授权。完成后原凭据立即失效，不能继续业务查询或升级权限，只能核对本次撤销回执。历史记录保留。",
      "Revoke all permissions above. The original credential becomes invalid immediately; business queries and upgrades are denied, and only this revocation receipt remains available. History is retained."));
  }
  return lines.join("\n");
}
