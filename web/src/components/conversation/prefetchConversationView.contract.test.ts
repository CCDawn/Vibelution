import { describe, expect, it } from "vitest";

import lazySource from "./LazyConversationView.tsx?raw";
import prefetchSource from "./prefetchConversationView.ts?raw";
import routeSource from "../../routes/ChatCodingRoute.tsx?raw";
import workspaceSource from "../../routes/chat/ChatSessionWorkspacePanel.tsx?raw";

describe("conversation view load contract (T1/T2)", () => {
  it("keeps ConversationView behind lazy + prefetch helpers", () => {
    expect(lazySource).toContain('import("./ConversationView")');
    expect(prefetchSource).toContain('import("./ConversationView")');
    expect(lazySource).toContain("prefetchConversationView");
  });

  it("warms ConversationView after session intent from Chat route", () => {
    expect(routeSource).toContain("prefetchConversationView");
    expect(routeSource).toContain("requestIdleCallback");
  });

  it("does not mount ConversationView without a session surface", () => {
    expect(workspaceSource).toContain("if (!activeSessionId && !sessionsPending)");
    expect(workspaceSource).toContain("ChatConversationComposerBridge");
    expect(workspaceSource).toContain('import("./ChatFilePreviewPanel")');
    expect(workspaceSource).toContain('import("./ChatToolApprovalDialog")');
  });
});
