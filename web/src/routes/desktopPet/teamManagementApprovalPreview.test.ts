import { describe, expect, it } from "vitest";
import { toolApprovalActionPreview } from "../chat/toolApprovalPreview";
import { launcherTeamActionIsKnown, launcherTeamActionPreview, launcherTeamActionTitle, launcherTeamPreviewIsValid,
  type LauncherTeamAction } from "./teamManagementApprovalPreview";

const hash = "a".repeat(64);
const commonTargets = { project_id: "project-a", request_id: "request_1" };
const teamTargets = { ...commonTargets, team_id: "team-a", expected_team_fingerprint: hash };
const member = { memberId: "", agentId: "agent-a", role: " Lead ", effectiveRole: "lead", knowledgeReviewEligible: true };
const members = () => ({ memberAgentIds: ["agent-a"], memberIds: [""], memberRoles: [{ ...member }], membersDigest: hash, memberCount: "1" });
function base(action: LauncherTeamAction, targets: Record<string, unknown>, delta: Record<string, unknown>, fields: string[]) {
  return { assistantPlatformPreviewVersion: 1, assistantAction: action, assistantTargets: targets, assistantParametersDigest: hash,
    assistantChangedFields: fields, assistantDelta: delta, assistantContentOmitted: false, assistantDetailsOmitted: false };
}
const create = () => base("team_create", { ...commonTargets }, { operation: "create", name: "团队 \"名称\"", descriptionChars: "4",
  descriptionDigest: hash, purposeChars: "0", purposeDigest: hash, ...members(), teamKind: "custom" }, ["team"]);
const add = () => base("team_member_add", { ...teamTargets }, { operation: "add", ...members() }, ["members"]);
const remove = () => base("team_member_remove", { ...teamTargets, agent_id: "agent-a" }, { operation: "remove", removedAgentId: "agent-a",
  preservesAgent: true, preservesHistory: true, explicitKnowledgeGrantsUnchanged: true }, ["members"]);
const archive = (room = "room-a") => base("team_archive", { ...teamTargets, ...(room ? { expected_linked_chat_room_id: room } : {}) },
  { operation: "archive", memberAgentIds: ["agent-a", "agent-b"], memberCount: "2", linkedChatRoomId: room,
    archivesMemberAgents: true, freezesMemberSessions: true, deletesLinkedChatRooms: true,
    clearsOtherMemberRoomAssociations: true, dissolvesEmptyMemberRooms: true, keepsTeamKnowledgeAndFlows: true },
  ["status", "members", "sessions", "linkedChatRooms"]);

function expectDeclined(value: unknown) {
  expect(launcherTeamPreviewIsValid(value)).toBe(false);
  expect(launcherTeamActionPreview(value)).toBe("团队操作\n参数无法核对，请拒绝并重新发起。");
  expect(launcherTeamActionPreview(value, "en")).toContain("Arguments cannot be verified");
}

