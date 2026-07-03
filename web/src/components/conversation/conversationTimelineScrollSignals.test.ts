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
    toolCalls: [{ name: "read_file", status: "running" }],
  };

  it("keeps scroll signal helpers outside the React component file", () => {
    expect(conversationViewSource).toContain("from \"./conversationTimelineScrollSignals\"");
    expect(conversationViewSource).toContain("buildTimelineScrollSignal(timelineMessages, agentRenderStatesByMessageId, {");
    expect(conversationViewSource).toContain("buildStreamingTimelineScrollSignal(streamingTimelineMessages, agentRenderStatesByMessageId, {");
    expect(conversationViewSource).not.toContain("function renderStateForScrollSignal");
    expect(conversationViewSource).not.toContain("export function buildTimelineScrollSignal");
    expect(conversationViewSource).not.toContain("export function buildStreamingTimelineScrollSignal");
  });

  it("changes when a tool status changes without changing tool count", () => {
    const before = timelineSignalFor([baseAssistantMessage]);
    const after = timelineSignalFor([
      {
        ...baseAssistantMessage,
        toolCalls: [{ name: "read_file", status: "done" }],
      },
    ]);

    expect(after).not.toBe(before);
  });

  it("changes when a tool summary appears without changing message text length", () => {
    const before = timelineSignalFor([baseAssistantMessage]);
    const after = timelineSignalFor([
      {
        ...baseAssistantMessage,
        toolCalls: [{ name: "read_file", status: "running", summary: "opened session_service.py" }],
      },
    ]);

    expect(after).not.toBe(before);
  });

  it("changes when a mental snapshot becomes visible", () => {
    const before = timelineSignalFor([baseAssistantMessage]);
    const after = timelineSignalFor([
      {
        ...baseAssistantMessage,
        mentalSnapshot: {
          mood: "focused",
          feeling: "tracking tool output",
          whisper: "",
          summary: "Following the active tool result",
          cognitiveState: "productive",
          confidence: 0.7,
          sampleSize: 1,
          interventionCount: 0,
          updatedAt: "2026-05-22T00:01:05Z",
          source: "runtime",
        },
      },
    ]);

    expect(after).not.toBe(before);
  });

  it("ignores mental snapshot signal changes when mental snapshots are hidden", () => {
    const before = timelineSignalWithoutMentalFor([baseAssistantMessage]);
    const after = timelineSignalWithoutMentalFor([
      {
        ...baseAssistantMessage,
        mentalSnapshot: {
          mood: "focused",
          feeling: "tracking tool output",
          whisper: "",
          summary: "Following the active tool result",
          cognitiveState: "productive",
          confidence: 0.7,
          sampleSize: 1,
          interventionCount: 0,
          updatedAt: "2026-05-22T00:01:05Z",
          source: "runtime",
        },
      },
    ]);

    expect(after).toBe(before);
  });

  it("does not change the synchronous scroll signal when streaming text grows", () => {
    const before = timelineSignalFor([baseAssistantMessage]);
    const after = timelineSignalFor([
      {
        ...baseAssistantMessage,
        content: "streaming response text is still growing",
      },
    ]);

    expect(after).toBe(before);
  });

  it("tracks streaming text growth in the deferred scroll signal", () => {
    const before = streamingTimelineSignalFor([baseAssistantMessage]);
    const after = streamingTimelineSignalFor([
      {
        ...baseAssistantMessage,
        content: "streaming response text is still growing",
      },
    ]);

    expect(after).not.toBe(before);
  });

  it("changes the synchronous scroll signal when settled text changes", () => {
    const before = timelineSignalFor([{ ...baseAssistantMessage, streaming: false }]);
    const after = timelineSignalFor([
      {
        ...baseAssistantMessage,
        streaming: false,
        content: "settled response text changed",
      },
    ]);

    expect(after).not.toBe(before);
  });
});
