import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";

import {
  agentPurgePreviewIsValid,
  autonomyActionIsKnown,
  autonomyApprovalPreviewIsValid,
  platformManagementActionIsKnown,
  platformManagementPreviewIsValid,
  preferenceProposalPreviewIsValid,
  managementApprovalActionIsKnown,
  authorizationUpgradePreviewIsValid,
  browserInteractPreviewIsValid,
  dispatchWritePreviewIsValid,
  launcherAgentCreatePreviewIsValid,
  projectLifecyclePreviewIsValid,
  recoveryPreviewIsValid,
  toolApprovalActionPreview,
  toolApprovalCodexButtonLabels,
  toolApprovalCodexTitle,
  toolApprovalDisplayName,
  toolApprovalSessionGrantDescription,
} from "./toolApprovalPreview";

describe("Launcher autonomy approvals use the existing complete VUI preview", () => {
  const actions = ["delegation_goal_create", "delegation_goal_revoke", "dispatch_derived", "research_command", "authorization_reduce", "authorization_revoke"];
  it.each(actions)("registers the exact native action %s and rejects incomplete previews", action => {
    expect(autonomyActionIsKnown(action)).toBe(true);
    expect(managementApprovalActionIsKnown(action)).toBe(true);
    expect(autonomyApprovalPreviewIsValid({ assistantAction: action })).toBe(false);
    expect(toolApprovalActionPreview({ assistantAction: action }, "personal_assistant_manage_tool", "zh")).toContain("无法核对");
  });
  it("renders the entire derived task through the ordinary formatter in both languages", () => {
    const task = "🧭".repeat(11999) + "终";
    const summary = { assistantAction: "dispatch_derived", assistantAutonomyPreviewVersion: 1, assistantParametersDigest: "a".repeat(64),
      assistantDetailsOmitted: false, assistantTargets: { goal_id: "goal-a", project_id: "project-a", agent_id: "agent-a",
        dispatch_id: "dispatch-a", permission_profile: "workspace_write" }, assistantTask: task, assistantTaskChars: "12000",
      assistantTaskDigest: "b".repeat(64), assistantRequestedPermission: "workspace_write" };
    for (const lang of ["zh", "en"] as const) {
      const text = toolApprovalActionPreview(summary, "personal_assistant_manage_tool", lang);
      expect(text).toContain(task);
      for (const value of ["goal-a", "project-a", "agent-a", "dispatch-a", "workspace_write"]) expect(text).toContain(value);
      expect(text).not.toContain("[object Object]");
    }
  });
  it("cannot disguise autonomy metadata as a legacy action or invent an action alias", () => {
    for (const action of ["agent_update", "delegated_goal_create"]) {
      const text = toolApprovalActionPreview({ assistantAction: action, assistantAutonomyPreviewVersion: 1,
        assistantTargets: { goal_id: "SECRET" } }, "personal_assistant_manage_tool", "zh");
      expect(text).toContain("无法核对");
      expect(text).not.toContain("SECRET");
    }
    expect(managementApprovalActionIsKnown("delegated_goal_create")).toBe(false);
  });
  it("wires completeness into the manual accept gate and full-action surface without altering native policy", () => {
    const source = readFileSync(new URL("../desktopPet/LauncherAssistantRoute.tsx", import.meta.url), "utf8");
    const guard = source.slice(source.indexOf("function approvalAcceptDisabled"), source.indexOf("// Decode only JSON string tokens"));
    expect(guard).toContain("autonomyActionIsKnown(summary?.assistantAction)");
    expect(guard).toContain('Object.hasOwn(summary || {}, "assistantAutonomyPreviewVersion")');
    expect(guard).toContain("!autonomyApprovalPreviewIsValid(summary)");
    expect(source).toContain("fullActionPreview={approval.toolName === \"personal_assistant_manage_tool\" && (autonomyActionIsKnown(");
    expect(source).toContain("approveDisabled={approvalAcceptDisabled(approval)}");
  });
});

