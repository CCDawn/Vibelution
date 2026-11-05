import { TOOL_APPROVAL_LABELS } from "./toolApprovalLabels";
import { ASSISTANT_ACTION_LABELS } from "../../components/conversation/assistantActionLabels";
import { autonomyActionIsKnown, autonomyApprovalText } from "./autonomyApprovalPreview";
import { providerModelApprovalText } from "./providerApprovalPreview";
import { agentConfigurationApprovalActionIsKnown, agentConfigurationApprovalText } from "./agentConfigurationApprovalPreview";
export { providerModelApprovalPreviewIsValid } from "./providerApprovalPreview";
export { autonomyActionIsKnown, autonomyApprovalPreviewIsValid } from "./autonomyApprovalPreview";

const PLATFORM_MANAGE_ACTIONS = new Set(["dispatch_cancel", "runtime_command", "team_update", "agent_tool_policy_update",
  "knowledge_acl_grant", "knowledge_acl_revoke", "flow_save", "flow_start", "agent_dispatch_access_set"]);
type PreviewRule = (value: unknown) => boolean;
const previewRecord = (value: unknown): value is Record<string, unknown> => Boolean(value) && typeof value === "object" && !Array.isArray(value);
const previewText = (value: unknown, max = 160, empty = false) => typeof value === "string"
  && (empty || value.length > 0) && Array.from(value).length <= max && !/[\p{Cc}\p{Cf}\p{Cs}]/u.test(value);
const previewId = (value: unknown, max = 160) => typeof value === "string"
  && value.length <= max && /^[A-Za-z0-9][A-Za-z0-9_.:-]*(?![\s\S])/.test(value);
const previewDecimal = (value: unknown) => typeof value === "string" && /^(0|[1-9][0-9]*)(?![\s\S])/.test(value);
const previewDigest = (value: unknown) => typeof value === "string" && /^[a-f0-9]{64}(?![\s\S])/.test(value);
const previewOneOf = (...values: unknown[]): PreviewRule => value => values.includes(value);
const previewArray = (rule: PreviewRule, max = 512): PreviewRule => value => Array.isArray(value) && value.length <= max && value.every(item => rule(item));
const previewExact = (value: unknown, rules: Record<string, PreviewRule>) => previewRecord(value)
  && Object.keys(value).length === Object.keys(rules).length
  && Object.entries(rules).every(([key, rule]) => Object.hasOwn(value, key) && rule(value[key]));
const previewMap = (keyRule: PreviewRule, valueRule: PreviewRule): PreviewRule => value => previewRecord(value)
  && Object.keys(value).length <= 512 && Object.entries(value).every(([key, entry]) => keyRule(key) && valueRule(entry));
const previewInputId = (value: unknown) => typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9_-]{0,79}(?![\s\S])/.test(value);
const previewRequestId = (value: unknown) => typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9_-]{0,95}(?![\s\S])/.test(value);
const previewTool = (value: unknown) => typeof value === "string" && /^[a-z][a-z0-9_.:-]{1,127}(?![\s\S])/.test(value);
const previewCount = (value: unknown) => previewDecimal(value) && (value as string).length <= 5 && BigInt(value as string) <= 10000n;

export function platformManagementActionIsKnown(value: unknown): boolean {
  return typeof value === "string" && PLATFORM_MANAGE_ACTIONS.has(value);
}

