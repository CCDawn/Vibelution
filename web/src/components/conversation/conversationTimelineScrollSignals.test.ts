import { describe, expect, it } from "vitest";

import type { ConversationMessage } from "../../api/types";
import { conversationMessageToAgentMessage } from "../../agent-thread";
import { buildAgentMessageRenderState } from "./agentMessageRenderState";
import conversationViewSource from "./ConversationView.tsx?raw";
import {
  buildStreamingTimelineScrollSignal,
  buildTimelineScrollSignal,
} from "./conversationTimelineScrollSignals";

function renderStatesForMessages(messages: ConversationMessage[]) {
  return new Map(
    messages.map((message) => [
      message.id,
      buildAgentMessageRenderState(conversationMessageToAgentMessage(message)),
    ]),
  );
}

function timelineSignalFor(messages: ConversationMessage[]) {
  return buildTimelineScrollSignal(messages, renderStatesForMessages(messages));
}

function timelineSignalWithoutMentalFor(messages: ConversationMessage[]) {
  return buildTimelineScrollSignal(messages, renderStatesForMessages(messages), { includeMentalSignals: false });
}

function streamingTimelineSignalFor(messages: ConversationMessage[]) {
  return buildStreamingTimelineScrollSignal(messages, renderStatesForMessages(messages));
}

describe("conversation timeline scroll signals", () => {
  const baseAssistantMessage: ConversationMessage = {
    id: "message-assistant",
    role: "assistant",
    content: "",
    timestamp: "2026-05-22T00:01:00Z",
    streaming: true,
    feedbackEvents: [{ sequence: 1, kind: "tool", name: "read_file", status: "running" }],
  };

  it("keeps scroll signal helpers outside the React component file", () => {
    expect(conversationViewSource).toContain("from \"./conversationTimelineScrollSignals\"");
    expect(conversationViewSource).toContain("buildTimelineScrollSignal(timelineMessages, agentRenderStatesByMessageId, {");
    expect(conversationViewSource).toContain("buildStreamingTimelineScrollSignal(streamingTimelineMessages, agentRenderStatesByMessageId, {");
    expect(conversationViewSource).not.toContain("function renderStateForScrollSignal");
    expect(conversationViewSource).not.toContain("export function buildTimelineScrollSignal");
    expect(conversationViewSource).not.toContain("export function buildStreamingTimelineScrollSignal");
  });

  it("changes the streaming signal when an already-visible tool receives its exact start revision", () => {
    const placeholder: ConversationMessage = {
      ...baseAssistantMessage,
      turnId: "turn-a",
      status: "running",
      turnItems: [{
        version: 3,
        id: "tool-item-a",
        itemId: "tool-item-a",
        sessionId: "session-a",
        turnId: "turn-a",
        type: "tool_call",
        status: "pending",
        sequence: 1,
        revision: 1,
        createdAt: "2026-05-22T00:01:01Z",
        updatedAt: "2026-05-22T00:01:01Z",
        callId: "call-a",
        toolName: "glob_tool",
      }],
    };
    const exactStart: ConversationMessage = {
      ...placeholder,
      turnItems: [{
        ...placeholder.turnItems![0],
        revision: 2,
        metadata: { executionStartedAtEpochMs: 1779408061500 },
      }],
    };

    expect(streamingTimelineSignalFor([placeholder])).not.toBe(
      streamingTimelineSignalFor([exactStart]),
    );
    expect(streamingTimelineSignalFor([exactStart])).toContain("call-a:pending:2:1779408061500");
  });
});