describe("Launcher platform approval metadata", () => {
  const summary = { assistantPlatformPreviewVersion: 1, assistantAction: "dispatch_cancel",
    assistantTargets: { project_id: "project-a", dispatch_id: "dispatch-a", native_task_id: "task-a" },
    assistantParametersDigest: "a".repeat(64), assistantChangedFields: ["stopRequested"],
    assistantDelta: { operation: "request_stop" }, assistantContentOmitted: false, assistantDetailsOmitted: false };
  it("requires complete original native identity before reviewing a cancellation", () => {
    expect(platformManagementActionIsKnown("dispatch_cancel")).toBe(true);
    expect(platformManagementPreviewIsValid(summary)).toBe(true);
    for (const lang of ["zh", "en"] as const) {
      const preview = toolApprovalActionPreview(summary, "personal_assistant_manage_tool", lang);
      for (const value of ["project-a", "dispatch-a", "task-a", "a".repeat(64)]) expect(preview).toContain(value);
    }
    for (const invalid of [{ ...summary, assistantPlatformPreviewVersion: "1" },
      { ...summary, assistantPlatformPreviewVersion: 2 }, { ...summary, assistantPlatformPreviewVersion: undefined },
      { ...summary, assistantTargets: { ...summary.assistantTargets, approved: "true" } },
      { ...summary, assistantTargets: { project_id: "project-a", dispatch_id: "dispatch-a" } },
      { ...summary, assistantDetailsOmitted: true }, { ...summary, assistantParametersDigest: "bad" },
      { ...summary, assistantDelta: { operation: "request_stop", approved: true } }]) {
      expect(platformManagementPreviewIsValid(invalid)).toBe(false);
      expect(toolApprovalActionPreview(invalid, "personal_assistant_manage_tool", "zh")).toContain("参数无法核对");
    }
  });
  const platform = (action: string, targets: Record<string, string>, delta: Record<string, unknown>, fields: string[], content = false) => ({
    assistantPlatformPreviewVersion: 1, assistantAction: action, assistantTargets: { project_id: "project-a", request_id: "request-a", ...targets },
    assistantParametersDigest: "a".repeat(64), assistantChangedFields: [...fields].sort(), assistantDelta: delta,
    assistantContentOmitted: content, assistantDetailsOmitted: false });
  const policyDelta = { allowedTools: ["read_file_tool", "write_file_tool"], preferredTools: ["read_file_tool"], blockedTools: ["exec_command"],
    readScopes: ["private", "shared"], writeScopes: ["private"], allowedCommandKinds: ["read"], networkAccess: "restricted",
    mutationAccess: "workspace", delegationAccess: "assigned_only", approvalOverrides: { write_file_tool: "always" },
    maxCallsPerTurn: "12", maxCallsPerTurnByModelFamily: { "model-family": "7" }, perToolRules: { read_file_tool: { approval: "never" } } };
  const policy = platform("agent_tool_policy_update", { agent_id: "agent-a", expected_config_revision: "9007199254740993",
    expected_agent_updated_at: "2026-11-02T00:00:00Z", expected_policy_fingerprint: "b".repeat(64),
    expected_registry_version: "registry-v1", expected_registry_fingerprint: "c".repeat(64) }, policyDelta, Object.keys(policyDelta));
  const flow = platform("flow_save", { team_id: "team-a", flow_id: "flow-a", expectedRevision: "9007199254740993" }, {
    fieldIds: ["goal"], fieldKinds: ["text"], requiredFieldIds: ["goal"], optionCounts: ["0"], nodeIds: ["work"],
    nodeKinds: ["agent"], nodeOwners: ["agent-a"], nodeSourceRefs: [{}], instructionNodeIds: ["work"], definitionDigest: "b".repeat(64),
    recoveryPolicyDigest: "c".repeat(64) }, ["flow"], true);
  const start = platform("flow_start", { team_id: "team-a", flow_id: "flow-a", expectedRevision: "9007199254740993" }, {
    inputIds: ["goal"], inputValueLengths: { goal: "17" }, inputsDigest: "d".repeat(64), localIntegration: false }, ["values"], true);
  const team = platform("team_update", { team_id: "team-a", expected_team_fingerprint: "b".repeat(64) }, {
    name: "Team", descriptionChars: "10", descriptionDigest: "c".repeat(64), memberAgentIds: ["member-a"], memberIds: [""],
    memberRoles: [{ memberId: "", agentId: "member-a", role: "member", effectiveRole: "member", knowledgeReviewEligible: false }],
    membersMode: "replace", membersDigest: "d".repeat(64), memberCount: "1" }, ["name", "description", "members"], true);
  const acl = (action: string) => ({ ...platform(action, { knowledge_base_id: "team:team-a:kb-a", target_agent_id: "agent-a",
    expected_acl_fingerprint: "c".repeat(64) }, { permissions: ["read", "review"] }, ["permissions"]), assistantPermissions: ["read", "review"] });
  const runtime = platform("runtime_command", { kind: "team_run", resource_id: "run-a", team_id: "team-a", flow_id: "flow-a",
    expected_revision: "9007199254740993" }, { command: "stop" }, ["command"]);
  it.each([runtime, team, policy, acl("knowledge_acl_grant"), acl("knowledge_acl_revoke"), flow, start])("verifies complete %j metadata and displays both languages", value => {
    expect(platformManagementPreviewIsValid(value)).toBe(true);
    for (const lang of ["zh", "en"] as const) {
      const preview = toolApprovalActionPreview(value, "personal_assistant_manage_tool", lang);
      expect(preview).not.toContain("参数无法核对");
      for (const target of Object.values(value.assistantTargets)) expect(preview).toContain(target);
      for (const field of Object.keys(value.assistantDelta)) expect(preview).toContain(field);
    }
  });
  it("keeps exact large revisions and every ToolPolicy permission field visible", () => {
    const zh = toolApprovalActionPreview(policy, "personal_assistant_manage_tool", "zh");
    const en = toolApprovalActionPreview(policy, "personal_assistant_manage_tool", "en");
    for (const text of ["9007199254740993", "read_file_tool", "write_file_tool", "exec_command", "private", "shared", "always", "never", "assigned_only"]) {
      expect(zh).toContain(text); expect(en).toContain(text);
    }
    expect(zh).toContain("联网权限"); expect(en).toContain("Network access");
    expect(zh).not.toContain("9007199254740992");
    expect(platformManagementPreviewIsValid({ ...policy, assistantTargets: { ...policy.assistantTargets, expected_config_revision: 9007199254740993 } })).toBe(false);
    for (const patch of [{ approvalGrants: ["forged"] }, { perToolRules: { read_file_tool: { approval: "never", approvalGrants: ["forged"] } } },
      { blockedCommandPatternsCount: "1", blockedCommandPatternsDigest: "a".repeat(64) }, { allowedTools: ["UNKNOWN TOOL"] },
      { maxCallsPerTurn: 12 }, { unexpectedPermission: "full" }]) {
      const invalid = { ...policy, assistantDelta: { ...policy.assistantDelta, ...patch } };
      expect(platformManagementPreviewIsValid(invalid)).toBe(false);
    }
  });
  it("permits fixed Flow content isolation but rejects missing structure, mismatched inputs or extra targets", () => {
    expect(toolApprovalActionPreview(flow, "personal_assistant_manage_tool", "zh")).toContain("用户正文未记录");
    for (const invalid of [{ ...flow, assistantDelta: { ...flow.assistantDelta, nodeOwners: [] } },
      { ...flow, assistantDelta: { ...flow.assistantDelta, instructionNodeIds: ["unknown"] } },
      { ...flow, assistantDelta: { ...flow.assistantDelta, fieldKinds: [] } },
      { ...flow, assistantContentOmitted: false }, { ...flow, assistantDetailsOmitted: true },
      { ...start, assistantDelta: { ...start.assistantDelta, inputValueLengths: {} } },
      { ...start, assistantDelta: { ...start.assistantDelta, localIntegration: true } },
      { ...team, assistantDelta: { ...team.assistantDelta, memberCount: "2" } },
      { ...runtime, assistantTargets: { ...runtime.assistantTargets, session_id: "extra-session" } },
      { ...runtime, assistantTargets: { ...runtime.assistantTargets, kind: "unknown" } },
      { ...start, assistantTargets: { ...start.assistantTargets, approved: "true" } }]) {
      expect(platformManagementPreviewIsValid(invalid)).toBe(false);
      expect(toolApprovalActionPreview(invalid, "personal_assistant_manage_tool", "en")).toContain("Arguments cannot be verified");
    }
  });
  it("keeps ordinary legacy Team and ACL preview paths without the Launcher marker", () => {
    for (const value of [{ assistantAction: "team_update", assistantTargets: { team_id: "team-a" }, assistantChangedFields: ["name"] },
      { assistantAction: "knowledge_acl_grant", assistantTargets: { knowledge_base_id: "kb-a" }, assistantPermissions: ["read"] }]) {
      expect(platformManagementPreviewIsValid(value)).toBe(false);
      expect(toolApprovalActionPreview(value, "personal_assistant_manage_tool", "zh")).not.toContain("参数无法核对");
    }
  });
  it("shows paired member and lead roles with native role eligibility, without claiming actual ACL access", () => {
    const member = { ...team, assistantDelta: { ...team.assistantDelta, memberIds: ["membership-a"],
      memberRoles: [{ memberId: "membership-a", agentId: "member-a", role: "member", effectiveRole: "member", knowledgeReviewEligible: false }] } };
    const lead = { ...member, assistantDelta: { ...member.assistantDelta,
      memberRoles: [{ memberId: "membership-a", agentId: "member-a", role: " LEAD ", effectiveRole: "lead", knowledgeReviewEligible: true }] } };
    expect(platformManagementPreviewIsValid(member)).toBe(true);
    expect(platformManagementPreviewIsValid(lead)).toBe(true);
    for (const lang of ["zh", "en"] as const) {
      const memberPreview = toolApprovalActionPreview(member, "personal_assistant_manage_tool", lang);
      const leadPreview = toolApprovalActionPreview(lead, "personal_assistant_manage_tool", lang);
      for (const value of ["membership-a", "member-a", "knowledgeReviewEligible"]) {
        expect(memberPreview).toContain(value); expect(leadPreview).toContain(value);
      }
      expect(memberPreview).toContain('"knowledgeReviewEligible": false');
      expect(leadPreview).toContain('"knowledgeReviewEligible": true');
      expect(leadPreview).toContain('"effectiveRole": "lead"');
      expect(leadPreview).not.toBe(memberPreview);
      expect(leadPreview).toContain(lang === "zh" ? "实际访问仍受原生 ACL" : "actual access remains subject to native ACL");
    }
    const role = lead.assistantDelta.memberRoles[0];
    for (const rows of [undefined, [], [{ ...role, memberId: "wrong-membership" }], [{ ...role, agentId: "wrong-agent" }],
      [{ ...role, role: "lead\u202e" }], [{ ...role, effectiveRole: "member" }],
      [{ ...role, knowledgeReviewEligible: "true" }], [{ ...role, extraPermission: true }]]) {
      const invalid = { ...lead, assistantDelta: { ...lead.assistantDelta, memberRoles: rows } };
      expect(platformManagementPreviewIsValid(invalid)).toBe(false);
      expect(toolApprovalActionPreview(invalid, "personal_assistant_manage_tool", "zh")).toContain("参数无法核对");
    }
    expect(platformManagementPreviewIsValid({ ...lead, assistantDetailsOmitted: true })).toBe(false);
  });
  it("requires every native Session, Turn or research source reference for a supervising Flow", () => {
    for (const [kind, source] of [["session", { sessionId: "session-a", turnId: "turn-a", agentId: "source-agent" }],
      ["research", { runId: "research-a", nodeId: "node-a" }]] as const) {
      const supervised = { ...flow, assistantDelta: { ...flow.assistantDelta, fieldIds: [], fieldKinds: [], requiredFieldIds: [], optionCounts: [],
        nodeKinds: [kind], nodeOwners: [""], nodeSourceRefs: [source], instructionNodeIds: [] } };
      expect(platformManagementPreviewIsValid(supervised)).toBe(true);
      for (const value of Object.values(source)) expect(toolApprovalActionPreview(supervised, "personal_assistant_manage_tool", "zh")).toContain(value);
      expect(platformManagementPreviewIsValid({ ...supervised, assistantDelta: { ...supervised.assistantDelta, nodeSourceRefs: [{}] } })).toBe(false);
      expect(platformManagementPreviewIsValid({ ...supervised, assistantDelta: { ...supervised.assistantDelta, nodeSourceRefs: [{ ...source, approved: true }] } })).toBe(false);
    }
  });
});

