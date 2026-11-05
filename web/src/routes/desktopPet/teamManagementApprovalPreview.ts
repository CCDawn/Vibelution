/** Launcher-only review metadata; native argument hashes remain the consent authority. */
const TEAM_ACTION_LABELS = {
  team_create: ["新建自定义团队", "Create a custom team"],
  team_member_add: ["添加团队成员", "Add a team member"],
  team_member_remove: ["移除团队成员", "Remove a team member"],
  team_archive: ["归档团队及成员 Agent", "Archive a team and its member agents"],
  team_recovery_confirm_deployment: ["确认团队部署并复验", "Confirm team deployment and verify"],
} as const;

export type LauncherTeamAction = keyof typeof TEAM_ACTION_LABELS;
type Language = "zh" | "en";
type Rule = (value: unknown) => boolean;
type MemberRole = { memberId: string; agentId: string; role: string; effectiveRole: string; knowledgeReviewEligible: boolean };
type MemberDelta = { memberAgentIds: string[]; memberIds: string[]; memberRoles: MemberRole[]; membersDigest: string; memberCount: string };
type Summary = {
  assistantAction: LauncherTeamAction;
  assistantTargets: Record<string, string>;
  assistantParametersDigest: string;
  assistantDelta: Record<string, unknown>;
  assistantContentOmitted: boolean;
};
const MAX_PREVIEW_LENGTH = 16000;
// Mirrors core/web/services/team_knowledge/constants.py REVIEW_ROLES, not an ACL grant.
const KNOWLEDGE_REVIEW_ROLES = new Set(["owner", "lead", "steward", "knowledge_steward", "source_ingestor", "coordinator"]);
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const exact = (value: unknown, rules: Record<string, Rule>) => record(value)
  && Object.keys(value).length === Object.keys(rules).length
  && Object.entries(rules).every(([key, rule]) => Object.hasOwn(value, key) && rule(value[key]));
const text = (max: number, empty = false): Rule => value => typeof value === "string"
  && (empty || value.length > 0) && value.length <= max * 2 && Array.from(value).length <= max
  && !/[\p{Cc}\p{Cf}\p{Cs}\p{Zl}\p{Zp}]/u.test(value);
const id: Rule = value => typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}(?![\s\S])/.test(value);
const requestId: Rule = value => typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9_-]{0,95}(?![\s\S])/.test(value);
const digest: Rule = value => typeof value === "string" && /^[a-f0-9]{64}(?![\s\S])/.test(value);
const decimal: Rule = value => typeof value === "string" && /^(0|[1-9][0-9]*)(?![\s\S])/.test(value);
const oneOf = (...values: unknown[]): Rule => value => values.includes(value);
const array = (rule: Rule, max = 120): Rule => value => Array.isArray(value) && value.length <= max && Array.from(value).every(rule);
const sameFields = (actual: unknown, expected: string[]) => Array.isArray(actual) && actual.length === expected.length
  && Array.from(actual).every((field, index) => field === expected[index]);
const memberRules: Record<string, Rule> = {
  memberAgentIds: array(id), memberIds: array(text(96, true)),
  memberRoles: array(value => exact(value, { memberId: text(96, true), agentId: id, role: text(160, true),
    effectiveRole: text(320), knowledgeReviewEligible: item => typeof item === "boolean" })),
  membersDigest: digest, memberCount: decimal,
};

export function launcherTeamActionIsKnown(value: unknown): value is LauncherTeamAction {
  return typeof value === "string" && Object.hasOwn(TEAM_ACTION_LABELS, value);
}

