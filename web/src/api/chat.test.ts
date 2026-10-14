import { describe, expect, it } from "vitest";

import apiSource from "./chat.ts?raw";
import chatTypesSource from "./types/chat.ts?raw";
import evolutionApiSource from "./evolution.ts?raw";
import routeSource from "../routes/chat/ChatCodingRouteWorkbench.tsx?raw";
import detailQueriesSource from "../routes/chat/useChatSessionDetailQueries.ts?raw";
import surfaceModelSource from "../routes/chat/useChatConversationSurfaceModel.tsx?raw";
import querySeamsSource from "../routes/chat/chatSessionQuerySeams.ts?raw";
import mutationSource from "../routes/chat/useChatSessionDetailMutations.ts?raw";
import lifecycleSource from "../routes/chat/useChatWorkspaceLifecycle.ts?raw";
import sessionChangeSource from "../routes/chat/useChatSessionChangeMutations.ts?raw";
import composerActionsSource from "../routes/chat/useChatComposerSubmit.ts?raw";
import composerSource from "../routes/chat/useChatComposerTurnMutations.ts?raw";
import composerModelSource from "../routes/chat/chatComposerSubmitModel.ts?raw";
import helperSource from "../routes/chat/chatSessionDetailHelpers.ts?raw";
import conversationViewSource from "../components/conversation/ConversationView.tsx?raw";

