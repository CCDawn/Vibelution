import type { ConversationMessage } from "../../api/types";
import type { AgentMessageSectionState } from "./agentMessageSections";
import { conversationMessageTurnId } from "./conversationMessageIdentity";
import {
  isCliAgentLifecycleMessage,
  isGroupRoomTranscriptMessage,
  isRuntimeNoticeMessage,
  isTurnErrorMessage,
} from "./conversationMessagePredicates";

export function isAssistantProcessThreadCandidate(
  message: ConversationMessage,
  sectionState: AgentMessageSectionState,
) {
  if (
    message.role !== "assistant"
    || isRuntimeNoticeMessage(message)
    || isCliAgentLifecycleMessage(message)
    || isGroupRoomTranscriptMessage(message)
  ) {
    return false;
  }
  return Boolean(
    message.streaming
    || String(message.streamStage ?? "").trim()
    || (message.timelineItems?.length ?? 0) > 0
    || sectionState.hasProcessSection
    || isTurnErrorMessage(message)
  );
}

export function conversationVisualThreadKey(
  message: ConversationMessage | undefined,
  sectionState: AgentMessageSectionState | undefined,
) {
  if (!message || !sectionState || !isAssistantProcessThreadCandidate(message, sectionState)) {
    return "";
  }
  const turnId = conversationMessageTurnId(message);
  if (turnId) {
    return `assistant-turn:${turnId}`;
  }
  return "assistant-process-thread";
}

export function shouldCompactConversationTurnHeader(
  previous: ConversationMessage | undefined,
  message: ConversationMessage,
  previousSectionState: AgentMessageSectionState | undefined,
  sectionState: AgentMessageSectionState,
) {
  const threadKey = conversationVisualThreadKey(message, sectionState);
  return Boolean(threadKey && threadKey === conversationVisualThreadKey(previous, previousSectionState));
}