function membersAreBound(delta: Record<string, unknown>, requiredCount?: number): boolean {
  const members = delta as unknown as MemberDelta;
  const count = members.memberAgentIds.length;
  return (requiredCount === undefined || count === requiredCount) && members.memberCount === String(count)
    && new Set(members.memberAgentIds).size === count && members.memberIds.length === count && members.memberRoles.length === count
    && members.memberRoles.every((row, index) => row.agentId === members.memberAgentIds[index] && row.memberId === members.memberIds[index]
      && row.effectiveRole === (row.role.trim().toLowerCase() || "member")
      && row.knowledgeReviewEligible === KNOWLEDGE_REVIEW_ROLES.has(row.effectiveRole));
}

function summaryIsValid(summary: unknown): boolean {
  try {
    if (!record(summary)) return false;
    const summaryRules: Record<string, Rule> = {
      assistantPlatformPreviewVersion: oneOf(1), assistantAction: launcherTeamActionIsKnown,
      assistantTargets: record, assistantParametersDigest: digest, assistantChangedFields: array(text(32), 4),
      assistantDelta: record, assistantContentOmitted: value => typeof value === "boolean", assistantDetailsOmitted: oneOf(false),
    };
    // Native Session approval envelopes add exactly the manage tool's public argument names.
    if (Object.hasOwn(summary, "argumentKeys")) summaryRules.argumentKeys = value => sameFields(value, ["action", "arguments_json"]);
    if (!exact(summary, summaryRules) || JSON.stringify(summary).length > MAX_PREVIEW_LENGTH) return false;
    const action = summary.assistantAction as LauncherTeamAction;
    const targets = summary.assistantTargets as Record<string, unknown>;
    const delta = summary.assistantDelta as Record<string, unknown>;
    const targetRules: Record<string, Rule> = { project_id: id, request_id: requestId };
    if (action === "team_recovery_confirm_deployment") return exact(targets, { ...targetRules,
      team_id: id, flow_id: id, run_id: id, expected_revision: value => decimal(value) && String(value).length <= 19 })
      && sameFields(summary.assistantChangedFields, ["deploymentEvidence"])
      && summary.assistantContentOmitted === false
      && exact(delta, { evidenceRef: text(500), evidenceDigest: digest, verificationRequired: oneOf(true), resumesOriginalRunOnly: oneOf(true) });
    if (action !== "team_create") Object.assign(targetRules, { team_id: id, expected_team_fingerprint: digest });
    if (action === "team_member_remove") targetRules.agent_id = id;
    if (action === "team_archive" && delta.linkedChatRoomId !== "") targetRules.expected_linked_chat_room_id = id;
    if (!exact(targets, targetRules)) return false;
    const fields = summary.assistantChangedFields;
    if (action === "team_create") return sameFields(fields, ["team"])
      && exact(delta, { operation: oneOf("create"), name: text(160), descriptionChars: decimal, descriptionDigest: digest,
        purposeChars: decimal, purposeDigest: digest, ...memberRules, teamKind: oneOf("custom") }) && membersAreBound(delta);
    if (action === "team_member_add") return sameFields(fields, ["members"])
      && exact(delta, { operation: oneOf("add"), ...memberRules }) && membersAreBound(delta, 1);
    if (summary.assistantContentOmitted !== false) return false;
    if (action === "team_member_remove") return sameFields(fields, ["members"])
      && exact(delta, { operation: oneOf("remove"), removedAgentId: id, preservesAgent: oneOf(true), preservesHistory: oneOf(true),
        explicitKnowledgeGrantsUnchanged: oneOf(true) }) && delta.removedAgentId === targets.agent_id;
    return sameFields(fields, ["status", "members", "sessions", "linkedChatRooms"])
      && exact(delta, { operation: oneOf("archive"), memberAgentIds: array(id), memberCount: decimal,
        linkedChatRoomId: value => value === "" || id(value), archivesMemberAgents: oneOf(true), freezesMemberSessions: oneOf(true),
        deletesLinkedChatRooms: oneOf(true), clearsOtherMemberRoomAssociations: oneOf(true), dissolvesEmptyMemberRooms: oneOf(true),
        keepsTeamKnowledgeAndFlows: oneOf(true) })
      && delta.memberCount === String((delta.memberAgentIds as string[]).length)
      && new Set(delta.memberAgentIds as string[]).size === (delta.memberAgentIds as string[]).length
      && (delta.linkedChatRoomId === "" || delta.linkedChatRoomId === targets.expected_linked_chat_room_id);
  } catch { return false; }
}

