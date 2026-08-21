import { describe, expect, it } from "vitest";

import apiSource from "./chat.ts?raw";
import routeSource from "../routes/chat/ChatCodingRouteWorkbench.tsx?raw";
import mutationSource from "../routes/chat/useChatSessionDetailMutations.ts?raw";
import lifecycleSource from "../routes/chat/useChatWorkspaceLifecycle.ts?raw";
import composerSource from "../routes/chat/useChatComposerSubmit.ts?raw";
import composerModelSource from "../routes/chat/chatComposerSubmitModel.ts?raw";
import helperSource from "../routes/chat/chatSessionDetailHelpers.ts?raw";

describe("Chat session tool approval API", () => {
  it("owns pending approval query and decision transports", () => {
    expect(apiSource).toContain("/tool-approvals?status=pending");
    expect(apiSource).toContain("/tool-approvals/");
    expect(apiSource).toContain("/decision");
    expect(apiSource).toContain('method: "POST"');
    expect(apiSource).toContain("JSON.stringify({ decision })");
  });

  it("keeps route orchestration free of direct session approval transport", () => {
    expect(routeSource).toContain("listPendingSessionToolApprovals");
    expect(mutationSource).toContain("resolveSessionToolApprovalDecision");
    expect(routeSource).not.toContain("/tool-approvals?status=pending");
    expect(mutationSource).not.toContain("/tool-approvals/");
  });

  it("owns session detail GET transport outside chat route helpers", () => {
    expect(apiSource).toContain("`/api/sessions/${encodeURIComponent(sessionId)}`");
    expect(apiSource).toContain("search.set(\"includeSecondary\", \"false\")");
    expect(helperSource).toContain("fetchSessionDetail(normalizedSessionId, {");
    expect(lifecycleSource).toContain("fetchSessionDetail(optimisticNextActiveSessionId)");
    expect(helperSource).not.toContain("/api/sessions/");
    expect(lifecycleSource).not.toContain("`/api/sessions/${encodeURIComponent(optimisticNextActiveSessionId)}`");
  });

  it("owns session catalog transport outside chat route hooks", () => {
    expect(apiSource).toContain("/api/sessions/query");
    expect(apiSource).toContain("/api/sessions/bootstrap?limit=50");
    expect(apiSource).toContain("/api/sessions/active");
    expect(apiSource).toContain("`/api/sessions/${encodeURIComponent(sessionId)}/select`");
    expect(apiSource).toContain('method: "PATCH"');
    expect(apiSource).toContain('method: "DELETE"');
    expect(lifecycleSource).toContain("createChatSession");
    expect(lifecycleSource).toContain("deleteChatSession");
    expect(lifecycleSource).toContain("updateChatSession");
    expect(apiSource).toContain("isSessionNotFoundError(error)");
    expect(apiSource).toContain("export async function deleteChatSession");
    expect(apiSource).toContain("export function bulkDeleteChatSessions");
    expect(apiSource).toContain("/api/sessions/bulk-delete");
    expect(lifecycleSource).toContain("bulkDeleteChatSessions");
    expect(lifecycleSource).not.toContain('fetchJson<SessionDetail>("/api/sessions"');
    expect(lifecycleSource).not.toContain('fetchJson<SessionDeleteResponse>(`/api/sessions/${sessionId}`');
  });

  it("owns session turn-command transport outside chat route hooks", () => {
    expect(apiSource).toContain("/messages");
    expect(apiSource).toContain("/messages/edit-resubmit");
    expect(apiSource).toContain("/stop");
    expect(apiSource).toContain("/guidance");
    expect(apiSource).toContain("/attachments");
    expect(apiSource).toContain("/llm-options");
    expect(apiSource).toContain("/reasoning-effort");
    expect(composerSource).toContain("submitSessionMessage");
    expect(composerSource).toContain("editResubmitSessionMessage");
    expect(composerSource).toContain("stopSessionTurn");
    expect(composerSource).toContain("submitSessionGuidance");
    expect(composerModelSource).toContain("postSessionImageAttachment");
    expect(mutationSource).toContain("updateSessionReasoningEffort");
    expect(routeSource).toContain("fetchSessionLlmOptions");
    expect(composerSource).not.toContain("/api/sessions/");
    expect(composerModelSource).not.toContain("/api/sessions/");
    expect(mutationSource).not.toContain("/reasoning-effort");
  });

  it("owns review-candidate transport outside the chat lifecycle hook", () => {
    expect(apiSource).toContain("/chat-review-candidate");
    expect(apiSource).toContain('method: "POST"');
    expect(lifecycleSource).toContain("createSessionChatReviewCandidate");
    expect(lifecycleSource).not.toContain("/chat-review-candidate");
  });

  it("owns conversation and child-session list transport", () => {
    expect(apiSource).toContain("/api/conversations");
    expect(apiSource).toContain("/child-sessions");
    expect(apiSource).toContain("export function listSessionChildSessions");
    expect(apiSource).not.toContain("export function listChildSessions");
    expect(lifecycleSource).not.toContain("/api/conversations");
  });

  it("owns chat-room transport outside chat and team hooks", () => {
    expect(apiSource).toContain("/api/chat-rooms/modes");
    expect(apiSource).toContain("/api/chat-rooms/purposes");
    expect(apiSource).toContain("`/api/chat-rooms/${encodeURIComponent(roomId)}`");
    expect(apiSource).toContain("/rounds");
    expect(apiSource).toContain("/reset");
    expect(apiSource).toContain('method: "PATCH"');
    expect(apiSource).toContain('method: "DELETE"');
    expect(lifecycleSource).toContain("createChatRoom");
    expect(lifecycleSource).toContain("startChatRoomRound");
    expect(lifecycleSource).toContain("stopChatRoomRound");
    expect(lifecycleSource).toContain("updateChatRoom");
    expect(lifecycleSource).toContain("deleteChatRoom");
    expect(lifecycleSource).toContain("resetChatRoom");
    expect(lifecycleSource).not.toContain("/api/chat-rooms");
  });
});
