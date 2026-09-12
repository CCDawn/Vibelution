import { describe, expect, it } from "vitest";

import {
  latestUserMessageId,
  resolveActiveEditTarget,
  resolveComposerDraftValue,
  type ChatEditTarget,
} from "./chatComposerState";

describe("chat composer state", () => {
  it("keeps normal draft text visible when the user is not editing", () => {
    expect(resolveComposerDraftValue("normal message", null, null)).toBe("normal message");
  });

  it("keeps draft text for an edit target still on the active path", () => {
    const target: ChatEditTarget = { messageId: "message-user-2", original: "second prompt" };
    const resolved = resolveActiveEditTarget(target, [
      { id: "message-user-1", role: "user" },
      { id: "message-assistant-1", role: "assistant" },
      { id: "message-user-2", role: "user" },
    ]);

    expect(resolved).toEqual(target);
    expect(resolveComposerDraftValue("edited prompt", target, resolved)).toBe("edited prompt");
  });

  it("keeps an older branch-mode edit target that is no longer the latest message", () => {
    const target: ChatEditTarget = {
      messageId: "message-user-1",
      nodeId: "session-live-node-1",
      original: "first prompt",
    };
    const resolved = resolveActiveEditTarget(target, [
      { id: "message-user-1", role: "user" },
      { id: "message-assistant-1", role: "assistant" },
      { id: "message-user-2", role: "user" },
    ]);

    expect(resolved).toEqual(target);
    expect(resolveComposerDraftValue("edited first prompt", target, resolved)).toBe("edited first prompt");
  });

  it("hides draft text for an edit target that left the active path", () => {
    const target: ChatEditTarget = { messageId: "message-user-1", original: "first prompt" };
    const resolved = resolveActiveEditTarget(target, [
      { id: "message-user-2", role: "user" },
      { id: "message-assistant-2", role: "assistant" },
    ]);

    expect(resolved).toBeNull();
    expect(resolveComposerDraftValue("stale edit draft", target, resolved)).toBe("");
  });

  it("finds only the latest user message id", () => {
    expect(
      latestUserMessageId([
        { id: "message-user-1", role: "user" },
        { id: "message-assistant-1", role: "assistant" },
        { id: "message-user-2", role: "user" },
      ]),
    ).toBe("message-user-2");
  });

  it("skips running-turn steer records when resolving the editable latest user message", () => {
    expect(
      latestUserMessageId([
        { id: "message-user-2", role: "user" },
        { id: "message-assistant-1", role: "assistant" },
        { id: "message-steer-1", role: "user", metadata: { kind: "user_guidance" } },
      ]),
    ).toBe("message-user-2");
  });
});