/** Only complete server-produced platform metadata can enable manual approval. */
export function platformManagementPreviewIsValid(summary: Record<string, unknown> | null | undefined): boolean {
  if (!summary || !platformManagementActionIsKnown(summary.assistantAction) || summary.assistantPlatformPreviewVersion !== 1
    || summary.assistantArgumentsInvalid || summary.assistantDetailsOmitted !== false
    || typeof summary.assistantContentOmitted !== "boolean" || !previewDigest(summary.assistantParametersDigest)) return false;
  const permitted = new Set(["argumentKeys", "assistantPlatformPreviewVersion", "assistantAction", "assistantTargets", "assistantParametersDigest",
    "assistantChangedFields", "assistantDelta", "assistantContentOmitted", "assistantDetailsOmitted", "assistantPermissions"]);
  try { if (Object.keys(summary).some(key => !permitted.has(key)) || JSON.stringify(summary).length > 16000) return false; } catch { return false; }
  const action = summary.assistantAction as string;
  if (Object.hasOwn(summary, "assistantPermissions") && !action.startsWith("knowledge_acl_")
    || Object.hasOwn(summary, "argumentKeys") && !previewArray(value => previewText(value, 160), 24)(summary.argumentKeys)) return false;
  const targets = summary.assistantTargets;
  const delta = summary.assistantDelta;
  const fields = summary.assistantChangedFields;
  if (!previewRecord(targets) || !previewRecord(delta) || !Array.isArray(fields) || !fields.length
    || !fields.every(value => typeof value === "string") || new Set(fields).size !== fields.length
    || fields.join("\n") !== [...fields].sort().join("\n")) return false;
  const targetRules: Record<string, PreviewRule> = { project_id: previewId };
  if (action !== "dispatch_cancel") targetRules.request_id = previewRequestId;
  const sameFields = (...expected: string[]) => fields.join("\n") === expected.sort().join("\n");
  if (action === "agent_dispatch_access_set") {
    Object.assign(targetRules, { agent_id: (value: unknown) => previewId(value, 128),
      expected_public_config_hash: previewDigest, expected_eligibility_fingerprint: previewDigest });
    return previewExact(targets, targetRules) && sameFields("enabled")
      && previewExact(delta, { enabled: value => typeof value === "boolean" }) && summary.assistantContentOmitted === false;
  }
  if (action === "dispatch_cancel") {
    targetRules.dispatch_id = value => typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9_-]{0,119}(?![\s\S])/.test(value);
    targetRules.native_task_id = previewId;
    return previewExact(targets, targetRules) && sameFields("stopRequested")
      && previewExact(delta, { operation: previewOneOf("request_stop") }) && summary.assistantContentOmitted === false;
  }
  if (action === "runtime_command") {
    targetRules.kind = previewOneOf("session_turn", "runtime_task", "external_task", "team_run", "supervised_run", "self_evolution_run", "research_run");
    targetRules.resource_id = previewId;
    targetRules.expected_revision = value => typeof value === "string" && /^[A-Za-z0-9_.:-]{1,160}(?![\s\S])/.test(value);
    if (targets.kind === "session_turn") targetRules.session_id = previewId;
    if (targets.kind === "team_run" || targets.kind === "research_run") targetRules.team_id = previewId;
    if (targets.kind === "research_run" || targets.kind === "team_run" && Object.hasOwn(targets, "flow_id")) targetRules.flow_id = previewId;
    return previewExact(targets, targetRules) && sameFields("command")
      && previewExact(delta, { command: previewOneOf("stop", "pause", "resume", "retry", "confirm") })
      && summary.assistantContentOmitted === false;
  }
  if (action.startsWith("knowledge_acl_")) {
    targetRules.knowledge_base_id = value => typeof value === "string" && value.length <= 390
      && /^(?:(?:team|agent):[A-Za-z0-9][A-Za-z0-9_.-]{0,127}:)?[A-Za-z0-9][A-Za-z0-9_.-]{0,127}(?![\s\S])/.test(value);
    targetRules.target_agent_id = previewId;
    targetRules.expected_acl_fingerprint = previewDigest;
    const permissions = delta.permissions;
    return previewExact(targets, targetRules) && sameFields("permissions")
      && previewExact(delta, { permissions: previewArray(previewOneOf("read", "propose", "review"), 3) })
      && Array.isArray(permissions) && permissions.length > 0 && new Set(permissions).size === permissions.length
      && JSON.stringify(summary.assistantPermissions) === JSON.stringify(permissions) && summary.assistantContentOmitted === false;
  }
  if (action === "agent_tool_policy_update") {
    Object.assign(targetRules, { agent_id: previewId, expected_config_revision: previewDecimal,
      expected_agent_updated_at: (value: unknown) => previewText(value, 80), expected_policy_fingerprint: previewDigest,
      expected_registry_version: (value: unknown) => previewText(value, 160), expected_registry_fingerprint: (value: unknown) => previewText(value, 160) });
    const approval = previewOneOf("never", "on_request", "always");
    const scope = previewOneOf("private", "shared", "team_workflow_ledger");
    const rules: Record<string, PreviewRule> = { allowedTools: previewArray(previewTool), preferredTools: previewArray(previewTool), blockedTools: previewArray(previewTool),
      readScopes: previewArray(scope, 256), writeScopes: previewArray(scope, 256), allowedCommandKinds: previewArray(value => previewText(value, 80), 128),
      networkAccess: previewOneOf("none", "restricted", "full", "inherit", "controlled"), mutationAccess: previewOneOf("none", "workspace", "controlled", "inherit", "restricted"),
      delegationAccess: previewOneOf("none", "assigned_only"), approvalOverrides: previewMap(previewTool, approval), maxCallsPerTurn: previewCount,
      maxCallsPerTurnByModelFamily: previewMap(value => previewText(value, 64), previewCount),
      perToolRules: previewMap(previewTool, value => previewExact(value, { approval })) };
    return previewExact(targets, targetRules) && fields.every(key => Object.hasOwn(rules, key))
      && previewExact(delta, Object.fromEntries(fields.map(key => [key, rules[key]]))) && summary.assistantContentOmitted === false;
  }
  if (action === "team_update") {
    Object.assign(targetRules, { team_id: previewId, expected_team_fingerprint: previewDigest });
    if (!fields.every(key => ["name", "description", "purpose", "members"].includes(key))) return false;
    const rules: Record<string, PreviewRule> = {};
    for (const field of fields) {
      if (field === "name") rules.name = value => previewText(value, 160);
      else if (field === "members") Object.assign(rules, { memberAgentIds: previewArray(previewId, 120),
        memberIds: previewArray(value => previewText(value, 96, true), 120), membersMode: previewOneOf("replace"),
        memberRoles: previewArray(value => previewExact(value, { memberId: item => previewText(item, 96, true), agentId: previewId,
          role: item => previewText(item, 160, true), effectiveRole: item => previewText(item, 320),
          knowledgeReviewEligible: item => typeof item === "boolean" }), 120),
        membersDigest: previewDigest, memberCount: previewDecimal });
      else { rules[field + "Chars"] = previewDecimal; rules[field + "Digest"] = previewDigest; }
    }
    if (!previewExact(targets, targetRules) || !previewExact(delta, rules)) return false;
    if (fields.includes("members")) {
      const ids = delta.memberAgentIds as string[];
      const roles = delta.memberRoles as Record<string, unknown>[];
      if ((delta.memberIds as string[]).length !== ids.length || new Set(ids).size !== ids.length
        || BigInt(delta.memberCount as string) !== BigInt(ids.length) || roles.length !== ids.length
        || roles.some((row, index) => row.agentId !== ids[index] || row.memberId !== (delta.memberIds as string[])[index]
          || row.effectiveRole !== ((row.role as string).trim().toLowerCase() || "member"))) return false;
    }
    return true;
  }
  Object.assign(targetRules, { team_id: (value: unknown) => previewId(value, 96), flow_id: previewInputId, expectedRevision: previewDecimal });
  if (!previewExact(targets, targetRules)) return false;
  if (action === "flow_save") {
    if (!sameFields("flow") || summary.assistantContentOmitted !== true || !previewExact(delta, {
      fieldIds: previewArray(previewInputId, 40), fieldKinds: previewArray(previewOneOf("text", "paragraph", "select"), 40),
      requiredFieldIds: previewArray(previewInputId, 40), optionCounts: previewArray(previewDecimal, 40),
      nodeIds: previewArray(previewInputId, 60), nodeKinds: previewArray(previewOneOf("input", "agent", "human", "output", "research", "session"), 60),
      nodeOwners: previewArray(value => previewText(value, 128, true), 60), nodeSourceRefs: previewArray(previewRecord, 60), instructionNodeIds: previewArray(previewInputId, 60),
      definitionDigest: previewDigest, recoveryPolicyDigest: previewDigest })) return false;
    const ids = delta.fieldIds as string[], nodes = delta.nodeIds as string[];
    const sources = delta.nodeSourceRefs as Record<string, unknown>[];
    return new Set(ids).size === ids.length && new Set(nodes).size === nodes.length
      && (delta.fieldKinds as unknown[]).length === ids.length && (delta.optionCounts as unknown[]).length === ids.length
      && (delta.nodeKinds as unknown[]).length === nodes.length && (delta.nodeOwners as unknown[]).length === nodes.length
      && sources.length === nodes.length && sources.every((source, index) => (delta.nodeKinds as string[])[index] === "research"
        ? previewExact(source, { runId: previewId, nodeId: value => previewId(value, 128) })
        : (delta.nodeKinds as string[])[index] === "session" ? previewExact(source, { sessionId: previewId, turnId: previewId, agentId: value => previewText(value, 128) })
        : Object.keys(source).length === 0)
      && (delta.requiredFieldIds as string[]).every(id => ids.includes(id))
      && (delta.instructionNodeIds as string[]).every(id => nodes.includes(id));
  }
  if (!sameFields("values") || BigInt(targets.expectedRevision as string) < 1n || !previewExact(delta, {
    inputIds: previewArray(previewInputId, 40), inputValueLengths: previewMap(previewInputId, previewDecimal),
    inputsDigest: previewDigest, localIntegration: previewOneOf(false) })) return false;
  const ids = delta.inputIds as string[];
  return new Set(ids).size === ids.length && Object.keys(delta.inputValueLengths as object).length === ids.length
    && ids.every(id => Object.hasOwn(delta.inputValueLengths as object, id)) && summary.assistantContentOmitted === (ids.length > 0);
}

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