describe("toolApprovalPreview", () => {
  const purgeSummary = {
    assistantAction: "agent_purge",
    assistantTargets: { project_id: "project-1", agent_id: "agent-1", expected_config_revision: "42", request_id: "purge-1" },
    assistantPurgeIrreversible: true,
    assistantPurgeEffects: ["agent", "sessions", "private_workspace", "team_room_mode_references"],
  };

  it("shows the complete irreversible agent purge request and fixed effects", () => {
    expect(agentPurgePreviewIsValid(purgeSummary)).toBe(true);
    expect(managementApprovalActionIsKnown("agent_purge")).toBe(true);
    const zh = toolApprovalActionPreview(purgeSummary, "personal_assistant_manage_tool", "zh");
    const en = toolApprovalActionPreview(purgeSummary, "personal_assistant_manage_tool", "en");
    for (const value of ["永久删除 Agent", "项目: project-1", "Agent: agent-1", "配置版本: 42", "请求 ID: purge-1",
      "不可恢复", "Agent 记录", "会话", "私有工作区", "团队、群聊和模式引用"]) expect(zh).toContain(value);
    for (const value of ["Permanently delete agent", "Project: project-1", "Agent: agent-1", "Config revision: 42", "Request ID: purge-1",
      "irreversible", "agent record", "sessions", "private workspace", "team, chat room, and mode references"]) expect(en).toContain(value);
    for (const revision of ["0", "9007199254740993", "1".repeat(30)]) {
      const summary = { ...purgeSummary, assistantTargets: { ...purgeSummary.assistantTargets, expected_config_revision: revision } };
      expect(agentPurgePreviewIsValid(summary)).toBe(true);
      expect(toolApprovalActionPreview(summary, "personal_assistant_manage_tool")).toContain(`配置版本: ${revision}`);
    }
    const boundaryTargets = { project_id: "p".repeat(160), agent_id: "a".repeat(128), expected_config_revision: "0", request_id: "r".repeat(96) };
    const boundarySummary = { ...purgeSummary, assistantTargets: boundaryTargets };
    expect(agentPurgePreviewIsValid(boundarySummary)).toBe(true);
    for (const value of Object.values(boundaryTargets)) expect(toolApprovalActionPreview(boundarySummary, "personal_assistant_manage_tool")).toContain(value);
  });

  it("rejects incomplete or altered purge identities, revisions, and effects", () => {
    const targets = purgeSummary.assistantTargets;
    const invalid = [
      { ...purgeSummary, assistantTargets: undefined }, { ...purgeSummary, assistantTargets: [] },
      ...Object.keys(targets).map(key => ({ ...purgeSummary, assistantTargets: Object.fromEntries(Object.entries(targets).filter(([name]) => name !== key)) })),
      { ...purgeSummary, assistantTargets: { ...targets, extra: "forged" } },
      ...["purge.1", "purge:1"].map(request_id => ({ ...purgeSummary, assistantTargets: { ...targets, request_id } })),
      ...["project_id", "agent_id", "request_id"].flatMap(key => ["", "forged\n", "bad/id", "hidden\u202e", "x".repeat(key === "request_id" ? 97 : key === "agent_id" ? 129 : 161)]
        .map(value => ({ ...purgeSummary, assistantTargets: { ...targets, [key]: value } }))),
      ...[undefined, 42, -1, "-1", "+1", "01", "1.0", "1e3", " 1", "1\n", "", "NaN"]
        .map(value => ({ ...purgeSummary, assistantTargets: { ...targets, expected_config_revision: value } })),
      ...[undefined, false, "true"].map(value => ({ ...purgeSummary, assistantPurgeIrreversible: value })),
      ...[undefined, [], [...purgeSummary.assistantPurgeEffects].reverse(), purgeSummary.assistantPurgeEffects.slice(1),
        [...purgeSummary.assistantPurgeEffects, "all_history"], ["agent", "sessions", "private_workspace", "all_history"]]
        .map(value => ({ ...purgeSummary, assistantPurgeEffects: value })),
      { ...purgeSummary, assistantArgumentsInvalid: true }, { ...purgeSummary, assistantDetailsOmitted: true },
    ];
    expect(agentPurgePreviewIsValid(null)).toBe(false);
    expect(agentPurgePreviewIsValid(undefined)).toBe(false);
    expect(agentPurgePreviewIsValid({ ...purgeSummary, assistantAction: "agent_archive" })).toBe(false);
    for (const summary of invalid) {
      expect(agentPurgePreviewIsValid(summary)).toBe(false);
      expect(toolApprovalActionPreview(summary, "personal_assistant_manage_tool", "zh")).toContain("参数无法核对");
      expect(toolApprovalActionPreview(summary, "personal_assistant_manage_tool", "en")).toContain("Arguments cannot be verified");
    }
  });

  it("binds preference decisions to complete pending native values", () => {
    const summary = { assistantAction: "preference_proposal_accept", assistantTargets: { proposal_id: "companion-preference-proposal:123", expected_fingerprint: "a".repeat(64) },
      assistantPreference: { preferenceType: "address", candidateValue: "小明\u202e", status: "pending" } };
    expect(preferenceProposalPreviewIsValid(summary)).toBe(true);
    expect(managementApprovalActionIsKnown(summary.assistantAction)).toBe(true);
    const preview = toolApprovalActionPreview(summary, "personal_assistant_manage_tool", "zh");
    expect(preview).toContain("接受偏好建议"); expect(preview).toContain("称呼"); expect(preview).toContain("\\u202e");
    expect(preview).not.toContain("\u202e"); expect(preview).toContain(summary.assistantTargets.expected_fingerprint);
    expect(toolApprovalActionPreview({ ...summary, assistantAction: "preference_proposal_reject" }, "personal_assistant_manage_tool", "zh")).toContain("拒绝偏好建议");
    for (const invalid of [{ ...summary, assistantArgumentsInvalid: true }, { ...summary, assistantPreference: undefined },
      { ...summary, assistantTargets: { ...summary.assistantTargets, extra: "x" } },
      { ...summary, assistantTargets: { ...summary.assistantTargets, expected_fingerprint: "x".repeat(64) } },
      { ...summary, assistantPreference: { ...summary.assistantPreference, extra: "x" } },
      { ...summary, assistantPreference: { ...summary.assistantPreference, status: "accepted" } },
      { ...summary, assistantPreference: { ...summary.assistantPreference, candidateValue: "x".repeat(41) } },
      { ...summary, assistantPreference: { ...summary.assistantPreference, preferenceType: "humor", candidateValue: "unapproved" } }]) {
      expect(preferenceProposalPreviewIsValid(invalid)).toBe(false);
      expect(toolApprovalActionPreview(invalid, "personal_assistant_manage_tool", "zh")).toMatch(/无法核对/);
    }
    expect(managementApprovalActionIsKnown("arbitrary_action")).toBe(false);
  });
  it("preserves the complete browser target and quotes untrusted page text", () => {
    const targets = { page_id: "8e2731f7-06a2-41db-bfa2-cbe76a099811", snapshot_id: "8e2731f7-06a2-41db-bfa2-cbe76a099812", element_ref: "1", url: "https://www.bilibili.com/", element_name: "搜索\u202e", operation: "fill", value: "机器学习\n第二行" };
    const summary = { assistantAction: "browser_interact", assistantTargets: targets, assistantOperationDescription: "向网页上的所选元素填写所示内容。" };
    expect(browserInteractPreviewIsValid(summary)).toBe(true);
    const preview = toolApprovalActionPreview(summary, "personal_assistant_manage_tool", "zh");
    expect(preview).toContain(targets.page_id);
    expect(preview).toContain(targets.snapshot_id);
    expect(preview).toContain('"机器学习\\n第二行"');
    expect(preview).toContain('"搜索\\u202e"');
    expect(preview).not.toContain("\u202e");
    const fullUrl = "https://www.bilibili.com/?keyword=a%26b#results";
    expect(browserInteractPreviewIsValid({ ...summary, assistantTargets: { ...targets, url: fullUrl } })).toBe(true);
    expect(toolApprovalActionPreview({ ...summary, assistantTargets: { ...targets, url: fullUrl } }, "personal_assistant_manage_tool", "zh")).toContain(fullUrl);
    expect(browserInteractPreviewIsValid({ ...summary, assistantTargets: { ...targets, url: "https://example.com/?" + "x".repeat(8192) } })).toBe(false);
    expect(browserInteractPreviewIsValid({ ...summary, assistantTargets: { ...targets, operation: "click" } })).toBe(false);
    expect(browserInteractPreviewIsValid({ ...summary, assistantTargets: { ...targets, approved: true } })).toBe(false);
    expect(browserInteractPreviewIsValid({ ...summary, assistantTargets: { ...targets, url: "file:///private" } })).toBe(false);
    expect(browserInteractPreviewIsValid({ ...summary, assistantTargets: { ...targets, snapshot_id: "forged" } })).toBe(false);
  });
  it("binds and displays all recovery details without truncation", () => {
    const suffix = "a".repeat(40);
    const summary = { assistantAction: "reminder_handoff_recover", assistantOperationDescription: "重新审批当前来源快照并继续原编号交接；原记录保留。旧进程实际权限与发送者停止尚未证明；不重放已开始或未知的写入。",
      assistantTargets: { sourceProjectId: "p".repeat(160), instanceId: "instance:1", assistantAgentId: "agent-1",
        operationId: `initial-${suffix}`, syncId: `affairs-${suffix}`, sourceSnapshotDigest: "b".repeat(64), previousAuthorizationHead: "c".repeat(64) } };
    expect(recoveryPreviewIsValid(summary)).toBe(true);
    const zh = toolApprovalActionPreview(summary, "personal_assistant_manage_tool", "zh");
    for (const value of Object.values(summary.assistantTargets)) expect(zh).toContain(value);
    for (const value of ["重新授权旧提醒交接", "来源项目", "来源实例", "来源助理", "原操作 ID", "原同步 ID", "当前来源快照摘要", "原授权 head", "旧进程实际权限与发送者停止尚未证明", "不重放已开始或未知的写入"]) expect(zh).toContain(value);
    expect(toolApprovalActionPreview(summary, "personal_assistant_manage_tool", "en")).toContain("sender shutdown have not been proven");
    const invalid = [
      { ...summary, assistantTargets: undefined },
      ...Object.keys(summary.assistantTargets).map(key => ({ ...summary, assistantTargets: Object.fromEntries(Object.entries(summary.assistantTargets).filter(([name]) => name !== key)) })),
      { ...summary, assistantTargets: { ...summary.assistantTargets, extra: "forged" } },
      { ...summary, assistantTargets: { ...summary.assistantTargets, sourceProjectId: "p".repeat(161) } },
      { ...summary, assistantTargets: { ...summary.assistantTargets, instanceId: "instance\nforged" } },
      { ...summary, assistantTargets: { ...summary.assistantTargets, assistantAgentId: "agent\n" } },
      { ...summary, assistantTargets: { ...summary.assistantTargets, operationId: `initial-${"A".repeat(40)}` } },
      { ...summary, assistantTargets: { ...summary.assistantTargets, operationId: `initial-${suffix.slice(1)}` } },
      { ...summary, assistantTargets: { ...summary.assistantTargets, syncId: `affairs-${"d".repeat(40)}` } },
      { ...summary, assistantTargets: { ...summary.assistantTargets, sourceSnapshotDigest: "b".repeat(63) } },
      { ...summary, assistantTargets: { ...summary.assistantTargets, previousAuthorizationHead: `${"c".repeat(64)}\n` } },
      { ...summary, assistantTargets: { ...summary.assistantTargets, previousAuthorizationHead: 42 } },
      { ...summary, assistantOperationDescription: undefined },
      { ...summary, assistantOperationDescription: "重新审批当前来源快照并继续原编号交接；原记录保留。" },
      { ...summary, assistantOperationDescription: `${summary.assistantOperationDescription}\nforged` },
      { ...summary, assistantArgumentsInvalid: true }, { ...summary, assistantDetailsOmitted: true },
    ];
    expect(recoveryPreviewIsValid(null)).toBe(false);
    for (const value of invalid) {
      expect(recoveryPreviewIsValid(value)).toBe(false);
      const preview = toolApprovalActionPreview(value, "personal_assistant_manage_tool", "zh");
      expect(preview).toContain("参数无法核对");
      expect(preview).not.toContain(suffix);
    }
  });
  it("requires and displays every fixed file-tool permission and the dynamic directory boundary", () => {
    const summary = { assistantAction: "agent_create", assistantTargets: { project_id: "project:1", display_name: "Worker", model_id: "model-1" },
      assistantCreatePreset: "project_files_v1", assistantCreateTools: ["glob_tool", "grep_search_tool", "read_file_tool", "apply_diff_edit_tool", "write_file_tool"],
      assistantOperationDescription: "固定文件工具权限持续生效；写入按当前权限和协作模式审批，edit/yolo 等模式可能自动批准。目标派遣任务的审批只有在完整预览、版本和执行参数均可验证时才能批准。平台允许的动态目录包括项目、Agent 工作区、项目存储、工具目录、系统临时目录和用户配置允许目录，未来可能变化。不能执行命令或测试。" };
    expect(launcherAgentCreatePreviewIsValid(summary)).toBe(true);
    const zh = toolApprovalActionPreview(summary, "personal_assistant_manage_tool", "zh");
    const en = toolApprovalActionPreview(summary, "personal_assistant_manage_tool", "en");
    for (const name of summary.assistantCreateTools) { expect(zh).toContain(name); expect(en).toContain(name); }
    for (const value of ["项目存储", "工具目录", "系统临时目录", "用户配置允许目录", "协作模式审批", "edit/yolo", "可能自动批准", "完整预览", "版本和执行参数", "未来可能变化", "不能执行命令或测试"]) expect(zh).toContain(value);
    for (const value of ["project storage", "tools directory", "system temporary directories", "user-configured allowed directories", "collaboration mode", "approve automatically", "complete preview", "revision, and execution arguments", "may change"]) expect(en).toContain(value);
    for (const patch of [{ assistantCreateTools: undefined }, { assistantCreateTools: ["glob_tool"] },
      { assistantCreatePreset: "full_access" }, { assistantOperationDescription: "omitted" }]) {
      expect(launcherAgentCreatePreviewIsValid({ ...summary, ...patch })).toBe(false);
    }
  });
  it("shows the complete Launcher creation project and model in both languages and counts code points", () => {
    const summary = { assistantAction: "agent_create", assistantTargets: {
      project_id: "project:1", display_name: "😀".repeat(120), model_id: "m".repeat(200),
    }, assistantOperationDescription: "新 Agent 默认没有工具和读写范围，不能保证读取或修改项目；派遣写任务不会自动增加工具权限。" };
    expect(launcherAgentCreatePreviewIsValid(summary)).toBe(true);
    const zh = toolApprovalActionPreview(summary, "personal_assistant_manage_tool", "zh");
    const en = toolApprovalActionPreview(summary, "personal_assistant_manage_tool", "en");
    expect(zh).toContain(`模型: ${summary.assistantTargets.model_id}`);
    expect(en).toContain(`Model: ${summary.assistantTargets.model_id}`);
    expect(en).toContain("Project: project:1");
    expect(en).toContain("has no tools or read/write scopes by default");
    expect(en).not.toContain("新 Agent 默认");
    expect(launcherAgentCreatePreviewIsValid({ ...summary, assistantTargets: { ...summary.assistantTargets, display_name: "😀".repeat(121) } })).toBe(false);
    expect(launcherAgentCreatePreviewIsValid({ ...summary, assistantTargets: { ...summary.assistantTargets, model_id: "bad\u202evalue" } })).toBe(false);
    expect(launcherAgentCreatePreviewIsValid({ ...summary, assistantTargets: { project_id: "project:1", display_name: "Worker" } })).toBe(false);
  });
  it("shows the exact project lifecycle request and rejects incomplete details", () => {
    const summary = { assistantAction: "project_lifecycle", assistantTargets: {
      project_id: "project:1", operation: "start", request_id: "request-1",
    } };
    expect(projectLifecyclePreviewIsValid(summary)).toBe(true);
    expect(toolApprovalActionPreview(summary, "personal_assistant_manage_tool", "zh"))
      .toBe("管理项目\n项目: project:1\n操作: 启动\n请求 ID: request-1");
    for (const targets of [undefined, { ...summary.assistantTargets, operation: "force-stop" },
      { ...summary.assistantTargets, project_id: "project\nforged" },
      { ...summary.assistantTargets, request_id: "x".repeat(129) },
      { ...summary.assistantTargets, extra: true }]) {
      const invalid = { ...summary, assistantTargets: targets };
      expect(projectLifecyclePreviewIsValid(invalid)).toBe(false);
      expect(toolApprovalActionPreview(invalid, "personal_assistant_manage_tool", "zh")).toContain("参数无法核对");
    }
  });
  it("shows the entire write dispatch request and rejects misleading or incomplete details", () => {
    const task = `修改这两个文件\n${"长任务".repeat(300)}\n保留其他内容。`;
    const summary = { assistantAction: "dispatch_write", assistantTargets: { project_id: "project-1", agent_id: "agent-1", dispatch_id: "dispatch-1" },
      assistantRequestedPermission: "workspace_write", assistantTask: task };
    expect(dispatchWritePreviewIsValid(summary)).toBe(true);
    const preview = toolApprovalActionPreview(summary, "personal_assistant_manage_tool", "zh");
    expect(preview).toContain("项目: project-1");
    expect(preview).toContain("Agent: agent-1");
    expect(preview).toContain("派遣 ID: dispatch-1");
    expect(preview).toContain("申请权限: workspace_write");
    expect(preview.endsWith(task)).toBe(true);
    for (const invalid of [
      { ...summary, assistantTargets: { ...summary.assistantTargets, agent_id: "agent\nforged" } },
      { ...summary, assistantRequestedPermission: "full_access" },
      { ...summary, assistantTask: "altered\u202Etext" },
      { ...summary, assistantTask: "x".repeat(12001) },
      { ...summary, assistantTask: undefined },
      { ...summary, assistantArgumentsInvalid: true },
    ]) {
      expect(dispatchWritePreviewIsValid(invalid)).toBe(false);
      expect(toolApprovalActionPreview(invalid, "personal_assistant_manage_tool", "zh")).toContain("参数无法核对");
    }
  });
  it("names semantic API operations and shows concrete targets and impact", () => {
    const preview = toolApprovalActionPreview({ assistantAction: "provider_update",
      assistantTargets: { provider_id: "local-ai" }, assistantChangedFields: ["enabled"],
      assistantOperationDescription: "修改连接名称、启用状态或地址。", assistantDetailsOmitted: true,
    }, "personal_assistant_manage_tool", "zh");
    expect(preview).toContain("修改模型连接");
    expect(preview).toContain("provider_id: local-ai");
    expect(preview).toContain("修改字段: enabled");
    expect(preview).toContain("修改连接名称、启用状态或地址");
    expect(toolApprovalActionPreview({ assistantAction: "session_archive" }, "personal_assistant_manage_tool", "en"))
      .toContain("Archive session");
    expect(toolApprovalActionPreview({ assistantAction: "http_proxy" }, "personal_assistant_manage_tool", "zh"))
      .toContain("参数无法核对");
  });
  it("shows every authorization upgrade scope and exact project in both languages", () => {
    const scopes = ["knowledge:catalog:read", "teams:directory:read", ...Array.from({ length: 20 }, (_, i) => `scope:${i}`)];
    const summary = { assistantAction: "authorization_upgrade", assistantTargets: { project_id: "project-123" }, assistantAddedScopes: scopes };
    expect(authorizationUpgradePreviewIsValid(summary)).toBe(true);
    expect(toolApprovalActionPreview(summary, "personal_assistant_manage_tool", "zh")).toBe(
      ["新增项目权限", "项目: project-123", "新增权限:", ...scopes.map((scope) => `- ${scope}`)].join("\n"));
    expect(toolApprovalActionPreview(summary, "personal_assistant_manage_tool", "en")).toBe(
      ["Add project permissions", "Project: project-123", "Added permissions:", ...scopes.map((scope) => `- ${scope}`)].join("\n"));
  });
  it("rejects absent or unsafe authorization upgrade details", () => {
    const good = { assistantAction: "authorization_upgrade", assistantTargets: { project_id: "project-123" }, assistantAddedScopes: ["source:read"] };
    const invalid: Record<string, unknown>[] = [
      { ...good, assistantTargets: undefined }, { ...good, assistantTargets: { project_id: "" } },
      { ...good, assistantTargets: { project_id: "project\nforged" } },
      { ...good, assistantTargets: { project_id: "project\n" } },
      { ...good, assistantTargets: { project_id: "project\u202Eforged" } },
      { ...good, assistantAddedScopes: undefined }, { ...good, assistantAddedScopes: [] },
      { ...good, assistantAddedScopes: ["source:read", 3] }, { ...good, assistantAddedScopes: [""] },
      { ...good, assistantAddedScopes: ["source:read\nforged"] },
      { ...good, assistantAddedScopes: ["source:read\n"] },
      { ...good, assistantAddedScopes: ["source:read\u202E"] },
      { ...good, assistantAddedScopes: Array(1) },
    ];
    invalid.push({ ...good, assistantArgumentsInvalid: true });
    invalid.push({ ...good, assistantAction: "team_run" });
    expect(authorizationUpgradePreviewIsValid(null)).toBe(false);
    for (const summary of invalid) {
      expect(authorizationUpgradePreviewIsValid(summary)).toBe(false);
      if (summary.assistantAction !== "authorization_upgrade") continue;
      expect(toolApprovalActionPreview(summary, "personal_assistant_manage_tool", "zh")).toContain("参数无法核对");
      expect(toolApprovalActionPreview(summary, "personal_assistant_manage_tool", "en")).toContain("Arguments cannot be verified");
    }
  });
  it("explains the one-step team run and rejects an incomplete scope", () => {
    const summary = { assistantAction: "team_run", assistantTargets: { name: "验收团队", template_id: "dev-team" },
      assistantPlan: { memberCount: 4, goalPreview: "核对计算结果", startsImmediately: true, automaticRecovery: false, localIntegration: false } };
    const preview = toolApprovalActionPreview(summary, "personal_assistant_manage_tool", "zh");
    expect(preview).toContain("创建团队并运行");
    expect(preview).toContain("核对计算结果");
    expect(preview).toContain("规划师 → 开发 A → 开发 B → 评审员");
    expect(preview).toContain("立即启动");
    expect(preview).toContain("不启用自动恢复、自动合入或部署");
    expect(toolApprovalActionPreview(summary, "personal_assistant_manage_tool", "en")).toContain("Create 4 members");
    expect(toolApprovalActionPreview({ ...summary, assistantPlan: undefined }, "personal_assistant_manage_tool", "zh"))
      .toContain("运行范围无法核对");
  });
  it("shows the assistant operation and concrete target in both languages", () => {
    const summary = { assistantAction: "session_create", assistantTargets: { agent_id: "agent-a", title: "Acceptance" } };
    expect(toolApprovalActionPreview(summary, "personal_assistant_manage_tool", "zh"))
      .toBe("创建会话\nagent_id: agent-a\ntitle: Acceptance");
    expect(toolApprovalActionPreview(summary, "personal_assistant_manage_tool", "en"))
      .toContain("Create session");
    expect(toolApprovalActionPreview({ assistantAction: "session_delete", assistantArgumentsInvalid: true }, "personal_assistant_manage_tool", "zh"))
      .toContain("参数无法核对");
    expect(toolApprovalActionPreview({ assistantAction: "agent_update", assistantChangedFields: ["tool_policy_json"], assistantDetailsOmitted: true }, "personal_assistant_manage_tool", "en"))
      .toContain("Values omitted");
  });
  it("covers managed write actions with names, targets and changed fields", () => {
    expect(toolApprovalActionPreview(
      { assistantAction: "team_create", assistantTargets: { name: "交付团队", templateId: "dev-team" } },
      "personal_assistant_manage_tool", "zh",
    )).toBe("创建团队\nname: 交付团队\ntemplateId: dev-team");
    expect(toolApprovalActionPreview(
      { assistantAction: "knowledge_ingest", assistantTargets: { inboxSourceId: "isrc-1", ownerType: "team", ownerId: "team-1" } },
      "personal_assistant_manage_tool", "en",
    )).toContain("Ingest knowledge");
    expect(toolApprovalActionPreview(
      { assistantAction: "config_update", assistantChangedFields: ["ui.language", "llm.profiles.primary.model_ref"], assistantDetailsOmitted: true },
      "personal_assistant_manage_tool", "zh",
    )).toContain("修改字段: ui.language, llm.profiles.primary.model_ref");
    // An unknown manage action still renders the refuse-and-retry guidance.
    expect(toolApprovalActionPreview(
      { assistantAction: "config_write" }, "personal_assistant_manage_tool", "zh",
    )).toContain("参数无法核对");
  });

  it("prefers command preview for shell tools like Codex", () => {
    expect(toolApprovalActionPreview({
      commandPreview: "curl https://example.com",
      argumentKeys: ["cmd"],
    }, "web_fetch_tool")).toBe("$ curl https://example.com");
  });

  it("shows cwd and stdin while keeping session grants truthful", () => {
    expect(toolApprovalActionPreview({
      commandPreview: '.\\.venv\\Scripts\\python.exe -c "print(123)"',
      cwdPreview: "C:\\workspace\\repo",
    }, "exec_command")).toContain("cwd: C:\\workspace\\repo");
    expect(toolApprovalActionPreview({
      terminalSessionId: "sandbox-terminal-a",
      stdinPreview: "ORBIT-71\n",
      stdinChars: 9,
    }, "write_stdin")).toContain("stdin (9 chars):\nORBIT-71\n");
    expect(toolApprovalSessionGrantDescription({ kind: "terminal_session" }, "zh"))
      .toContain("同一终端");
  });

  it("falls back to path preview then tool label", () => {
    expect(toolApprovalActionPreview({
      pathPreview: "docs/readme.md",
    }, "read_file_tool")).toBe("docs/readme.md");
    expect(toolApprovalDisplayName("web_fetch_tool", "zh")).toBe("读取网页");
  });

  it("uses Codex-style title and Yes/Always/No labels", () => {
    expect(toolApprovalCodexTitle("zh")).toBe("允许执行？");
    expect(toolApprovalCodexTitle("en")).toBe("Allow this action?");
    expect(toolApprovalCodexButtonLabels("en")).toMatchObject({
      yes: "Yes",
      always: "Always (this agent)",
      no: "No",
    });
    expect(toolApprovalCodexButtonLabels("zh")).toMatchObject({
      yes: "是",
      always: "始终（此 Agent）",
      no: "否",
    });
    expect(toolApprovalSessionGrantDescription({ kind: "exact_arguments" }, "zh"))
      .toContain("永久");
  });
});
it("shows the verified previous assistant for a history import", () => {
  const preview = toolApprovalActionPreview({ assistantAction: "history_import",
    assistantTargets: { sourceProjectId: "fixture-project", instanceId: "fixture-instance", assistantAgentId: "old-pa" },
    assistantOperationDescription: "只读导入所选旧助理的历史会话和附件。" }, "personal_assistant_manage_tool", "zh");
  expect(preview).toContain("导入旧助理历史");
  expect(preview).toContain("项目: fixture-project");
  expect(preview).toContain("旧助理: old-pa");
});
it("shows the verified previous assistant for an affairs sync", () => {
  const preview = toolApprovalActionPreview({ assistantAction: "affairs_sync",
    assistantTargets: { sourceProjectId: "fixture-project", instanceId: "fixture-instance", assistantAgentId: "old-pa" },
    assistantOperationDescription: "同步所选旧助理的个人事务。" }, "personal_assistant_manage_tool", "zh");
  expect(preview).toContain("同步旧助理事务");
  expect(preview).toContain("旧助理: old-pa");
  const recovery = toolApprovalActionPreview({ assistantAction: "affairs_sync",
    assistantTargets: { assistantAgentId: "old-pa", syncId: "affairs-" + "f".repeat(40) },
    assistantOperationDescription: "核对原事务同步回执，不会重新写入事务。" }, "personal_assistant_manage_tool", "zh");
  expect(recovery).toContain("原回执: affairs-");
});

it.each([["avatar", "头像", "avatar"], ["background", "壁纸", "background"]])("shows the reviewed %s upload and cancellation effects", (kind, zhTarget, enTarget) => {
  const summary = { assistantAction: "operator_image_upload", assistantTargets: { kind } };
  const zh = toolApprovalActionPreview(summary, "personal_assistant_manage_tool", "zh");
  const en = toolApprovalActionPreview(summary, "personal_assistant_manage_tool", "en");
  expect(zh).toContain(zhTarget); expect(zh).toContain("上传并应用"); expect(zh).toContain("取消不修改");
  expect(en).toContain(enTarget); expect(en).toContain("upload and apply"); expect(en).toContain("Cancel");
});

it.each([undefined, {}, {kind: "other"}, {kind: "avatar", path: "secret"}, {kind: null}])("rejects unverifiable image upload target %j", assistantTargets => {
  const preview = toolApprovalActionPreview({assistantAction: "operator_image_upload", assistantTargets}, "personal_assistant_manage_tool", "zh");
  expect(preview).toContain("参数无法核对");
  expect(preview).not.toContain("secret");
});
