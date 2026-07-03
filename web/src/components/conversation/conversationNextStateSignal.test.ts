import { describe, expect, it } from "vitest";

import type { ChatNextStateSignalSummary } from "../../api/types";
import chatCodingRouteSource from "../../routes/ChatCodingRoute.tsx?raw";
import conversationViewSource from "./ConversationView.tsx?raw";
import { shouldShowNextStateSignalInConversation } from "./conversationNextStateSignal";

function nextStateSignal(kind: ChatNextStateSignalSummary["kind"]): ChatNextStateSignalSummary {
  return {
    signalId: `signal-${kind}`,
    sessionId: "session-1",
    turnId: "turn-1",
    source: "user",
    kind,
    polarity: "neutral",
    mode: "directive",
    relatedEventCode: `conversation.${kind}`,
    createdAt: "2026-05-25T00:19:12Z",
    summary: kind,
  };
}

describe("shouldShowNextStateSignalInConversation", () => {
  it("shows user continue signals only while the conversation phase is busy", () => {
    const signal = nextStateSignal("user_continues");

    expect(shouldShowNextStateSignalInConversation(signal, "ready")).toBe(false);
    expect(shouldShowNextStateSignalInConversation(signal, "completed")).toBe(false);
    expect(shouldShowNextStateSignalInConversation(signal, "queued")).toBe(true);
    expect(shouldShowNextStateSignalInConversation(signal, " running ")).toBe(true);
    expect(shouldShowNextStateSignalInConversation(signal, "STOPPING")).toBe(true);
  });

  it("keeps non-continue signals visible after the turn finishes", () => {
    expect(shouldShowNextStateSignalInConversation(nextStateSignal("user_stops"), "ready")).toBe(true);
    expect(shouldShowNextStateSignalInConversation(nextStateSignal("tool_error"), "completed")).toBe(true);
  });

  it("keeps next-state signal filtering out of ConversationView and route imports", () => {
    const routeConversationViewImportEnd = chatCodingRouteSource.indexOf(
      'from "../components/conversation/ConversationView";',
    );
    const routeConversationViewImportStart = chatCodingRouteSource.lastIndexOf(
      "import {",
      routeConversationViewImportEnd,
    );
    const routeConversationViewImport = chatCodingRouteSource.slice(
      routeConversationViewImportStart,
      routeConversationViewImportEnd,
    );

    expect(conversationViewSource).toContain('from "./conversationNextStateSignal"');
    expect(conversationViewSource).not.toMatch(
      /function isBusyConversationPhase|export function shouldShowNextStateSignalInConversation/,
    );
    expect(chatCodingRouteSource).toContain('from "../components/conversation/conversationNextStateSignal"');
    expect(routeConversationViewImport).not.toContain("shouldShowNextStateSignalInConversation");
  });
});