/** Archive approval binds project, target, stable request and lossless CAS. */
export function agentArchivePreviewIsValid(summary: Record<string, unknown> | null | undefined): boolean {
  if (!summary || summary.assistantAction !== "agent_archive" || summary.assistantArgumentsInvalid
    || summary.assistantDetailsOmitted !== false || summary.assistantPurgeIrreversible) return false;
  return previewExact(summary.assistantTargets, { project_id: previewId, agent_id: value => previewId(value, 128),
    request_id: previewRequestId, expected_config_revision: previewDecimal });
}

/** Purge approval requires the complete identity and fixed irreversible effects. */
export function agentPurgePreviewIsValid(summary: Record<string, unknown> | null | undefined): boolean {
  if (!summary || summary.assistantAction !== "agent_purge" || summary.assistantArgumentsInvalid || summary.assistantDetailsOmitted
    || summary.assistantPurgeIrreversible !== true) return false;
  const targets = summary.assistantTargets;
  if (!targets || typeof targets !== "object" || Array.isArray(targets)) return false;
  const values = targets as Record<string, unknown>;
  const keys = ["project_id", "agent_id", "expected_config_revision", "request_id"];
  const idPattern = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}(?![\s\S])/;
  const effects = ["agent", "sessions", "private_workspace", "team_room_mode_references"];
  return Object.keys(values).length === keys.length && keys.every(key => Object.hasOwn(values, key))
    && typeof values.project_id === "string" && idPattern.test(values.project_id)
    && typeof values.agent_id === "string" && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}(?![\s\S])/.test(values.agent_id)
    && typeof values.request_id === "string" && /^[A-Za-z0-9][A-Za-z0-9_-]{0,95}(?![\s\S])/.test(values.request_id)
    && typeof values.expected_config_revision === "string" && /^(0|[1-9][0-9]*)(?![\s\S])/.test(values.expected_config_revision)
    && Array.isArray(summary.assistantPurgeEffects) && summary.assistantPurgeEffects.length === effects.length
    && effects.every((effect, index) => (summary.assistantPurgeEffects as unknown[])[index] === effect);
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