describe("Chat session tool approval API", () => {
  it("owns pending approval query and decision transports", () => {
    expect(apiSource).toContain("/tool-approvals?status=pending");
    expect(apiSource).toContain("/tool-approvals/");
    expect(apiSource).toContain("/decision");
    expect(apiSource).toContain('method: "POST"');
    expect(apiSource).toContain("JSON.stringify({ decision })");
  });

  it("keeps route orchestration free of direct session approval transport", () => {
    expect(routeSource).toContain("useSessionToolApprovalsQuery");
    expect(querySeamsSource).toContain("listPendingSessionToolApprovals");
    expect(mutationSource).toContain("resolveSessionToolApprovalDecision");
    expect(routeSource).not.toContain("/tool-approvals?status=pending");
    expect(querySeamsSource).not.toContain("/tool-approvals?status=pending");
    expect(mutationSource).not.toContain("/tool-approvals/");
  });

  it("owns session detail GET transport outside chat route helpers", () => {
    expect(apiSource).toContain("`/api/sessions/${encodeURIComponent(sessionId)}`");
    expect(apiSource).toContain("search.set(\"includeSecondary\", \"false\")");
    expect(helperSource).toContain("fetchSessionDetail(normalizedSessionId, {");
    expect(sessionChangeSource).toContain("fetchSessionDetail(optimisticNextActiveSessionId)");
    expect(lifecycleSource).toContain("useChatSessionChangeMutations(");
    expect(helperSource).not.toContain("/api/sessions/");
    expect(lifecycleSource).not.toContain("`/api/sessions/${encodeURIComponent(optimisticNextActiveSessionId)}`");
    expect(sessionChangeSource).not.toContain("`/api/sessions/${encodeURIComponent(optimisticNextActiveSessionId)}`");
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
    expect(sessionChangeSource).toContain("deleteChatSession");
    expect(lifecycleSource).toContain("updateChatSession");
    expect(apiSource).toContain("isSessionNotFoundError(error)");
    expect(apiSource).toContain("export async function deleteChatSession");
    expect(apiSource).toContain("export function bulkDeleteChatSessions");
    expect(apiSource).toContain("/api/sessions/bulk-delete");
    expect(sessionChangeSource).toContain("bulkDeleteChatSessions");
    expect(lifecycleSource).not.toContain('fetchJson<SessionDetail>("/api/sessions"');
    expect(sessionChangeSource).not.toContain('fetchJson<SessionDetail>("/api/sessions"');
    expect(lifecycleSource).not.toContain('fetchJson<SessionDeleteResponse>(`/api/sessions/${sessionId}`');
    expect(sessionChangeSource).not.toContain('fetchJson<SessionDeleteResponse>(`/api/sessions/${sessionId}`');
  });

  it("owns session turn-command and Agent model-parameter transport outside chat route hooks", () => {
    expect(apiSource).toContain("/messages");
    expect(apiSource).toContain("/messages/edit-resubmit");
    expect(apiSource).toContain("/messages/regenerate");
    expect(apiSource).toContain("/stop");
    expect(apiSource).toContain("/guidance");
    expect(apiSource).toContain("/attachments");
    expect(apiSource).toContain("/llm-options");
    expect(apiSource).toContain("/model-parameters");
    expect(apiSource).toContain("parameters: SessionModelParametersUpdate");
    expect(apiSource).toContain("body: JSON.stringify(parameters)");
    expect(chatTypesSource).toContain("expectedAgentId: string");
    expect(chatTypesSource).toContain("expectedModelRef: string");
    expect(chatTypesSource).toContain("expectedConfigRevision: number");
    expect(composerSource).toContain("submitSessionMessage");
    expect(composerSource).toContain("editResubmitSessionMessage");
    expect(composerSource).toContain("regenerateSessionMessage");
    expect(composerSource).toContain("stopSessionTurn");
    expect(composerSource).toContain("submitSessionGuidance");
    expect(composerModelSource).toContain("postSessionImageAttachment");
    expect(mutationSource).toContain("updateSessionModelParameters");
    expect(detailQueriesSource).toContain("fetchSessionLlmOptions");
    expect(routeSource).toContain("useChatSessionDetailQueries(");
    expect(routeSource).toContain("expectedAgentId: options.agentId");
    expect(routeSource).not.toContain("updateSessionReasoningEffort");
    expect(composerSource).not.toContain("/api/sessions/");
    expect(composerActionsSource).not.toContain("/api/sessions/");
    expect(composerModelSource).not.toContain("/api/sessions/");
    expect(mutationSource).not.toContain("/reasoning-effort");
  });

  it("owns branch head and base-message transport outside the render layer", () => {
    expect(apiSource).toContain("export function switchSessionHead");
    expect(apiSource).toContain("/head");
    expect(apiSource).toContain("baseMessageId?: string");
    expect(composerSource).toContain("switchSessionHead");
    expect(composerSource).toContain("baseMessageId");
    expect(routeSource).toContain("switchHeadMutation");
    expect(surfaceModelSource).toContain("onSwitchMessageVersion");
  });

  it("owns review-candidate transport outside the chat lifecycle hook", () => {
    expect(apiSource).toContain("/chat-review-candidate");
    expect(apiSource).toContain('method: "POST"');
    expect(sessionChangeSource).toContain("createSessionChatReviewCandidate");
    expect(lifecycleSource).not.toContain("/chat-review-candidate");
    expect(sessionChangeSource).not.toContain("/chat-review-candidate");
  });

  it("owns session message curation transport outside the view layer", () => {
    expect(apiSource).toContain("export function fetchSessionMessageCuration");
    expect(apiSource).toContain("export function setSessionMessageCuration");
    expect(apiSource).toContain("`/api/sessions/${encodeURIComponent(sessionId)}/curation`");
    expect(apiSource).toContain(
      "`/api/sessions/${encodeURIComponent(sessionId)}/messages/${encodeURIComponent(messageId)}/curation`",
    );
    expect(apiSource).toContain("JSON.stringify({ action })");
    // The aggregate model tally rides the chat-review domain module instead.
    expect(evolutionApiSource).toContain("/api/chat-review/model-curation-stats");
    // View layers consume the api functions and never the endpoint strings.
    expect(conversationViewSource).toContain("fetchSessionMessageCuration");
    expect(conversationViewSource).toContain("setSessionMessageCuration");
    expect(conversationViewSource).not.toContain("/curation");
    expect(routeSource).not.toContain("/curation");
    expect(mutationSource).not.toContain("/curation");
    expect(lifecycleSource).not.toContain("/curation");
    expect(sessionChangeSource).not.toContain("/curation");
    expect(composerSource).not.toContain("Curation");
    expect(composerActionsSource).not.toContain("Curation");
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
