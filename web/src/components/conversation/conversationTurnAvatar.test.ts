import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import type { ConversationMessage } from "../../api/types";
import {
  resolveMessageTurnAvatar,
  userAvatarSymbol,
  type TurnAvatarResolution,
} from "./conversationTurnAvatar";

const conversationViewSource = readFileSync(new URL("./ConversationView.tsx", import.meta.url), "utf8");

function message(patch: Partial<ConversationMessage> = {}): ConversationMessage {
  return {
    id: "message-a",
    role: "assistant",
    content: "",
    timestamp: "2026-07-04T07:16:00Z",
    ...patch,
  };
}

function resolveAvatarOptions(
  patch: Partial<Parameters<typeof resolveMessageTurnAvatar>[1]> = {},
): Parameters<typeof resolveMessageTurnAvatar>[1] {
  return {
    assistantLabel: "Assistant",
    userAvatarLabel: "U",
    agentInboxMessage: false,
    groupTranscriptMessage: false,
    ...patch,
  };
}

describe("conversation turn avatar identity helpers", () => {
  it("normalizes user avatar preset symbols with display-name fallback", () => {
    expect(userAvatarSymbol("spark", "Owner")).toBe("*");
    expect(userAvatarSymbol("codex", "Owner")).toBe("C");
    expect(userAvatarSymbol("minimal", "Owner")).toBe(".");
    expect(userAvatarSymbol("custom", "vibe owner")).toBe("V");
    expect(userAvatarSymbol(undefined, "")).toBe("U");
  });

  it("resolves assistant and user avatar content without depending on React rendering", () => {
    expect(resolveMessageTurnAvatar(message(), resolveAvatarOptions({
      assistantAvatarImageUrl: "/avatar/assistant.png",
      assistantAvatarFallback: "助",
    }))).toEqual({ imageUrl: "/avatar/assistant.png", fallback: "助" });

    expect(resolveMessageTurnAvatar(message({
      role: "assistant",
    }), resolveAvatarOptions({
      assistantLabel: "Companion Agent",
    }))).toEqual({ imageUrl: undefined, fallback: "Co" });

    expect(resolveMessageTurnAvatar(message({
      role: "user",
    }), resolveAvatarOptions({
      userAvatarImageUrl: "/avatar/user.png",
      userAvatarLabel: "我",
    }))).toEqual({ imageUrl: "/avatar/user.png", fallback: "我" });
  });

  it("prefers group transcript and agent inbox avatar rules before role fallbacks", () => {
    expect(resolveMessageTurnAvatar(message(), resolveAvatarOptions({
      groupTranscriptMessage: true,
    }))).toEqual({ icon: "groupTranscript" });

    const resolvedInboxAvatar: TurnAvatarResolution = {
      imageUrl: "/agent/inbox.png",
      fallback: "IN",
    };
    expect(resolveMessageTurnAvatar(message(), resolveAvatarOptions({
      agentInboxMessage: true,
      resolveTurnAvatar: () => resolvedInboxAvatar,
    }))).toEqual(resolvedInboxAvatar);
    expect(resolveMessageTurnAvatar(message(), resolveAvatarOptions({
      agentInboxMessage: true,
    }))).toEqual({ fallback: "?" });
  });

  it("keeps turn avatar identity helpers outside ConversationView", () => {
    expect(conversationViewSource).toContain("./conversationTurnAvatar");
    expect(conversationViewSource).not.toContain("function userAvatarSymbol");
    expect(conversationViewSource).not.toContain("function resolveMessageTurnAvatar");
    expect(conversationViewSource).not.toContain("export type TurnAvatarResolution =");
    expect(conversationViewSource).not.toContain("export type { TurnAvatarResolution }");
  });
});
