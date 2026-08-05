/**
 * Pure memo helpers for ConversationView turn rows (Wave 3 extract).
 */
import type { ReactNode } from "react";

import type { ConversationMessage } from "../../api/types";
import type { AgentMessage } from "../../agent-thread/types";
import type { AgentMessageRenderState } from "./agentMessageRenderState";
import type { AgentMessageTimelineRowIdentity } from "./agentMessageTimelineRows";
import type { CodexTranscriptCell } from "./codexTranscriptCells";
import type { TurnAvatarResolution } from "./conversationTurnAvatar";

export function transcriptCellSequenceMatches(
  previous: readonly CodexTranscriptCell[],
  next: readonly CodexTranscriptCell[],
) {
  return previous.length === next.length && previous.every((cell, index) => cell === next[index]);
}

export function conversationPerformanceNowMs() {
  return typeof performance === "undefined" ? Date.now() : performance.now();
}

export type ConversationTurnRowProps = {
  message: ConversationMessage;
  previousMessage?: ConversationMessage;
  agentMessage?: AgentMessage;
  agentRenderState?: AgentMessageRenderState;
  previousAgentRenderState?: AgentMessageRenderState;
  codexTranscriptCells?: CodexTranscriptCell[];
  rowIdentity: AgentMessageTimelineRowIdentity;
  defaultResponseExpanded: boolean;
  latestUserMessageId: string;
  editingMessageId?: string;
  editUserMessageLabel?: string;
  editUserMessageDisabled?: boolean;
  composerPlaceholder: string;
  answerOnlyProcessMode: boolean;
  showMentalSnapshots: boolean;
  lang: "zh" | "en";
  assistantLabel: string;
  assistantAvatarImageUrl?: string;
  assistantAvatarFallback?: string;
  userLabel: string;
  userAvatarLabel: string;
  userAvatarImageUrl?: string;
  operationLabels: {
    thought: string;
    mental: string;
    status: string;
  };
  resolveTurnAvatar?: (message: ConversationMessage) => TurnAvatarResolution | undefined;
  onEditUserMessage?: (message: ConversationMessage) => void;
  sectionExpansionForMessage: Record<string, boolean>;
  computerUseStateForMessage: string;
  imageArtifactUrlsBeforeMessage?: Set<string>;
  renderTurn: () => ReactNode;
};

export function agentMessageTimelineRowIdentityIsEqual(
  previous: AgentMessageTimelineRowIdentity,
  next: AgentMessageTimelineRowIdentity,
) {
  return previous.messageId === next.messageId
    && previous.rowKey === next.rowKey
    && previous.messageKey === next.messageKey
    && previous.processKey === next.processKey
    && previous.answerKey === next.answerKey;
}

export function conversationTurnRowPropsAreEqual(
  previous: ConversationTurnRowProps,
  next: ConversationTurnRowProps,
) {
  return previous.message === next.message
    && previous.previousMessage === next.previousMessage
    && previous.agentMessage === next.agentMessage
    && previous.agentRenderState === next.agentRenderState
    && previous.previousAgentRenderState === next.previousAgentRenderState
    && previous.codexTranscriptCells === next.codexTranscriptCells
    && agentMessageTimelineRowIdentityIsEqual(previous.rowIdentity, next.rowIdentity)
    && previous.defaultResponseExpanded === next.defaultResponseExpanded
    && previous.latestUserMessageId === next.latestUserMessageId
    && previous.editingMessageId === next.editingMessageId
    && previous.editUserMessageLabel === next.editUserMessageLabel
    && previous.editUserMessageDisabled === next.editUserMessageDisabled
    && previous.composerPlaceholder === next.composerPlaceholder
    && previous.answerOnlyProcessMode === next.answerOnlyProcessMode
    && previous.showMentalSnapshots === next.showMentalSnapshots
    && previous.lang === next.lang
    && previous.assistantLabel === next.assistantLabel
    && previous.assistantAvatarImageUrl === next.assistantAvatarImageUrl
    && previous.assistantAvatarFallback === next.assistantAvatarFallback
    && previous.userLabel === next.userLabel
    && previous.userAvatarLabel === next.userAvatarLabel
    && previous.userAvatarImageUrl === next.userAvatarImageUrl
    && previous.operationLabels === next.operationLabels
    && previous.resolveTurnAvatar === next.resolveTurnAvatar
    && previous.onEditUserMessage === next.onEditUserMessage
    && previous.sectionExpansionForMessage === next.sectionExpansionForMessage
    && previous.computerUseStateForMessage === next.computerUseStateForMessage
    && previous.imageArtifactUrlsBeforeMessage === next.imageArtifactUrlsBeforeMessage;
}
