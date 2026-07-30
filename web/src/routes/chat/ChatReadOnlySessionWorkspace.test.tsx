import { describe, expect, it } from "vitest";

import source from "./ChatReadOnlySessionWorkspace.tsx?raw";

describe("ChatReadOnlySessionWorkspace", () => {
  it("reuses the formal Chat workspace and canonical conversation bridge", () => {
    expect(source).toContain("ChatSessionWorkspacePanel");
    expect(source).toContain("conversation={sessionDetail ? {");
    expect(source).toContain("messages: sessionDetail.messages");
    expect(source).toContain("showHeader: false");
    expect(source).toContain("showSessionOverview: false");
    expect(source).toContain("showComposer: false");
    expect(source).not.toContain("LazyConversationView");
  });

  it("projects both assistant and user identity into the formal transcript", () => {
    expect(source).toContain("assistantDisplayName: assistant.displayName");
    expect(source).toContain("assistantAvatarImageUrl: assistant.avatarImageUrl");
    expect(source).toContain("assistantAvatarFallback: assistant.avatarFallback");
    expect(source).toContain("userDisplayName: user.displayName");
    expect(source).toContain("userAvatarPreset: user.avatarPreset");
    expect(source).toContain("userAvatarImageUrl: user.avatarImageUrl");
  });

  it("keeps the embedded session read-only without manufacturing fallback messages", () => {
    expect(source).toContain("disabled: true");
    expect(source).toContain("actionDisabled: true");
    expect(source).toContain("hasBlockingError={hasSessionError && !sessionDetail}");
    expect(source).not.toContain("role: \"assistant\"");
    expect(source).not.toContain("snapshot");
  });
});