/** Image approval must identify exactly the reviewed destination. */
export function operatorImageUploadPreviewIsValid(summary: Record<string, unknown> | null | undefined): boolean {
  if (!summary || summary.assistantAction !== "operator_image_upload" || summary.assistantArgumentsInvalid) return false;
  const targets = summary.assistantTargets;
  if (!targets || typeof targets !== "object" || Array.isArray(targets)) return false;
  const values = targets as Record<string, unknown>;
  return Object.keys(values).length === 1 && (values.kind === "avatar" || values.kind === "background");
}

export function browserInteractPreviewIsValid(summary: Record<string, unknown> | null | undefined): boolean {
  if (!summary || summary.assistantAction !== "browser_interact" || summary.assistantArgumentsInvalid || summary.assistantDetailsOmitted) return false;
  const targets = summary.assistantTargets;
  if (!targets || typeof targets !== "object" || Array.isArray(targets)) return false;
  const values = targets as Record<string, unknown>;
  const keys = ["page_id", "snapshot_id", "element_ref", "url", "element_name", "operation", ...(values.operation === "fill" ? ["value"] : [])];
  const uuid = (value: unknown) => typeof value === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value);
  if (Object.keys(values).length !== keys.length || !keys.every(key => Object.hasOwn(values, key))
    || !uuid(values.page_id) || !uuid(values.snapshot_id) || typeof values.element_ref !== "string" || !/^[1-9][0-9]{0,2}$/.test(values.element_ref)
    || typeof values.element_name !== "string" || values.element_name.length > 160 || /\p{Cs}/u.test(values.element_name)
    || typeof values.url !== "string" || values.url.length > 8192 || /[\u0000-\u0020\u007f]/.test(values.url)) return false;
  try { const url = new URL(values.url); if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) return false; } catch { return false; }
  if (values.operation === "fill") return typeof values.value === "string" && Array.from(values.value).length <= 2000 && !/\p{Cs}/u.test(values.value)
    && summary.assistantOperationDescription === "向网页上的所选元素填写所示内容。";
  return values.operation === "click" && summary.assistantOperationDescription === "点击网页上的所选元素。";
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

