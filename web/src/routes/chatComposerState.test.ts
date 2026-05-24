import { describe, expect, it } from "vitest";

import {
  latestUserMessageId,
  resolveComposerDraftValue,
  resolveLatestEditTarget,
  type ChatEditTarget,
} from "./chatComposerState";

describe("chat composer state", () => {
  it("keeps normal draft text visible when the user is not editing", () => {
    expect(resolveComposerDraftValue("normal message", null, null)).toBe("normal message");
  });

  it("keeps draft text for a valid latest-user edit target", () => {
    const target: ChatEditTarget = { messageId: "message-user-2", original: "second prompt" };
    const resolved = resolveLatestEditTarget(target, "message-user-2");

    expect(resolved).toEqual(target);
    expect(resolveComposerDraftValue("edited prompt", target, resolved)).toBe("edited prompt");
  });

  it("hides draft text for a stale edit target until the route clears it", () => {
    const target: ChatEditTarget = { messageId: "message-user-1", original: "first prompt" };
    const resolved = resolveLatestEditTarget(target, "message-user-2");

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
});