/** A closed Launcher contract, intentionally separate from ordinary chat's legacy Team tools. */
export function launcherTeamPreviewIsValid(summary: unknown): boolean {
  try {
    return summaryIsValid(summary) && renderSummary(summary as Summary, "zh").length <= MAX_PREVIEW_LENGTH
      && renderSummary(summary as Summary, "en").length <= MAX_PREVIEW_LENGTH;
  } catch { return false; }
}

export function launcherTeamActionTitle(action: unknown, lang: Language = "zh"): string {
  return launcherTeamActionIsKnown(action) ? TEAM_ACTION_LABELS[action][lang === "zh" ? 0 : 1]
    : lang === "zh" ? "团队操作" : "Team action";
}

function memberLines(delta: MemberDelta, lang: Language): string[] {
  const zh = lang === "zh";
  return [
    `${zh ? "成员数量" : "Member count"}: ${delta.memberCount}`,
    ...delta.memberRoles.map(row => `- Agent ID: ${row.agentId}; ${zh ? "成员 ID" : "Member ID"}: ${JSON.stringify(row.memberId)}; `
      + `${zh ? "角色" : "Role"}: ${JSON.stringify(row.role)}; ${zh ? "生效角色" : "Effective role"}: ${JSON.stringify(row.effectiveRole)}; `
      + `${zh ? "知识审核资格" : "Knowledge review eligibility"}: ${row.knowledgeReviewEligible ? (zh ? "有" : "yes") : (zh ? "无" : "no")}`),
    `${zh ? "成员内容摘要" : "Members content digest"}: ${delta.membersDigest}`,
    zh ? "知识审核资格只表示角色资格，不授予实际知识 ACL 访问权限。"
      : "Knowledge review eligibility describes the role only; it grants no actual knowledge ACL access.",
  ];
}