/** Recovery approval binds the complete source and original authorization. */
export function recoveryPreviewIsValid(summary: Record<string, unknown> | null | undefined): boolean {
  if (!summary || summary.assistantAction !== "reminder_handoff_recover" || summary.assistantArgumentsInvalid || summary.assistantDetailsOmitted
    || summary.assistantOperationDescription !== "重新审批当前来源快照并继续原编号交接；原记录保留。旧进程实际权限与发送者停止尚未证明；不重放已开始或未知的写入。") return false;
  const targets = summary.assistantTargets;
  if (!targets || typeof targets !== "object" || Array.isArray(targets)) return false;
  const values = targets as Record<string, unknown>;
  const keys = ["sourceProjectId", "instanceId", "assistantAgentId", "operationId", "syncId", "sourceSnapshotDigest", "previousAuthorizationHead"];
  if (Object.keys(values).length !== keys.length || !keys.every(key => Object.hasOwn(values, key))) return false;
  const opaque = (value: unknown) => typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}(?![\s\S])/.test(value);
  const digest = (value: unknown) => typeof value === "string" && /^[0-9a-f]{64}(?![\s\S])/.test(value);
  const operation = values.operationId;
  return opaque(values.sourceProjectId) && opaque(values.instanceId) && opaque(values.assistantAgentId)
    && typeof operation === "string" && /^initial-[0-9a-f]{40}(?![\s\S])/.test(operation)
    && values.syncId === `affairs-${operation.slice("initial-".length)}`
    && digest(values.sourceSnapshotDigest) && digest(values.previousAuthorizationHead);
}

/** Only a complete native snapshot can authorize a specific preference decision. */
export function preferenceProposalPreviewIsValid(summary: Record<string, unknown> | null | undefined): boolean {
  if (!summary || typeof summary.assistantAction !== "string" || !["preference_proposal_accept", "preference_proposal_reject"].includes(summary.assistantAction)
    || summary.assistantArgumentsInvalid || summary.assistantDetailsOmitted) return false;
  const targets = summary.assistantTargets;
  const preference = summary.assistantPreference;
  if (!targets || typeof targets !== "object" || Array.isArray(targets)
    || !preference || typeof preference !== "object" || Array.isArray(preference)) return false;
  const ids = targets as Record<string, unknown>, values = preference as Record<string, unknown>;
  if (Object.keys(ids).length !== 2 || !Object.hasOwn(ids, "proposal_id") || !Object.hasOwn(ids, "expected_fingerprint")
    || typeof ids.proposal_id !== "string" || !/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}(?![\s\S])/.test(ids.proposal_id)
    || typeof ids.expected_fingerprint !== "string" || !/^[0-9a-f]{64}(?![\s\S])/.test(ids.expected_fingerprint)
    || Object.keys(values).length !== 3 || !["preferenceType", "candidateValue", "status"].every(key => Object.hasOwn(values, key))
    || values.status !== "pending" || typeof values.preferenceType !== "string" || typeof values.candidateValue !== "string") return false;
  const kind = values.preferenceType, value = values.candidateValue;
  if (!value || Array.from(value).length > 40 || /\p{Cs}/u.test(value)) return false;
  const enums: Record<string, string[]> = { verbosity: ["brief", "compact", "balanced", "detailed"],
    question_initiative: ["low", "normal", "high"], humor: ["off", "light", "natural"], proactive_contact: ["low", "normal", "high"] };
  return kind === "address" ? value.trim().replace(/\s+/gu, " ") === value : (Object.hasOwn(enums, kind) && enums[kind].includes(value));
}

