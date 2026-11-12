import { describe, expect, it } from "vitest";

import {
  rekeySessionComposerEntry,
  latestUserMessageId,
  resolveActiveEditTarget,
  resolveComposerDraftValue,
  type ChatEditTarget,
} from "./chatComposerState";

describe("chat composer state", () => {
  it("moves the latest temp draft without changing another session", () => {
    expect(rekeySessionComposerEntry({ temp: "latest", b: "other" }, "temp", "real")).toEqual({ real: "latest", b: "other" });
  });

  it("preserves an existing destination, including an intentionally empty draft", () => {
    expect(rekeySessionComposerEntry({ temp: "old", real: "", b: "other" }, "temp", "real")).toEqual({ real: "", b: "other" });
    const entries = { real: "new" };
    expect(rekeySessionComposerEntry(entries, "temp", "real")).toBe(entries);
    expect(rekeySessionComposerEntry(entries, "real", "real")).toBe(entries);
  });
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

  it("keeps the seeded draft when a re-projection re-keys the edited row", () => {
    const target: ChatEditTarget = { messageId: "message-user-1", original: "first prompt" };
    const resolved = resolveActiveEditTarget(target, [
      { id: "message-user-2", role: "user" },
      { id: "message-assistant-2", role: "assistant" },
    ]);

    // A stop or a branch re-key can re-identify the row. Blanking the draft here
    // is what left users staring at an empty editor with a disabled submit.
    expect(resolved).toEqual(target);
    expect(resolveComposerDraftValue("stale edit draft", target, resolved)).toBe("stale edit draft");
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