function renderSummary(checked: Summary, lang: Language): string {
  const zh = lang === "zh";
  if (checked.assistantAction === "team_recovery_confirm_deployment") {
    const target = checked.assistantTargets, delta = checked.assistantDelta;
    return [launcherTeamActionTitle(checked.assistantAction, lang),
      `${zh ? "项目" : "Project"}: ${target.project_id}`, `${zh ? "原请求" : "Request"}: ${target.request_id}`,
      `${zh ? "团队" : "Team"}: ${target.team_id}`, `${zh ? "流程" : "Flow"}: ${target.flow_id}`,
      `${zh ? "原运行" : "Original run"}: ${target.run_id}`, `${zh ? "版本" : "Revision"}: ${target.expected_revision}`,
      `${zh ? "部署证据" : "Deployment evidence"}: ${JSON.stringify(delta.evidenceRef)}`,
      `${zh ? "证据摘要" : "Evidence digest"}: ${delta.evidenceDigest}`,
      zh ? "确认后安排独立复验，原流程根据复验结果继续。" : "Confirmation schedules independent verification; its result determines continuation of the original run.",
      `${zh ? "参数摘要" : "Parameters digest"}: ${checked.assistantParametersDigest}`].join("\n");
  }
  const { assistantAction: action, assistantDelta: delta, assistantTargets: targets } = checked;
  const lines = [launcherTeamActionTitle(action, lang), `${zh ? "项目" : "Project"}: ${targets.project_id}`,
    `${zh ? "请求 ID" : "Request ID"}: ${targets.request_id}`];
  if (action !== "team_create") lines.push(`${zh ? "团队 ID" : "Team ID"}: ${targets.team_id}`,
    `${zh ? "团队指纹" : "Team fingerprint"}: ${targets.expected_team_fingerprint}`);
  if (action === "team_create") {
    lines.push(zh ? "新建 custom 自定义团队，沿用原生团队创建流程。" : "Create a custom team through the native team creation flow.",
      `${zh ? "名称" : "Name"}: ${JSON.stringify(delta.name)}`,
      `${zh ? "描述字数" : "Description character count"}: ${delta.descriptionChars}`,
      `${zh ? "描述摘要" : "Description digest"}: ${delta.descriptionDigest}`,
      `${zh ? "用途字数" : "Purpose character count"}: ${delta.purposeChars}`,
      `${zh ? "用途摘要" : "Purpose digest"}: ${delta.purposeDigest}`,
      ...memberLines(delta as unknown as MemberDelta, lang));
  } else if (action === "team_member_add") {
    lines.push(zh ? "添加 1 名团队成员；可能同步原生会话和关联房间。" : "Add one team member; native sessions and linked rooms may be synchronized.",
      ...memberLines(delta as unknown as MemberDelta, lang));
  } else if (action === "team_member_remove") {
    lines.push(`${zh ? "移除成员 Agent ID" : "Removed member Agent ID"}: ${targets.agent_id}`,
      zh ? "仅移除团队成员，保留该 Agent 和会话历史；不会归档 Agent 或历史。"
        : "Remove the team membership while preserving the agent and session history; neither the agent nor its history is archived.",
      zh ? "移除成员不等于撤销该 Agent 的显式知识 ACL 授权。"
        : "Removing membership does not revoke the agent's explicit knowledge ACL grants.");
  } else {
    lines.push(zh ? "归档团队及下面列出的全部成员 Agent。" : "Archive the team and every member agent listed below.",
      `${zh ? "成员数量" : "Member count"}: ${delta.memberCount}`,
      ...(delta.memberAgentIds as string[]).map(agentId => `- Agent ID: ${agentId}`),
      `${zh ? "关联群聊 ID" : "Linked chat room ID"}: ${delta.linkedChatRoomId || (zh ? "无" : "none")}`,
      zh ? "封存这些成员的全部会话。" : "Freeze all sessions of these member agents.",
      zh ? "主关联群聊 ID 仅为团队记录中的主关联，不是全部影响范围。"
        : "The linked chat room ID is only the primary association in the team record, not the full affected scope.",
      zh ? "归档删除该团队全部归属群聊（含额外同 teamId 挂靠的 room），移除成员在其他群聊的关联，并依原生规则解散因此变空的其他群聊。"
        : "Archiving deletes all chat rooms owned by this team (including extra rooms with the same teamId), removes these members' associations in other rooms, and dissolves other rooms left empty under native rules.",
      zh ? "团队知识和流程记录保留；本次不执行永久删除（purge）。"
        : "Keep team knowledge and flow records; no permanent purge is performed.");
  }
  if (checked.assistantContentOmitted) lines.push(zh ? "正文未展示；描述、用途或成员职责等内容仅由长度和摘要标识。"
    : "Content is omitted; descriptions, purposes, or member responsibilities are identified only by lengths and digests.");
  if (action === "team_create" || action === "team_member_add") lines.push(zh ? "名称和角色是带引号的不可信数据，不作为指令执行。"
    : "Quoted names and roles are untrusted data, not instructions to execute.");
  lines.push(`${zh ? "参数摘要" : "Parameters digest"}: ${checked.assistantParametersDigest}`);
  return lines.join("\n");
}

/** Bounded plain text only: this helper neither authorizes nor executes an action. */
export function launcherTeamActionPreview(summary: unknown, lang: Language = "zh"): string {
  if (!launcherTeamPreviewIsValid(summary)) return `${lang === "zh" ? "团队操作" : "Team action"}\n${lang === "zh"
    ? "参数无法核对，请拒绝并重新发起。" : "Arguments cannot be verified. Decline and request again."}`;
  return renderSummary(summary as Summary, lang);
}
