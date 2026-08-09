import type { ConversationMessage, SessionTurnItem } from "../../api/types";
import { assistantTurnIsStreaming } from "../../routes/chatTurnProtocol";
import type { AgentMessageRenderState } from "./agentMessageRenderState";

function renderStateForScrollSignal(
  message: ConversationMessage,
  agentRenderStatesByMessageId: Map<string, AgentMessageRenderState>,
) {
  return agentRenderStatesByMessageId.get(message.id) ?? {
    processSignal: "",
    processSignalWithoutMental: "",
    renderedTextLength: 0,
  };
}

export type TimelineScrollSignalOptions = {
  includeMentalSignals?: boolean;
};

export function buildTimelineScrollSignal(
  messages: ConversationMessage[],
  agentRenderStatesByMessageId: Map<string, AgentMessageRenderState>,
  options: TimelineScrollSignalOptions = {},
) {
  return messages
    .map((message) => {
      const renderState = renderStateForScrollSignal(message, agentRenderStatesByMessageId);
      const processSignal = options.includeMentalSignals === false
        ? renderState.processSignalWithoutMental
        : renderState.processSignal;
      const streaming = assistantTurnIsStreaming(message);
      const contentSignal = streaming
        ? ""
        : renderState.renderedTextLength;
      const metadataSignal = message.metadata
        ? [
            String(message.metadata.kind ?? ""),
            String(message.metadata.status ?? ""),
            String(message.metadata.artifactId ?? ""),
            String(message.metadata.imageUrl ?? ""),
            String(message.metadata.downloadUrl ?? ""),
          ].join(":")
        : "";
      return [
        message.id,
        contentSignal,
        processSignal,
        metadataSignal,
        streaming ? 1 : 0,
      ].join(":");
    })
    .join("|");
}

export function buildStreamingTimelineScrollSignal(
  messages: ConversationMessage[],
  agentRenderStatesByMessageId: Map<string, AgentMessageRenderState>,
  options: TimelineScrollSignalOptions = {},
) {
  return messages
    .filter(assistantTurnIsStreaming)
    .map((message) => {
      const renderState = renderStateForScrollSignal(message, agentRenderStatesByMessageId);
      const processSignal = options.includeMentalSignals === false
        ? renderState.processSignalWithoutMental
        : renderState.processSignal;
      return [
        message.id,
        renderState.renderedTextLength,
        processSignal,
        streamingToolRevisionSignal(message),
      ].join(":");
    })
    .join("|");
}

function streamingToolRevisionSignal(message: ConversationMessage) {
  if (message.role !== "assistant") {
    return "";
  }
  return message.turnItems
    .filter((item): item is Extract<SessionTurnItem, { type: "tool_call" }> => (
      item.type === "tool_call" && (item.status === "pending" || item.status === "running")
    ))
    .map((item) => [
      item.callId || item.itemId || item.id,
      item.status,
      item.revision,
      item.metadata?.executionStartedAtEpochMs ?? "",
    ].join(":"))
    .join(",");
}
