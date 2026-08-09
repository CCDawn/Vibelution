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
  });});
