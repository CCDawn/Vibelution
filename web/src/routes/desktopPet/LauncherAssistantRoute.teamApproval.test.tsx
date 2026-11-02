// @vitest-environment happy-dom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ConversationViewProps } from "../../components/conversation/conversationViewTypes";
import { LauncherAssistantEmbeddedRoute } from "./LauncherAssistantRoute";

vi.mock("./DesktopPetCharacter", () => ({ DesktopPetCharacter: () => null }));
// Keep the native approval dialog and Launcher API; replace only transcript rendering.
vi.mock("../../components/conversation/LazyConversationView", () => ({
  LazyConversationView: (props: ConversationViewProps) => createElement("div", { "data-testid": "native-conversation" }, props.composerPrecedingContent),
}));

const hash = "a".repeat(64);
const parameterHash = "b".repeat(64);
const targets = { project_id: "project-a", request_id: "team-request-a" };
const teamTargets = { ...targets, team_id: "team-a", expected_team_fingerprint: hash };
const memberDelta = { memberAgentIds: ["agent-member-a"], memberIds: ["member-a"],
  memberRoles: [{ memberId: "member-a", agentId: "agent-member-a", role: "lead", effectiveRole: "lead", knowledgeReviewEligible: true }],
  memberCount: "1", membersDigest: hash };
function summary(action: string, identity: Record<string, unknown>, delta: Record<string, unknown>, fields: string[]) {
  return { argumentKeys: ["action", "arguments_json"], assistantPlatformPreviewVersion: 1, assistantAction: action, assistantTargets: identity, assistantParametersDigest: parameterHash,
    assistantDelta: delta, assistantChangedFields: fields, assistantContentOmitted: false, assistantDetailsOmitted: false };
}
function teamCases() {
  return [
    { action: "team_create", summary: summary("team_create", targets, { operation: "create", name: "新团队", descriptionChars: "0",
      descriptionDigest: hash, purposeChars: "0", purposeDigest: hash, ...memberDelta, teamKind: "custom" }, ["team"]),
    scope: ["新建 custom 自定义团队", '名称: "新团队"', "agent-member-a", "member-a", "知识审核资格: 有", "不授予实际知识 ACL"] },
    { action: "team_member_add", summary: summary("team_member_add", teamTargets, { operation: "add", ...memberDelta }, ["members"]),
      scope: ["添加 1 名团队成员", "可能同步原生会话和关联房间", "agent-member-a", "member-a", "知识审核资格: 有"] },
    { action: "team_member_remove", summary: summary("team_member_remove", { ...teamTargets, agent_id: "agent-member-a" },
      { operation: "remove", removedAgentId: "agent-member-a", preservesAgent: true, preservesHistory: true, explicitKnowledgeGrantsUnchanged: true }, ["members"]),
    scope: ["agent-member-a", "保留该 Agent 和会话历史", "不会归档 Agent 或历史", "不等于撤销该 Agent 的显式知识 ACL"] },
    { action: "team_archive", summary: summary("team_archive", { ...teamTargets, expected_linked_chat_room_id: "room-a" },
      { operation: "archive", memberAgentIds: ["agent-member-a", "agent-member-b"], memberCount: "2", linkedChatRoomId: "room-a",
        archivesMemberAgents: true, freezesMemberSessions: true, deletesLinkedChatRooms: true,
        clearsOtherMemberRoomAssociations: true, dissolvesEmptyMemberRooms: true, keepsTeamKnowledgeAndFlows: true },
      ["status", "members", "sessions", "linkedChatRooms"]),
    scope: ["归档团队及下面列出的全部成员 Agent", "agent-member-a", "agent-member-b", "封存这些成员的全部会话",
      "删除该团队全部归属群聊", "room-a", "主关联群聊 ID 仅为团队记录中的主关联", "额外同 teamId 挂靠的 room",
      "移除成员在其他群聊的关联", "解散因此变空的其他群聊", "团队知识和流程记录保留", "不执行永久删除（purge）"] },
  ];
}