describe("Launcher Team management approval preview", () => {
  it("recognizes only the four private Team actions and returns safe localized titles", () => {
    for (const action of ["team_create", "team_member_add", "team_member_remove", "team_archive"]) {
      expect(launcherTeamActionIsKnown(action)).toBe(true);
      expect(launcherTeamActionTitle(action)).not.toBe("团队操作");
      expect(launcherTeamActionTitle(action, "en")).not.toBe("Team action");
    }
    for (const value of ["team_update", "team_run", "TEAM_CREATE", "toString", "__proto__", null, 1, {}, "team_create\n"]) {
      expect(launcherTeamActionIsKnown(value)).toBe(false);
      expect(launcherTeamActionTitle(value)).toBe("团队操作");
    }
  });

  it("renders all four complete native summaries with project/request identities and hashes", () => {
    for (const fixture of [create(), add(), remove(), archive()]) {
      expect(launcherTeamPreviewIsValid(fixture)).toBe(true);
      for (const lang of ["zh", "en"] as const) {
        const preview = launcherTeamActionPreview(fixture, lang);
        expect(preview).toContain("project-a");
        expect(preview).toContain("request_1");
        expect(preview).toContain(hash);
        expect(preview.length).toBeLessThanOrEqual(16000);
        if (fixture.assistantAction !== "team_create") expect(preview).toContain("team-a");
      }
    }
    const preview = launcherTeamActionPreview(create());
    expect(preview).toContain("新建 custom 自定义团队");
    expect(preview).toContain(String.raw`名称: "团队 \"名称\""`);
    expect(preview).toContain('成员 ID: ""');
    expect(preview).toContain('角色: " Lead "');
    expect(preview).toContain("知识审核资格: 有");
    expect(preview).toContain("不授予实际知识 ACL");
    expect(launcherTeamActionPreview(add())).toContain("可能同步原生会话和关联房间");
  });

  it("states the remove and archive cascade exactly without offering an approval conclusion", () => {
    const removed = launcherTeamActionPreview(remove());
    expect(removed).toContain("移除成员 Agent ID: agent-a");
    expect(removed).toContain("不会归档 Agent 或历史");
    expect(removed).toContain("不等于撤销该 Agent 的显式知识 ACL");
    const archived = launcherTeamActionPreview(archive());
    for (const text of ["归档团队及下面列出的全部成员 Agent", "agent-a", "agent-b", "封存这些成员的全部会话",
      "删除该团队全部归属群聊", "room-a", "主关联群聊 ID 仅为团队记录中的主关联", "额外同 teamId 挂靠的 room",
      "移除成员在其他群聊的关联", "解散因此变空的其他群聊", "知识和流程记录保留", "不执行永久删除（purge）"]) expect(archived).toContain(text);
    const english = launcherTeamActionPreview(archive(), "en");
    for (const text of ["only the primary association", "all chat rooms owned by this team", "extra rooms with the same teamId",
      "associations in other rooms", "dissolves other rooms left empty"]) expect(english).toContain(text);
    expect(archived).not.toMatch(/可以批准|批准此操作|safe to approve/i);
    expect(launcherTeamActionPreview(archive(""))).toContain("关联群聊 ID: 无");
  });

  it("allows content isolation only for create/add while requiring full authorization details", () => {
    for (const fixture of [create(), add()]) {
      fixture.assistantContentOmitted = true;
      expect(launcherTeamPreviewIsValid(fixture)).toBe(true);
      expect(launcherTeamActionPreview(fixture)).toContain("正文未展示");
    }
    for (const fixture of [remove(), archive()]) expectDeclined({ ...fixture, assistantContentOmitted: true });
    for (const fixture of [create(), add(), remove(), archive()]) {
      expectDeclined({ ...fixture, assistantDetailsOmitted: true });
      expectDeclined({ ...fixture, assistantContentOmitted: "false" });
      expectDeclined({ ...fixture, assistantDetailsOmitted: "false" });
      expectDeclined({ ...fixture, assistantArgumentsInvalid: false });
    }
  });

  it("accepts only the exact native manage-tool argumentKeys envelope without relaxing the required preview", () => {
    for (const fixture of [create(), add(), remove(), archive()]) {
      const wrapped = { argumentKeys: ["action", "arguments_json"], ...fixture };
      expect(launcherTeamPreviewIsValid(wrapped)).toBe(true);
      expect(launcherTeamActionPreview(wrapped)).toBe(launcherTeamActionPreview(fixture));
      for (const argumentKeys of [undefined, null, [], Array(2), ["action"], ["arguments_json", "action"],
        ["action", "arguments_json", "extra"], ["action", "unknown"], ["action", "arguments_json\n"],
        ["action", "action"], "action,arguments_json"]) expectDeclined({ ...wrapped, argumentKeys });
      expectDeclined({ ...wrapped, extraEnvelopeField: true });
      for (const key of Object.keys(fixture)) {
        const incomplete: Record<string, unknown> = { ...wrapped };
        delete incomplete[key];
        expectDeclined(incomplete);
      }
    }
  });

  it("rejects missing/extra fields at every level and summaries without the Launcher version marker", () => {
    for (const fixture of [create(), add(), remove(), archive()]) {
      for (const key of Object.keys(fixture)) {
        const incomplete: Record<string, unknown> = { ...fixture };
        delete incomplete[key];
        expectDeclined(incomplete);
      }
      expectDeclined({ ...fixture, argumentKeys: [] });
      for (const key of Object.keys(fixture.assistantTargets)) {
        const targets = { ...fixture.assistantTargets };
        delete targets[key];
        expectDeclined({ ...fixture, assistantTargets: targets });
      }
      expectDeclined({ ...fixture, assistantTargets: { ...fixture.assistantTargets, approved: true } });
      for (const key of Object.keys(fixture.assistantDelta)) {
        const delta = { ...fixture.assistantDelta };
        delete delta[key];
        expectDeclined({ ...fixture, assistantDelta: delta });
      }
      expectDeclined({ ...fixture, assistantDelta: { ...fixture.assistantDelta, approved: true } });
    }
    expectDeclined({ ...create(), assistantPlatformPreviewVersion: "1" });
    expectDeclined({ ...create(), assistantAction: "team_update" });
    for (const value of [undefined, null, [], 1, "team_create", { assistantAction: "team_create" }]) expectDeclined(value);
  });

  it("rejects unsafe text, malformed identities, digests and noncanonical numeric strings", () => {
    for (const unsafe of ["\n", "\r", "\t", "\u0000", "\u200b", "\u202e", "\ud800", "\u2028", "\u2029"]) {
      expectDeclined({ ...create(), assistantDelta: { ...create().assistantDelta, name: `name${unsafe}` } });
      expectDeclined({ ...add(), assistantDelta: { ...add().assistantDelta, memberIds: [`member${unsafe}`],
        memberRoles: [{ ...member, memberId: `member${unsafe}` }] } });
      expectDeclined({ ...add(), assistantDelta: { ...add().assistantDelta, memberRoles: [{ ...member, role: `role${unsafe}` }] } });
    }
    for (const bad of ["", "-bad", "id/part", "bad id", "id\n", "a".repeat(161)])
      expectDeclined({ ...add(), assistantTargets: { ...teamTargets, team_id: bad } });
    for (const bad of ["request.with.dot", "request:colon", "r".repeat(97), "request\n"])
      expectDeclined({ ...create(), assistantTargets: { ...commonTargets, request_id: bad } });
    for (const bad of ["a".repeat(63), "a".repeat(65), "A".repeat(64), hash + "\n", 1]) {
      expectDeclined({ ...create(), assistantParametersDigest: bad });
      expectDeclined({ ...add(), assistantTargets: { ...teamTargets, expected_team_fingerprint: bad } });
      expectDeclined({ ...create(), assistantDelta: { ...create().assistantDelta, descriptionDigest: bad } });
    }
    for (const bad of [1, "01", "+1", "1.0", "-1", "1e1", "1\n", ""]) {
      expectDeclined({ ...create(), assistantDelta: { ...create().assistantDelta, descriptionChars: bad } });
      expectDeclined({ ...add(), assistantDelta: { ...add().assistantDelta, memberCount: bad } });
    }
  });

  it("binds member counts, order and each role row to its member and agent identity", () => {
    const fixture = create();
    for (const delta of [{ memberCount: "0" }, { memberAgentIds: ["agent-a", "agent-a"], memberIds: ["", ""], memberRoles: [member, member], memberCount: "2" },
      { memberIds: [] }, { memberRoles: [] }, { memberAgentIds: Array(1), memberIds: Array(1), memberRoles: Array(1) },
      { memberRoles: [{ ...member, memberId: "different" }] },
      { memberRoles: [{ ...member, agentId: "different" }] }, { memberRoles: [{ ...member, extra: true }] },
      { memberRoles: [{ ...member, effectiveRole: "owner" }] }, { memberRoles: [{ ...member, knowledgeReviewEligible: false }] }])
      expectDeclined({ ...fixture, assistantDelta: { ...fixture.assistantDelta, ...delta } });
    const rows = [{ ...member, memberId: "first" }, { ...member, memberId: "second", agentId: "agent-b" }];
    const two = { ...fixture, assistantDelta: { ...fixture.assistantDelta, memberAgentIds: ["agent-a", "agent-b"],
      memberIds: ["first", "second"], memberRoles: rows, memberCount: "2" } };
    expect(launcherTeamPreviewIsValid(two)).toBe(true);
    expectDeclined({ ...two, assistantDelta: { ...two.assistantDelta, memberRoles: [...rows].reverse() } });
    expectDeclined({ ...add(), assistantDelta: { ...two.assistantDelta, operation: "add" } });
  });

  it("uses the native knowledge review role list without treating custom roles as permissions", () => {
    for (const role of ["owner", "lead", "steward", "knowledge_steward", "source_ingestor", "coordinator", "reviewer", "member", "Custom role", ""]) {
      const effectiveRole = role.trim().toLowerCase() || "member";
      const eligible = ["owner", "lead", "steward", "knowledge_steward", "source_ingestor", "coordinator"].includes(effectiveRole);
      const fixture = { ...add(), assistantDelta: { ...add().assistantDelta, memberRoles: [{ ...member, role, effectiveRole, knowledgeReviewEligible: eligible }] } };
      expect(launcherTeamPreviewIsValid(fixture)).toBe(true);
      expect(launcherTeamActionPreview(fixture)).toContain(`知识审核资格: ${eligible ? "有" : "无"}`);
      expectDeclined({ ...fixture, assistantDelta: { ...fixture.assistantDelta,
        memberRoles: [{ ...member, role, effectiveRole, knowledgeReviewEligible: !eligible }] } });
    }
    const role = "İ".repeat(160);
    expect(launcherTeamPreviewIsValid({ ...add(), assistantDelta: { ...add().assistantDelta,
      memberRoles: [{ ...member, role, effectiveRole: role.toLowerCase(), knowledgeReviewEligible: false }] } })).toBe(true);
  });

  it("rejects wrong operation/changed fields and every false remove or archive effect", () => {
    for (const fixture of [create(), add(), remove(), archive()]) {
      expectDeclined({ ...fixture, assistantChangedFields: [] });
      expectDeclined({ ...fixture, assistantChangedFields: [...fixture.assistantChangedFields, "extra"] });
      expectDeclined({ ...fixture, assistantDelta: { ...fixture.assistantDelta, operation: "purge" } });
    }
    expectDeclined({ ...archive(), assistantChangedFields: ["linkedChatRooms", "members", "sessions", "status"] });
    for (const key of ["preservesAgent", "preservesHistory", "explicitKnowledgeGrantsUnchanged"])
      expectDeclined({ ...remove(), assistantDelta: { ...remove().assistantDelta, [key]: false } });
    for (const key of ["archivesMemberAgents", "freezesMemberSessions", "deletesLinkedChatRooms", "clearsOtherMemberRoomAssociations",
      "dissolvesEmptyMemberRooms", "keepsTeamKnowledgeAndFlows"])
      expectDeclined({ ...archive(), assistantDelta: { ...archive().assistantDelta, [key]: false } });
    expectDeclined({ ...remove(), assistantDelta: { ...remove().assistantDelta, removedAgentId: "agent-b" } });
    expectDeclined({ ...archive(), assistantDelta: { ...archive().assistantDelta, memberCount: "1" } });
    expectDeclined({ ...archive(), assistantDelta: { ...archive().assistantDelta, memberAgentIds: ["agent-a", "agent-a"] } });
    expectDeclined({ ...archive(), assistantDelta: { ...archive().assistantDelta, linkedChatRoomId: "room-b" } });
    expectDeclined({ ...archive(""), assistantTargets: { ...teamTargets, expected_linked_chat_room_id: "" } });
    expectDeclined({ ...archive(), assistantDelta: { ...archive().assistantDelta, linkedChatRoomId: "" } });
  });

  it("bounds strings, member arrays, summary and rendered text without partial approval previews", () => {
    expectDeclined({ ...create(), assistantDelta: { ...create().assistantDelta, name: "n".repeat(161) } });
    expectDeclined({ ...add(), assistantDelta: { ...add().assistantDelta, memberIds: ["m".repeat(97)] } });
    expectDeclined({ ...add(), assistantDelta: { ...add().assistantDelta, memberRoles: [{ ...member, role: "r".repeat(161) }] } });
    const agentIds = Array.from({ length: 120 }, (_, index) => `a${index}`);
    const fixture = { ...archive(""), assistantDelta: { ...archive("").assistantDelta, memberAgentIds: agentIds, memberCount: "120" } };
    expect(launcherTeamPreviewIsValid(fixture)).toBe(true);
    expectDeclined({ ...fixture, assistantDelta: { ...fixture.assistantDelta, memberAgentIds: [...agentIds, "a120"], memberCount: "121" } });
    const large = { ...create(), assistantDelta: { ...create().assistantDelta, descriptionChars: "1".repeat(16000) } };
    expectDeclined(large);
    const circular = create();
    circular.assistantDelta.circular = circular;
    expectDeclined(circular);
    const empty = { ...create(), assistantDelta: { ...create().assistantDelta, memberAgentIds: [], memberIds: [], memberRoles: [], memberCount: "0" } };
    expect(launcherTeamPreviewIsValid(empty)).toBe(true);
  });

  it("rejects same-named legacy summaries here while preserving ordinary chat's existing helper", () => {
    for (const action of ["team_create", "team_archive"]) {
      const legacy = { assistantAction: action, assistantTargets: { team_id: "legacy-team" }, assistantChangedFields: ["name"] };
      expectDeclined(legacy);
      const ordinary = toolApprovalActionPreview(legacy, "personal_assistant_manage_tool", "zh");
      expect(ordinary).toContain("legacy-team");
      expect(ordinary).not.toContain("参数无法核对");
    }
  });
});
