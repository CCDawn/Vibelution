import { describe, expect, it } from "vitest";

import apiSource from "./chat.ts?raw";
import routeSource from "../routes/chat/ChatCodingRouteWorkbench.tsx?raw";
import mutationSource from "../routes/chat/useChatSessionDetailMutations.ts?raw";
import lifecycleSource from "../routes/chat/useChatWorkspaceLifecycle.ts?raw";

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

  it("owns review-candidate transport outside the chat lifecycle hook", () => {
    expect(apiSource).toContain("/chat-review-candidate");
    expect(apiSource).toContain('method: "POST"');
    expect(lifecycleSource).toContain("createSessionChatReviewCandidate");
    expect(lifecycleSource).not.toContain("/chat-review-candidate");
  });
});