let root: Root | undefined;
let container: HTMLDivElement | undefined;
let client: QueryClient | undefined;
let invoke: ReturnType<typeof vi.fn>;
let nativeApproval: Record<string, unknown>;
async function unmount() {
  await act(async () => root?.unmount()); root = undefined;
  client?.clear(); client = undefined;
  container?.remove(); container = undefined;
}
afterEach(async () => {
  await unmount();
  vi.unstubAllGlobals(); vi.clearAllMocks();
});
async function settle() {
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)); });
}
async function renderApproval(argumentSummary: unknown, options: { toolName?: string; requestId?: string } = {}) {
  await unmount();
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  vi.stubGlobal("fetch", vi.fn(() => { throw new Error("HTTP is forbidden in this window"); }));
  nativeApproval = { requestId: options.requestId ?? "native-approval-a", sessionId: "assistant-session", turnId: "turn-a", agentId: "assistant-a",
    callId: "call-a", toolName: options.toolName ?? "personal_assistant_manage_tool", approval: "on_request", risk: "high", argumentsHash: hash,
    argumentSummary, sessionGrantScope: {}, decisionFingerprint: hash, configRevision: 1, configHash: hash, permissionPreset: "standard",
    availableDecisions: ["accept", "decline"], createdAt: "2026-11-02T01:00:00Z", status: "pending", decision: null, resolvedAt: null };
  invoke = vi.fn(async (request: Record<string, unknown>) => {
    switch (request.operation) {
      case "status": return { assistant: { agentId: "assistant-a", directSessionId: "assistant-session", displayName: "助理" },
        operatorAssetsVersion: 1, settings: { ok: true, displayName: "助理", modelId: "model-a",
          preferences: { characterId: "dafeiyu", showStatus: true, showTitles: true, showCompletion: true, idleMessage: "在的。" } } };
      case "config": return { language: "zh" };
      case "detail": return { id: "assistant-session", agentId: "assistant-a", status: "ready", messages: [] };
      case "approvals": return [nativeApproval];
      case "resolveApproval":
        nativeApproval = { ...nativeApproval, status: request.decision === "accept" ? "accepted" : "declined", decision: request.decision,
          resolvedAt: "2026-11-02T01:00:01Z" };
        return nativeApproval;
      case "dispatches": return { dispatches: [] };
      case "operatorAsset": return { schemaVersion: 1, kind: request.kind, image: null, readability: "standard" };
      default: throw new Error(`unexpected_operation: ${request.operation}`);
    }
  });
  vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
  client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 30_000 } } });
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
  await act(async () => root!.render(createElement(QueryClientProvider, { client }, createElement(LauncherAssistantEmbeddedRoute))));
  await settle(); await settle();
}
function dialog() {
  const result = container!.querySelector<HTMLElement>('[role="dialog"][data-chat-tool-approval-variant="composer"]');
  expect(result).not.toBeNull();
  return result!;
}
function acceptButton() {
  const result = [...dialog().querySelectorAll("button")].find(button => button.textContent?.includes("允许本次"));
  expect(result).toBeDefined();
  return result!;
}
function decisions() {
  return invoke.mock.calls.filter(([request]) => request.operation === "resolveApproval").map(([request]) => request);
}
function shortcut(element: Element, key: string) {
  element.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }));
}

describe("Launcher Team approval through the native composer dialog", () => {
  it("shows all four complete scopes and resolves each approval using its original native request ID", async () => {
    for (const fixture of teamCases()) {
      const requestId = `native-${fixture.action}-approval`;
      await renderApproval(fixture.summary, { requestId });
      const card = dialog();
      const details = card.querySelector<HTMLElement>("[data-approval-full-preview]");
      expect(details?.closest("details")).not.toBeNull();
      for (const expected of ["project-a", "team-request-a", parameterHash, ...fixture.scope]) expect(details?.textContent).toContain(expected);
      if (fixture.action !== "team_create") {
        expect(details?.textContent).toContain("team-a");
        expect(details?.textContent).toContain(hash);
      }
      expect(card.textContent).toContain("仅本次调用");
      expect(acceptButton().disabled).toBe(false);
      await act(async () => acceptButton().click()); await settle();
      expect(decisions()).toEqual([{ operation: "resolveApproval", requestId, decision: "accept" }]);
      expect(container!.querySelector('[role="dialog"]')).toBeNull();
    }
  });

  it("blocks approval buttons and shortcuts for an altered archive cascade while keeping decline available", async () => {
    const fixture = teamCases().find(row => row.action === "team_archive")!;
    await renderApproval({ ...fixture.summary, assistantDelta: { ...fixture.summary.assistantDelta, archivesMemberAgents: false } });
    const card = dialog();
    expect(card.querySelector("h2")?.textContent).toBe("本次操作暂不能批准");
    expect(card.textContent).toContain("参数无法核对");
    expect(acceptButton().disabled).toBe(true);
    await act(async () => { acceptButton().click(); shortcut(card, "1"); shortcut(card, "y"); });
    expect(decisions()).toEqual([]);
    const decline = card.querySelector<HTMLButtonElement>('button[aria-label="拒绝并关闭"]')!;
    expect(decline.disabled).toBe(false);
    await act(async () => decline.click()); await settle();
    expect(decisions()).toEqual([{ operation: "resolveApproval", requestId: "native-approval-a", decision: "decline" }]);
  });

  it("fails closed on missing previews and same-named legacy management summaries but still accepts a decline shortcut", async () => {
    for (const argumentSummary of [undefined, null,
      { assistantAction: "team_create", assistantTargets: targets },
      { assistantAction: "team_archive", assistantTargets: teamTargets }]) {
      await renderApproval(argumentSummary);
      const card = dialog();
      expect(acceptButton().disabled).toBe(true);
      expect(card.textContent).toContain("参数无法核对");
      await act(async () => { shortcut(card, "1"); shortcut(card, "y"); });
      expect(decisions()).toEqual([]);
      await act(async () => shortcut(card, "2")); await settle();
      expect(decisions()).toEqual([{ operation: "resolveApproval", requestId: "native-approval-a", decision: "decline" }]);
    }
  });

  it("keeps unrelated legacy tool previews outside the private Team adapter despite matching action names", async () => {
    for (const action of ["team_create", "team_archive"]) {
      await renderApproval({ assistantAction: action, path: "legacy-team-reference" }, { toolName: `legacy_${action}_tool` });
      expect(dialog().textContent).toContain("legacy-team-reference");
      expect(dialog().textContent).not.toContain("参数无法核对");
      expect(dialog().textContent).not.toContain("封存这些成员的全部会话");
      expect(acceptButton().disabled).toBe(false);
      await act(async () => acceptButton().click()); await settle();
      expect(decisions()).toEqual([{ operation: "resolveApproval", requestId: "native-approval-a", decision: "accept" }]);
    }
  });
});
