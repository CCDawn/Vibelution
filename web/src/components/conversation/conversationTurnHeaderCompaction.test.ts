import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import type { ConversationMessage } from "../../api/types";
import type { AgentMessageSectionState } from "./agentMessageSections";
import {
  conversationVisualThreadKey,
  isAssistantProcessThreadCandidate,
  shouldCompactConversationTurnHeader,
} from "./conversationTurnHeaderCompaction";

const conversationViewSource = readFileSync(new URL("./ConversationView.tsx", import.meta.url), "utf8");

const processSectionState: AgentMessageSectionState = {
  userText: "",
  answerText: "",
  processText: "",
  hasUserContent: false,
  hasResponseBlock: false,
  hasProcessSection: true,
  hasFeedbackTimeline: false,
  hasContextSections: false,
  hasAttachments: false,
  hasReferences: false,
};

const answerOnlySectionState: AgentMessageSectionState = {
  ...processSectionState,
  hasProcessSection: false,
};

function assistantMessage(patch: Partial<ConversationMessage> = {}): ConversationMessage {
  return {
    id: "assistant-message",
    role: "assistant",
    content: "",
    timestamp: "2026-07-04T07:02:00Z",
    ...patch,
  };
}

describe("conversation turn header compaction", () => {
  it("identifies assistant process-thread candidates without compacting special messages", () => {
    expect(isAssistantProcessThreadCandidate(
      assistantMessage({ metadata: { turnId: "turn-a" } }),
      processSectionState,
    )).toBe(true);
    expect(isAssistantProcessThreadCandidate(
      assistantMessage({ streaming: true }),
      answerOnlySectionState,
    )).toBe(true);
    expect(isAssistantProcessThreadCandidate(
      assistantMessage({ metadata: { kind: "cli_agent_lifecycle" } }),
      processSectionState,
    )).toBe(false);
    expect(isAssistantProcessThreadCandidate(
      assistantMessage({ metadata: { kind: "group_room_transcript" } }),
      processSectionState,
    )).toBe(false);
    expect(isAssistantProcessThreadCandidate(
      { ...assistantMessage(), role: "user" },
      processSectionState,
    )).toBe(false);
  });

  it("uses turn id when present and adjacent process thread fallback otherwise", () => {
    expect(conversationVisualThreadKey(
      assistantMessage({ metadata: { turnId: "live:turn-a" } }),
      processSectionState,
    )).toBe("assistant-turn:turn-a");
    expect(conversationVisualThreadKey(
      assistantMessage(),
      processSectionState,
    )).toBe("assistant-process-thread");
    expect(conversationVisualThreadKey(
      assistantMessage(),
      answerOnlySectionState,
    )).toBe("");
  });

  it("compacts only consecutive assistant messages from the same visual thread", () => {
    const previous = assistantMessage({ id: "previous", metadata: { turnId: "turn-a" } });
    const sameTurn = assistantMessage({ id: "same", metadata: { turnId: "live:turn-a" } });
    const nextTurn = assistantMessage({ id: "next", metadata: { turnId: "turn-b" } });

    expect(shouldCompactConversationTurnHeader(
      previous,
      sameTurn,
      processSectionState,
      processSectionState,
    )).toBe(true);
    expect(shouldCompactConversationTurnHeader(
      previous,
      nextTurn,
      processSectionState,
      processSectionState,
    )).toBe(false);
    expect(shouldCompactConversationTurnHeader(
      undefined,
      sameTurn,
      undefined,
      processSectionState,
    )).toBe(false);
  });

  it("keeps turn-header compaction helpers outside ConversationView", () => {
    expect(conversationViewSource).toContain("./conversationTurnHeaderCompaction");
    expect(conversationViewSource).not.toContain("function isAssistantProcessThreadCandidate");
    expect(conversationViewSource).not.toContain("function conversationVisualThreadKey");
    expect(conversationViewSource).not.toContain("function shouldCompactConversationTurnHeader");
  });
});
