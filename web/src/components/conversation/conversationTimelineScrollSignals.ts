import type { ConversationMessage } from "../../api/types";
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
      const contentSignal = message.streaming
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
        message.streaming ? 1 : 0,
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
    .filter((message) => message.streaming)
    .map((message) => {
      const renderState = renderStateForScrollSignal(message, agentRenderStatesByMessageId);
      const processSignal = options.includeMentalSignals === false
        ? renderState.processSignalWithoutMental
        : renderState.processSignal;
      return [message.id, renderState.renderedTextLength, processSignal].join(":");
    })
    .join("|");
}