// Managed-write approval labels share the single assistant action table with
// the process labels (conversationToolSemanticLabel) so wording cannot drift;
// read-only actions included there never reach this managed-approval path.
const MANAGE_ACTIONS: Record<string, readonly [string, string]> = ASSISTANT_ACTION_LABELS;

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
    if (action === "provider_model_resolve" || Object.hasOwn(summary, "assistantProviderPreviewVersion")) {
      return providerModelApprovalText(summary, lang);
    }
    if (agentConfigurationApprovalActionIsKnown(action)) return agentConfigurationApprovalText(summary, lang);
    if (autonomyActionIsKnown(action) || Object.hasOwn(summary, "assistantAutonomyPreviewVersion")) {
      return autonomyApprovalText(summary, lang);
    }
    const targets = summary.assistantTargets;
    if (platformManagementActionIsKnown(action) && (summary.assistantPlatformPreviewVersion !== undefined
      || !["team_update", "knowledge_acl_grant"].includes(action))) {
      if (!platformManagementPreviewIsValid(summary)) return `${title}\n${lang === "zh"
        ? "参数无法核对，请拒绝并重新发起。关键权限缺失或未完整展示时不能批准。"
        : "Arguments cannot be verified. Decline and request again; missing or omitted permissions cannot be approved."}`;
      const targetLabels: Record<string, [string, string]> = { project_id: ["项目", "Project"], request_id: ["请求 ID", "Request ID"],
        dispatch_id: ["原派遣 ID", "Original dispatch ID"], native_task_id: ["原生任务 ID", "Native task ID"],
        agent_id: ["Agent", "Agent"], team_id: ["团队", "Team"], flow_id: ["Flow", "Flow"], kind: ["运行类型", "Run kind"],
        resource_id: ["运行 ID", "Run ID"], session_id: ["会话 ID", "Session ID"], knowledge_base_id: ["知识库", "Knowledge base"],
        target_agent_id: ["目标 Agent", "Target agent"], expected_revision: ["预期版本", "Expected revision"], expectedRevision: ["Flow 预期版本", "Expected Flow revision"],
        expected_config_revision: ["预期配置版本", "Expected config revision"], expected_agent_updated_at: ["Agent 原更新时间", "Previous agent update"],
        expected_policy_fingerprint: ["原工具策略指纹", "Previous policy fingerprint"], expected_registry_version: ["工具注册表版本", "Tool registry version"],
        expected_registry_fingerprint: ["工具注册表指纹", "Tool registry fingerprint"], expected_team_fingerprint: ["原团队指纹", "Previous team fingerprint"],
        expected_acl_fingerprint: ["原 ACL 指纹", "Previous ACL fingerprint"],
        expected_public_config_hash: ["原配置快照", "Previous config snapshot"],
        expected_eligibility_fingerprint: ["原接单资格快照", "Previous eligibility snapshot"] };
      const quote = (value: unknown) => JSON.stringify(value, null, 2).replace(/[\p{Cf}\p{Cs}\p{Zl}\p{Zp}]/gu,
        char => `\\u${char.charCodeAt(0).toString(16).padStart(4, "0")}`);
      const deltaLabels: Record<string, [string, string]> = { operation: ["操作", "Operation"], command: ["控制命令", "Control command"],
        enabled: ["允许所示 Agent 接单", "Allow this agent to receive tasks"],
        allowedTools: ["允许工具", "Allowed tools"], preferredTools: ["优先工具", "Preferred tools"], blockedTools: ["禁用工具", "Blocked tools"],
        readScopes: ["读取范围", "Read scopes"], writeScopes: ["写入范围", "Write scopes"], allowedCommandKinds: ["允许命令类别", "Allowed command kinds"],
        networkAccess: ["联网权限", "Network access"], mutationAccess: ["修改权限", "Mutation access"], delegationAccess: ["转派权限", "Delegation access"],
        approvalOverrides: ["审批策略", "Approval overrides"], maxCallsPerTurn: ["每轮调用上限", "Calls per turn"],
        maxCallsPerTurnByModelFamily: ["各模型调用上限", "Calls by model family"], perToolRules: ["单工具审批", "Per-tool approvals"],
        permissions: ["访问权限", "Access permissions"], name: ["团队名称", "Team name"], descriptionChars: ["说明字符数", "Description character count"],
        descriptionDigest: ["说明摘要", "Description digest"], purposeChars: ["用途字符数", "Purpose character count"], purposeDigest: ["用途摘要", "Purpose digest"],
        memberAgentIds: ["成员 Agent ID", "Member agent IDs"], memberIds: ["成员记录 ID", "Membership IDs"], membersMode: ["成员变更方式", "Membership change"],
        memberRoles: ["成员角色与知识资格", "Member roles and knowledge eligibility"],
        membersDigest: ["成员元数据摘要", "Membership digest"], memberCount: ["成员数", "Member count"], fieldIds: ["输入字段 ID", "Input field IDs"],
        fieldKinds: ["输入类型", "Input kinds"], requiredFieldIds: ["必填字段 ID", "Required input IDs"], optionCounts: ["选择项数量", "Option counts"],
        nodeIds: ["节点 ID", "Node IDs"], nodeKinds: ["节点类型", "Node kinds"], nodeOwners: ["节点负责人", "Node owners"],
        nodeSourceRefs: ["原生来源引用", "Native source references"],
        instructionNodeIds: ["含指令节点", "Nodes with instructions"], definitionDigest: ["定义摘要", "Definition digest"], recoveryPolicyDigest: ["恢复策略摘要", "Recovery policy digest"],
        inputIds: ["本次输入 ID", "Submitted input IDs"], inputValueLengths: ["输入字符数", "Input character counts"], inputsDigest: ["输入摘要", "Inputs digest"],
        localIntegration: ["本地合入", "Local integration"] };
      return [title, lang === "zh" ? "对象、版本和权限变化绑定本次原生请求；控制受理不代表任务完成。"
        : "Targets, revisions and permission changes bind this native request; acceptance does not prove completion.",
        ...Object.entries(targets as Record<string, string>).map(([key, value]) => `${targetLabels[key]?.[lang === "zh" ? 0 : 1] ?? key}: ${value}`),
        `${lang === "zh" ? "修改字段" : "Changed fields"}: ${(summary.assistantChangedFields as string[]).join(", ")}`,
        `${lang === "zh" ? "范围与权限变化" : "Scope and permission changes"}:`,
        ...(action === "team_update" && previewRecord(summary.assistantDelta) && Object.hasOwn(summary.assistantDelta, "memberRoles")
          ? [lang === "zh" ? "成员角色逐项绑定成员记录与 Agent；knowledgeReviewEligible 仅表示知识审核、评分及 ACL 管理的角色资格。实际访问仍受原生 ACL、owner、团队及工具策略限制。"
            : "Each role binds its membership and agent. knowledgeReviewEligible denotes role eligibility for knowledge review, rating and ACL management; actual access remains subject to native ACL, owner, team and tool policies."] : []),
        ...Object.entries(summary.assistantDelta as Record<string, unknown>).map(([key, value]) =>
          `${deltaLabels[key]?.[lang === "zh" ? 0 : 1] ?? key} (${key}): ${quote(value)}`),
        `${lang === "zh" ? "参数摘要" : "Parameter digest"}: ${summary.assistantParametersDigest}`,
        summary.assistantContentOmitted ? (lang === "zh" ? "用户正文未记录；此处仅展示完整对象、结构和权限范围。"
          : "User content is not recorded; complete targets, structure and permission scope are shown here.") : ""].filter(Boolean).join("\n");
    }
    if (action === "agent_archive" && summary.assistantDetailsOmitted === false) {
      if (!agentArchivePreviewIsValid(summary)) return `${title}\n${lang === "zh"
        ? "参数无法核对，请拒绝并重新发起。" : "Arguments cannot be verified. Decline and request again."}`;
      const identity = targets as Record<string, string>;
      return [title, `${lang === "zh" ? "项目" : "Project"}: ${identity.project_id}`, `Agent: ${identity.agent_id}`,
        `${lang === "zh" ? "配置版本" : "Config revision"}: ${identity.expected_config_revision}`,
        `${lang === "zh" ? "请求 ID" : "Request ID"}: ${identity.request_id}`].join("\n");
    }
    if (action === "agent_purge") {
      if (!agentPurgePreviewIsValid(summary)) {
        return `${title}\n${lang === "zh" ? "参数无法核对，请拒绝并重新发起。" : "Arguments cannot be verified. Decline and request again."}`;
      }
      const identity = targets as Record<string, string>;
      return [title, `${lang === "zh" ? "项目" : "Project"}: ${identity.project_id}`,
        `Agent: ${identity.agent_id}`,
        `${lang === "zh" ? "配置版本" : "Config revision"}: ${identity.expected_config_revision}`,
        `${lang === "zh" ? "请求 ID" : "Request ID"}: ${identity.request_id}`,
        lang === "zh" ? "此操作不可恢复：删除 Agent 记录、会话和私有工作区，并清理团队、群聊和模式引用。"
          : "This action is irreversible: delete the agent record, sessions, and private workspace, and clear team, chat room, and mode references."].join("\n");
    }
    if (action === "preference_proposal_accept" || action === "preference_proposal_reject") {
      if (!preferenceProposalPreviewIsValid(summary)) return `${title}\n${lang === "zh" ? "建议内容无法核对，请拒绝并重新查询。" : "The suggestion cannot be verified. Decline and query again."}`;
      const preference = summary.assistantPreference as Record<string, string>;
      const identity = targets as Record<string, string>;
      const labels: Record<string, [string, string]> = { verbosity: ["回复长短", "Response length"],
        question_initiative: ["提问频率", "Question initiative"], address: ["称呼", "Address"],
        humor: ["幽默程度", "Humor"], proactive_contact: ["主动联系频率", "Proactive contact"] };
      const value = JSON.stringify(preference.candidateValue).replace(/[\p{Cf}\p{Cc}\p{Cs}\p{Zl}\p{Zp}]/gu,
        char => Array.from({ length: char.length }, (_, index) => `\\u${char.charCodeAt(index).toString(16).padStart(4, "0")}`).join(""));
      const descriptions: Record<string, Record<string, [string, string]>> = {
        verbosity: { brief: ["简短", "Brief"], compact: ["精炼", "Compact"], balanced: ["适中", "Balanced"], detailed: ["详细", "Detailed"] },
        question_initiative: { low: ["较少", "Low"], normal: ["适中", "Normal"], high: ["较多", "High"] },
        humor: { off: ["关闭", "Off"], light: ["少量", "Light"], natural: ["自然", "Natural"] },
        proactive_contact: { low: ["较少", "Low"], normal: ["适中", "Normal"], high: ["较多", "High"] },
      };
      const label = descriptions[preference.preferenceType]?.[preference.candidateValue]?.[lang === "zh" ? 0 : 1];
      return [title, `${lang === "zh" ? "偏好" : "Preference"}: ${labels[preference.preferenceType][lang === "zh" ? 0 : 1]}`,
        `${lang === "zh" ? "建议值" : "Suggested value"}: ${label ? `${label} (${value})` : value}`,
        `${lang === "zh" ? "建议 ID" : "Suggestion ID"}: ${identity.proposal_id}`,
        `${lang === "zh" ? "内容指纹" : "Content fingerprint"}: ${identity.expected_fingerprint}`,
        lang === "zh" ? "建议值是不可信数据；内容变化后本次审批失效。" : "The suggested value is untrusted data; this approval expires if it changes."].join("\n");
    }
    if (action === "browser_interact") {
      if (!browserInteractPreviewIsValid(summary)) return `${title}\n${lang === "zh" ? "参数无法核对，请拒绝并重新读取页面。" : "Arguments cannot be verified. Decline and read the page again."}`;
      const fields = targets as Record<string, string>;
      const quote = (value: string) => JSON.stringify(value).replace(/[\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]/g, char => `\\u${char.charCodeAt(0).toString(16).padStart(4, "0")}`);
      return [title,
        `${lang === "zh" ? "网页" : "Webpage"}: ${quote(fields.url)}`,
        `${lang === "zh" ? "动作" : "Action"}: ${fields.operation === "fill" ? (lang === "zh" ? "填写" : "Fill") : (lang === "zh" ? "点击" : "Click")}`,
        `${lang === "zh" ? "元素" : "Element"}: ${quote(fields.element_name)}`,
        ...(fields.operation === "fill" ? [`${lang === "zh" ? "填写内容" : "Value"}: ${quote(fields.value)}`] : []),
        `${lang === "zh" ? "页面 ID" : "Page ID"}: ${fields.page_id}`,
        `${lang === "zh" ? "快照 ID" : "Snapshot ID"}: ${fields.snapshot_id}`,
        `${lang === "zh" ? "元素引用" : "Element reference"}: ${fields.element_ref}`,
        lang === "zh" ? "仅允许这一次网页操作；操作后仍需读取页面核对结果。" : "Allow only this webpage action; read the page again to verify its result.",
      ].join("\n");
    }
    if (action === "reminder_handoff_recover") {
      if (!recoveryPreviewIsValid(summary)) {
        return `${title}\n${lang === "zh" ? "参数无法核对，请拒绝并重新发起。" : "Arguments cannot be verified. Decline and request again."}`;
      }
      const identity = targets as Record<string, string>;
      return [title,
        lang === "zh" ? "重新审批当前来源快照并继续原编号交接；原记录保留。" : "Reapprove the current source snapshot and continue the original handoff; the original record is retained.",
        `${lang === "zh" ? "来源项目" : "Source project"}: ${identity.sourceProjectId}`,
        `${lang === "zh" ? "来源实例" : "Source instance"}: ${identity.instanceId}`,
        `${lang === "zh" ? "来源助理" : "Source assistant"}: ${identity.assistantAgentId}`,
        `${lang === "zh" ? "原操作 ID" : "Original operation ID"}: ${identity.operationId}`,
        `${lang === "zh" ? "原同步 ID" : "Original sync ID"}: ${identity.syncId}`,
        `${lang === "zh" ? "当前来源快照摘要" : "Current source snapshot digest"}: ${identity.sourceSnapshotDigest}`,
        `${lang === "zh" ? "原授权 head" : "Previous authorization head"}: ${identity.previousAuthorizationHead}`,
        lang === "zh" ? "旧进程实际权限与发送者停止尚未证明；不重放已开始或未知的写入。"
          : "The old process's effective permissions and sender shutdown have not been proven; started or unknown writes will not be replayed."].join("\n");
    }
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
    if (action === "operator_image_upload") {
      if (!operatorImageUploadPreviewIsValid(summary)) {
        return `${title}\n${lang === "zh" ? "参数无法核对，请拒绝并重新发起。" : "Arguments cannot be verified. Decline and request again."}`;
      }
      const kind = (targets as Record<string, unknown>).kind;
      return lang === "zh"
        ? `${title}\n选择图片后上传并应用为${kind === "avatar" ? "头像" : "壁纸"}；取消不修改。`
        : `${title}\nChoose an image to upload and apply as your ${kind === "avatar" ? "avatar" : "background"}. Cancel to leave it unchanged.`;
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
