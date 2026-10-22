import {
  ArrowLeftRight,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CircleMinus,
  Copy,
  FileText,
  Gauge,
  GitFork,
  ListPlus,
  LoaderCircle,
  MessageSquareText,
  Pencil,
  RefreshCw,
  Sparkles,
  TerminalSquare,
} from "lucide-react";
import React, { useLayoutEffect, type RefObject } from "react";

import type {
  ConversationAttachment,
  ConversationMessage,
  SessionMessageCurationAction,
  SessionReferenceAttachment,
} from "../../api/types";
import type { AgentMessage } from "../../agent-thread/types";
import type { TranslationKey } from "../../i18n/dictionaryTypes";
import {
  assistantFinalAnswerText,
  assistantTurnIsInFlight,
  assistantTurnIsStreaming,
  hasTerminalCanonicalTurnOutcome,
} from "../../routes/chatTurnProtocol";
import { AgentMessageTurnView } from "./AgentMessageTurnView";
import { AgentUserContentSectionView } from "./AgentUserContentSectionView";
import type { AgentMessageSectionState } from "./agentMessageSections";
import { buildAgentMessageRenderState, type AgentMessageRenderState } from "./agentMessageRenderState";
import { buildAgentMessageTimelineItems } from "./agentMessageTimeline";
import type { AgentMessageTimelineRowIdentity } from "./agentMessageTimelineRows";
import {
  buildAgentMessageOperationGroups,
  type AgentMessageOperation,
  type AgentMessageOperationGroups,
} from "./agentMessageOperations";
import { resolveAssistantDisplayPlan } from "./assistantDisplayPlan";
import {
  companionMessageSpokenText,
  companionUnrepeatedSpeech,
  previousCompanionSpokenText,
} from "./companionSpokenDisplay";
import { shouldSubmitComposerOnKeydown } from "./composerShortcuts";
import { ConversationActiveTurnStatusNote } from "./ConversationActiveTurnStatusNote";
import { ConversationImageArtifactView } from "./ConversationImageArtifactView";
import type { ConversationImagePreviewRequest } from "./ConversationImagePreviewDialog";
import { ConversationTodoChecklist } from "./ConversationTodoChecklist";
import { ConversationTurnAvatarContent } from "./ConversationTurnAvatarContent";
import type { CodexTranscriptSurface } from "./codexNativeTranscriptSurface";
import type { createConversationAuxiliaryPanels } from "./conversationAuxiliaryPanels";
import type { createConversationCodexSurface } from "./conversationCodexSurface";
import {
  buildComputerUseStateForMessage,
  COMPUTER_USE_TOOL_NAME,
  type ComputerUseResult,
} from "./conversationComputerUseState";
import { operationGroupsWithFeedbackStatusPlaceholder } from "./conversationFeedbackStatusPresentation";
import { renderConversationInlineMarkdown } from "./conversationInlineMarkdown";
import {
  isNoFinalAnswerStatusContent,
  isStreamingStatusPlaceholderContent,
} from "./conversationInternalStatus";
import { latestAgentMentalPart } from "./conversationMentalState";
import { resolveMessageCurationState, type MessageCurationDecision } from "./conversationMessageCuration";
import {
  imageArtifactForMessage,
  isAgentInboxMessage,
  isForkedSessionMarkerMessage,
  isGroupRoomTranscriptMessage,
  isSteerGuidanceMessage,
  isTurnErrorMessage,
  researchOrgMessageChips,
} from "./conversationMessagePredicates";
import type { ConversationModelSwitchBoundary } from "./conversationModelSwitch";
import type { createConversationOperationGroups } from "./conversationOperationGroups";
import {
  shouldRenderCompactActiveTurnPlaceholder as resolveShouldRenderCompactActiveTurnPlaceholder,
} from "./conversationOperationPresentation";
import {
  isRunningOperationStatus,
  operationCollectionTone,
} from "./conversationOperationState";
import type { createConversationReActRows } from "./conversationReActRows";
import type { createConversationResponseBlocks } from "./conversationResponseBlocks";
import {
  shouldShowAgentResponseBlock as resolveShouldShowAgentResponseBlock,
} from "./conversationResponseSegmentPresentation";
import type { createConversationSpecialRows } from "./conversationSpecialRows";
import {
  agentInboxSourceLabel,
  agentInboxSummary,
  groupRoomTranscriptLabel,
} from "./conversationSpecialMessagePresentation";
import { replaceDividerPlaceholder } from "./conversationThoughtUnits";
import type { createConversationTimelineItems } from "./conversationTimelineItems";
import { deriveLatestTodoChecklist } from "./conversationTodoChecklistModel";
import { resolveMessageTurnAvatar } from "./conversationTurnAvatar";
import {
  buildConversationTurnErrorReasonRows,
  resolveConversationTurnErrorRecoveryAction,
  resolveConversationTurnErrorType,
  resolveTurnErrorTypeLabelKey,
} from "./conversationTurnErrorPresentation";
import { shouldCompactConversationTurnHeader } from "./conversationTurnHeaderCompaction";
import {
  conversationTurnRowPropsAreEqual,
  type ConversationTurnRowProps,
} from "./conversationTurnRowMemo";
import { resolveConversationTurnUsageLabel } from "./conversationTurnUsageLabel";
import type { ConversationForkScope } from "./conversationViewTypes";
import type { ResponseSegment } from "./messageResponseSegments";
import { VActionGroup, VButton, VChip, VNativeTextarea } from "../vui";
import styles from "./ConversationView.styles";

// Group-transcript rows are chat lines, not documents: they render through the
// shared pure inline renderer (code/link/strong only) with the ConversationView
// styles as the single visual source, while answer bodies keep the full
// markdown renderer.
const groupTranscriptInlineClassNames = {
  inlineCode: styles.inlineCode,
  inlineLink: styles.inlineLink,
  inlineStrong: styles.inlineStrong,
};

const EMPTY_SECTION_EXPANSION: Record<string, boolean> = {};

/** Context chrome loads only when a turn actually has context sections. */
const AgentContextSectionsView = React.lazy(() =>
  import("./AgentContextSectionsView").then((module) => ({
    default: module.AgentContextSectionsView,
  })),
);

const ConversationTurnRow = React.memo(function ConversationTurnRow({
  renderTurn,
}: ConversationTurnRowProps) {
  return <>{renderTurn()}</>;
}, conversationTurnRowPropsAreEqual);


type ConversationUserInlineEditorProps = {
  lang: "zh" | "en";
  value: string;
  onValueChange: (value: string) => void;
  onSubmit: () => void;
  onCancel: () => void;
  disabled: boolean;
  pending: boolean;
  submitLabel: string;
  cancelLabel: string;
  ariaLabel: string;
  error: string;
  attachments: ConversationAttachment[];
  references: SessionReferenceAttachment[];
  inputRef: React.RefObject<HTMLTextAreaElement | null>;
};

function inlineEditorAttachmentLabel(attachment: ConversationAttachment): string {
  return String(attachment.filename || attachment.artifactId || "").trim();
}

function inlineEditorReferenceLabel(reference: SessionReferenceAttachment): string {
  return String(
    reference.title
    || reference.filename
    || (reference.quote || "").trim().slice(0, 80)
    || reference.kind
    || "",
  ).trim();
}

/**
 * ZCode-style inline edit (packages/ui v4 ConversationRowView): the edited user
 * row swaps its content body for this editor in place. Text lives in the shared
 * composer draft so submit/cancel ride the existing edit-resubmit pipeline;
 * original attachments/references render as read-only chips (the edit-resubmit
 * pipeline carries the original attachment artifacts over server-side).
 */
function ConversationUserInlineEditor({
  lang,
  value,
  onValueChange,
  onSubmit,
  onCancel,
  disabled,
  pending,
  submitLabel,
  cancelLabel,
  ariaLabel,
  error,
  attachments,
  references,
  inputRef,
}: ConversationUserInlineEditorProps) {
  // Auto-height within the max-height clamp: grow with the draft, scroll
  // internally once the cap is hit. Re-runs per value change.
  useLayoutEffect(() => {
    const el = inputRef.current;
    if (!el) {
      return;
    }
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [inputRef, value]);
  const canSubmit = !disabled && !pending && Boolean(value.trim());
  return (
    <div
      className={styles.turnInlineEditor}
      data-conversation-inline-edit="1"
    >
      {attachments.length ? (
        <div
          className={styles.turnInlineEditorChipRow}
          aria-label={lang === "zh" ? "原消息附件（保留）" : "Original attachments (kept)"}
          data-inline-edit-attachments={String(attachments.length)}
        >
          {attachments.map((attachment, index) => {
            const label = inlineEditorAttachmentLabel(attachment);
            const thumbUrl = attachment.imageUrl || attachment.url;
            const isImage = thumbUrl
              && (String(attachment.contentType || "").startsWith("image/") || attachment.kind === "user_image");
            return (
              <span
                key={`${attachment.artifactId}-${index}`}
                className={styles.turnInlineEditorChip}
                title={label}
              >
                {isImage ? (
                  <img className={styles.turnInlineEditorChipThumb} src={thumbUrl} alt="" />
                ) : (
                  <FileText className={styles.turnInlineEditorChipIcon} aria-hidden="true" />
                )}
                <span className={styles.turnInlineEditorChipName}>{label}</span>
              </span>
            );
          })}
        </div>
      ) : null}
      {references.length ? (
        <div
          className={styles.turnInlineEditorChipRow}
          aria-label={lang === "zh" ? "原消息引用（保留）" : "Original references (kept)"}
          data-inline-edit-references={String(references.length)}
        >
          {references.map((reference, index) => {
            const label = inlineEditorReferenceLabel(reference);
            return (
              <span
                key={`${reference.referenceId || reference.title || ""}-${index}`}
                className={styles.turnInlineEditorChip}
                title={label}
              >
                <MessageSquareText className={styles.turnInlineEditorChipIcon} aria-hidden="true" />
                <span className={styles.turnInlineEditorChipName}>{label}</span>
              </span>
            );
          })}
        </div>
      ) : null}
      <VNativeTextarea
        ref={inputRef}
        className={styles.turnInlineEditorInput}
        value={value}
        disabled={disabled || pending}
        aria-label={ariaLabel}
        data-conversation-inline-edit-input="1"
        onChange={(event) => onValueChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Escape" && !event.nativeEvent.isComposing) {
            event.preventDefault();
            onCancel();
            return;
          }
          if (shouldSubmitComposerOnKeydown({
            key: event.key,
            shiftKey: event.shiftKey,
            ctrlKey: event.ctrlKey,
            metaKey: event.metaKey,
            altKey: event.altKey,
            isComposing: event.nativeEvent.isComposing,
          })) {
            event.preventDefault();
            if (canSubmit) {
              onSubmit();
            }
          }
        }}
      />
      {error ? <p className={styles.composerError} role="alert">{error}</p> : null}
      <div className={styles.turnInlineEditorActions}>
        <VButton
          type="button"
          onClick={onCancel}
          isDisabled={pending}
        >
          {cancelLabel}
        </VButton>
        <VButton
          type="button"
          className={styles.composerEditSubmitButton}
          onClick={onSubmit}
          isDisabled={!canSubmit}
          icon={pending
            ? <LoaderCircle className={styles.statusSpinner} size={14} aria-hidden="true" />
            : <RefreshCw size={14} aria-hidden="true" />}
        >
          {submitLabel}
        </VButton>
      </div>
    </div>
  );
}


export type ConversationTimelineRowPlan = {
  index: number;
  virtualStartPx: number | null;
};

type CurationFeedback = {
  messageId: string;
  action: SessionMessageCurationAction;
  message: string;
} | null;

export type ConversationTimelineRowsDeps = {
  measureTimelineVirtualRow: (node: HTMLDivElement | null) => void;
  activeTimelineMessages: ConversationMessage[];
  activeTimelineRowIdentities: AgentMessageTimelineRowIdentity[];
  agentMessagesByMessageId: Map<string, AgentMessage>;
  agentRenderStatesByMessageId: Map<string, AgentMessageRenderState>;
  agentOperationGroupsByMessageId: Map<string, AgentMessageOperationGroups>;
  agentCodexSurfacesByMessageId: Map<string, CodexTranscriptSurface>;
  defaultExpandedResponseIds: Set<string>;
  imageArtifactUrlsBeforeMessage: Map<string, Set<string>>;
  timelineModelSwitchBoundaries: ReadonlyMap<string, ConversationModelSwitchBoundary>;
  messageCurationMap: Map<string, MessageCurationDecision>;
  sectionExpansion: Record<string, Record<string, boolean>>;
  computerUseSessionResults: Record<string, ComputerUseResult>;
  computerUseSessionPending: Record<string, "confirm" | "cancel" | undefined>;
  companionTypingMessage: Extract<ConversationMessage, { role: "assistant" }> | undefined;
  latestUserMessageId: string;
  editingMessageId?: string;
  editUserMessageLabel?: string;
  editUserMessageDisabled?: boolean;
  composerPlaceholder: string;
  answerOnlyProcessMode: boolean;
  showMentalSnapshots: boolean;
  companionMode: boolean;
  lang: "zh" | "en";
  t: (key: TranslationKey) => string;
  phase: string;
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
  resolveTurnAvatar?: ConversationTurnRowProps["resolveTurnAvatar"];
  onEditUserMessage?: (message: ConversationMessage) => void;
  onRegenerateAssistantMessage?: (message: ConversationMessage) => void;
  onSwitchMessageVersion?: (message: ConversationMessage, targetNodeId: string) => void;
  branchVersionSwitchDisabled?: boolean;
  regenerableAssistantMessageId?: string;
  regenerateDisabled?: boolean;
  regeneratePending?: boolean;
  onForkSessionFromNode?: (
    message: ConversationMessage,
    scope: ConversationForkScope,
  ) => Promise<void> | void;
  onOpenComposerContextDetail?: () => void;
  onCancelComposerMode?: () => void;
  composerValue: string;
  onComposerChange: (value: string) => void;
  composerDisabled: boolean;
  composerError?: string;
  submitLabel?: string;
  cancelComposerModeLabel?: string;
  inlineEditInputRef: RefObject<HTMLTextAreaElement | null>;
  copiedAnswerMessageId: string;
  curationFeedback: CurationFeedback;
  openForkDialog: (message: ConversationMessage) => void;
  formatTimestamp: (timestamp: string) => string;
  compactPreview: (value: string, maxLength?: number) => string;
  conversationModelLabel: (modelId: string) => string;
  resolvedSafeGuidanceLabel: string;
  getCachedResponseSegments: (content: string) => ResponseSegment[];
  getExpansionState: (messageId: string, section: string, defaultExpanded: boolean) => boolean;
  toggleSection: (messageId: string, section: string, defaultExpanded: boolean) => void;
  handleCopyAnswer: (messageId: string, text: string) => void;
  handleCurateMessage: (messageId: string, action: SessionMessageCurationAction) => void;
  handleSendAndFollowLatest: () => void;
  openImagePreview: (image: ConversationImagePreviewRequest) => void;
  renderTimelineSpecialRow: ReturnType<typeof createConversationSpecialRows>["renderTimelineSpecialRow"];
  renderAgentMessageTimeline: ReturnType<typeof createConversationTimelineItems>["renderAgentMessageTimeline"];
  renderOperationGroup: ReturnType<typeof createConversationOperationGroups>["renderOperationGroup"];
  renderFeedbackTimelineGroup: ReturnType<typeof createConversationOperationGroups>["renderFeedbackTimelineGroup"];
  renderFeedbackTimelineDetails: ReturnType<typeof createConversationReActRows>["renderFeedbackTimelineDetails"];
  renderAgentMentalPanel: ReturnType<typeof createConversationAuxiliaryPanels>["renderAgentMentalPanel"];
  renderResponseText: ReturnType<typeof createConversationResponseBlocks>["renderResponseText"];
  renderUserContentWithSlashEcho: ReturnType<typeof createConversationResponseBlocks>["renderUserContentWithSlashEcho"];
  renderCodexTranscriptCells: ReturnType<typeof createConversationCodexSurface>["renderCodexTranscriptCells"];
};

/**
 * Virtual timeline row host: the measured history row, the live-tail row, and
 * the turn body (special rows, dividers, agent turn, inline edit). Extracted
 * from ConversationView with identical output.
 */
export function createConversationTimelineRows({
  measureTimelineVirtualRow,
  activeTimelineMessages,
  activeTimelineRowIdentities,
  agentMessagesByMessageId,
  agentRenderStatesByMessageId,
  agentOperationGroupsByMessageId,
  agentCodexSurfacesByMessageId,
  defaultExpandedResponseIds,
  imageArtifactUrlsBeforeMessage,
  timelineModelSwitchBoundaries,
  messageCurationMap,
  sectionExpansion,
  computerUseSessionResults,
  computerUseSessionPending,
  companionTypingMessage,
  latestUserMessageId,
  editingMessageId,
  editUserMessageLabel,
  editUserMessageDisabled,
  composerPlaceholder,
  answerOnlyProcessMode,
  showMentalSnapshots,
  companionMode,
  lang,
  t,
  phase,
  assistantLabel,
  assistantAvatarImageUrl,
  assistantAvatarFallback,
  userLabel,
  userAvatarLabel,
  userAvatarImageUrl,
  operationLabels,
  resolveTurnAvatar,
  onEditUserMessage,
  onRegenerateAssistantMessage,
  onSwitchMessageVersion,
  branchVersionSwitchDisabled,
  regenerableAssistantMessageId,
  regenerateDisabled,
  regeneratePending,
  onForkSessionFromNode,
  onOpenComposerContextDetail,
  onCancelComposerMode,
  composerValue,
  onComposerChange,
  composerDisabled,
  composerError,
  submitLabel,
  cancelComposerModeLabel,
  inlineEditInputRef,
  copiedAnswerMessageId,
  curationFeedback,
  openForkDialog,
  formatTimestamp,
  compactPreview,
  conversationModelLabel,
  resolvedSafeGuidanceLabel,
  getCachedResponseSegments,
  getExpansionState,
  toggleSection,
  handleCopyAnswer,
  handleCurateMessage,
  handleSendAndFollowLatest,
  openImagePreview,
  renderTimelineSpecialRow,
  renderAgentMessageTimeline,
  renderOperationGroup,
  renderFeedbackTimelineGroup,
  renderFeedbackTimelineDetails,
  renderAgentMentalPanel,
  renderResponseText,
  renderUserContentWithSlashEcho,
  renderCodexTranscriptCells,
}: ConversationTimelineRowsDeps) {
  function shouldRenderCompactActiveTurnPlaceholder(
    message: ConversationMessage,
    options: {
      showResponseBlock: boolean;
      hasFeedbackTimeline: boolean;
      hasActiveProcess: boolean;
      turnErrorMessage: boolean;
      hasCodexSurface?: boolean;
    },
  ) {
    return resolveShouldRenderCompactActiveTurnPlaceholder({
      role: message.role,
      streaming: assistantTurnIsStreaming(message),
      inFlight: assistantTurnIsInFlight(message),
      showResponseBlock: options.showResponseBlock,
      hasFeedbackTimeline: options.hasFeedbackTimeline,
      hasActiveProcess: options.hasActiveProcess,
      turnErrorMessage: options.turnErrorMessage,
      hasCodexSurface: options.hasCodexSurface,
    });
  }

  function shouldExpandToolGroupByDefault(message: ConversationMessage, operations: AgentMessageOperation[]) {
    return assistantTurnIsStreaming(message)
      || operations.some((operation) => operation.kind === "tool" && (operation.rawLabel ?? operation.label) === COMPUTER_USE_TOOL_NAME);
  }

  function shouldShowAgentResponseBlock(
    message: ConversationMessage,
    sectionState: AgentMessageSectionState,
    hasFeedbackTimeline: boolean,
  ) {
    return resolveShouldShowAgentResponseBlock({
      hasResponseBlock: sectionState.hasResponseBlock,
      answerText: sectionState.answerText,
      hasFeedbackTimeline,
      streaming: assistantTurnIsStreaming(message),
      segments: getCachedResponseSegments(sectionState.answerText),
    });
  }

  function renderTimelineRow(rowPlan: { index: number; virtualStartPx: number | null }) {
              const index = rowPlan.index;
              const message = activeTimelineMessages[index];
              if (!message) {
                return null;
              }
              const rowIdentity = activeTimelineRowIdentities[index];
              const rowKey = rowIdentity?.rowKey ?? message.id;
              return (
              <div
                key={rowKey}
                ref={rowPlan.virtualStartPx === null ? undefined : measureTimelineVirtualRow}
                {...(rowPlan.virtualStartPx === null
                  ? {}
                  : {
                    "data-index": index,
                    style: {
                      position: "absolute",
                      top: 0,
                      left: 0,
                      width: "100%",
                      transform: `translateY(${rowPlan.virtualStartPx}px)`,
                    },
                  })}
                className={styles.timelineVirtualRow}
                data-conversation-virtual-row={rowKey}
                // Kept in sync with CONVERSATION_SELECTION_MESSAGE_ATTRIBUTE
                // (selection-quote reference wiring is covered by its tests).
                data-conversation-message-id={message.id}
              >
              <ConversationTurnRow
                message={message}
                previousMessage={activeTimelineMessages[index - 1]}
                agentMessage={agentMessagesByMessageId.get(message.id)}
                agentRenderState={agentRenderStatesByMessageId.get(message.id)}
                previousAgentRenderState={
                  activeTimelineMessages[index - 1]
                    ? agentRenderStatesByMessageId.get(activeTimelineMessages[index - 1].id)
                    : undefined
                }
                codexTranscriptCells={agentCodexSurfacesByMessageId.get(message.id)?.cells}
                rowIdentity={rowIdentity}
                defaultResponseExpanded={defaultExpandedResponseIds.has(message.id)}
                latestUserMessageId={latestUserMessageId}
                editingMessageId={editingMessageId}
                editUserMessageLabel={editUserMessageLabel}
                editUserMessageDisabled={editUserMessageDisabled}
                composerPlaceholder={composerPlaceholder}
                answerOnlyProcessMode={answerOnlyProcessMode}
                showMentalSnapshots={showMentalSnapshots}
                lang={lang}
                assistantLabel={assistantLabel}
                assistantAvatarImageUrl={assistantAvatarImageUrl}
                assistantAvatarFallback={assistantAvatarFallback}
                userLabel={userLabel}
                userAvatarLabel={userAvatarLabel}
                userAvatarImageUrl={userAvatarImageUrl}
                operationLabels={operationLabels}
                resolveTurnAvatar={resolveTurnAvatar}
                onEditUserMessage={onEditUserMessage}
                onRegenerateAssistantMessage={onRegenerateAssistantMessage}
                onSwitchMessageVersion={onSwitchMessageVersion}
                branchVersionSwitchDisabled={branchVersionSwitchDisabled}
                regenerableAssistantMessageId={regenerableAssistantMessageId}
                regenerateDisabled={regenerateDisabled}
                regeneratePending={regeneratePending}
                sectionExpansionForMessage={sectionExpansion[message.id] ?? EMPTY_SECTION_EXPANSION}
                computerUseStateForMessage={buildComputerUseStateForMessage(
                  message,
                  computerUseSessionResults,
                  computerUseSessionPending,
                )}
                imageArtifactUrlsBeforeMessage={imageArtifactUrlsBeforeMessage.get(message.id)}
                renderTurn={() => {
            const rowIdentity = activeTimelineRowIdentities[index];
            // The global companion typing affordance is the entire in-flight
            // shell; do not leave an empty speaker/avatar row beside it.
            if (companionTypingMessage?.id === message.id) {
              return null;
            }
            const specialRow = renderTimelineSpecialRow(message, rowIdentity?.rowKey ?? message.id);
            if (specialRow) {
              return specialRow;
            }
            const agentMessage = agentMessagesByMessageId.get(message.id);
            if (!agentMessage) {
              return null;
            }
            const baseOperationGroups = agentOperationGroupsByMessageId.get(agentMessage.id)
              ?? buildAgentMessageOperationGroups(agentMessage, operationLabels);
            const operationGroups = operationGroupsWithFeedbackStatusPlaceholder(baseOperationGroups, message, lang);
            const agentRenderState = agentRenderStatesByMessageId.get(message.id) ?? buildAgentMessageRenderState(agentMessage);
            const agentSections = agentRenderState.sectionState;
            const processSections = agentRenderState.processSections;
            const responseText = agentSections.answerText;
            const companionVisibleSpeech = companionMode
              ? companionUnrepeatedSpeech(
                previousCompanionSpokenText(activeTimelineMessages, index),
                companionMessageSpokenText(message),
              )
              : "";
            const noFinalAnswerStatusText = isNoFinalAnswerStatusContent(responseText)
              ? responseText.trim()
              : "";
            const userContentText = agentSections.userText;
            const hasActiveProcess = operationGroups.timeline.some((operation) => isRunningOperationStatus(operation.status));
            // Defect ⑦b: the active-turn shell gate must not count decorative
            // streaming operations (thought/mental/status rows) as active
            // process — a mid-stream reasoning flush would otherwise retire the
            // shell and hide the responding stage. Only running tools suppress.
            const hasRunningToolOperation = operationGroups.tools.some((operation) => isRunningOperationStatus(operation.status));
            const hasFeedbackTimeline = agentSections.hasFeedbackTimeline;
            const showResponseBlock = shouldShowAgentResponseBlock(message, agentSections, hasFeedbackTimeline);
            const turnErrorMessage = isTurnErrorMessage(message);
            const imageArtifact = imageArtifactForMessage(message);
            const agentInboxMessage = isAgentInboxMessage(message);
            const groupTranscriptMessage = isGroupRoomTranscriptMessage(message);
            const previousMessage = activeTimelineMessages[index - 1];
            const previousAgentRenderState = previousMessage
              ? agentRenderStatesByMessageId.get(previousMessage.id)
              : undefined;
            const compactTurnHeader = shouldCompactConversationTurnHeader(
              previousMessage,
              message,
              previousAgentRenderState?.sectionState,
              agentSections,
            );
            const codexTranscriptSurface = agentCodexSurfacesByMessageId.get(agentMessage.id);
            const codexTranscriptCells = codexTranscriptSurface?.cells ?? [];
            // Phase C: display plan picks package_cells vs legacy; single track for final answer.
            const displayPlanSeed = resolveAssistantDisplayPlan({
              message,
              surface: codexTranscriptSurface,
            });
            const shouldRenderLegacyTurnError = Boolean(
              turnErrorMessage && !displayPlanSeed.suppressProjectedError,
            );
            // Failure-turn presentation: human-readable errorType chip and a
            // budget-directed recovery action instead of raw codes.
            const turnErrorTypeLabelKey = shouldRenderLegacyTurnError
              ? resolveTurnErrorTypeLabelKey(resolveConversationTurnErrorType(message))
              : "";
            const turnErrorRecoveryAction = shouldRenderLegacyTurnError
              ? resolveConversationTurnErrorRecoveryAction(message)
              : "";
            const timelineOptions = {
              lang,
              // The assistant body always comes from the canonical cell surface.
              // Do not manufacture a second answer row in the process timeline.
              includeAssistantText: false,
            };
            const agentMessageTimelineItems = buildAgentMessageTimelineItems(
              agentMessage,
              operationGroups.timeline,
              timelineOptions,
            );
            const hasAgentMessageTimeline =
              message.role === "assistant"
              && hasFeedbackTimeline
              && !turnErrorMessage
              && !agentInboxMessage
              && !groupTranscriptMessage
              && agentMessageTimelineItems.length > 0;
            const displayPlan = resolveAssistantDisplayPlan({
              message,
              surface: codexTranscriptSurface,
            });
            const timelineRendersAssistantText = false;
            const showUserContent = agentSections.hasUserContent;
            const steerGuidanceMessage = isSteerGuidanceMessage(message);
            const userAuthoredMessage = message.role === "user" && !agentInboxMessage;
            const isStreamingStatusPlaceholder = assistantTurnIsStreaming(message)
              && showResponseBlock
              && answerOnlyProcessMode
              && isStreamingStatusPlaceholderContent(responseText);
            const isResponseStreaming = assistantTurnIsStreaming(message) && showResponseBlock && !isStreamingStatusPlaceholder;
            const copyableAnswerText = message.role === "assistant"
              && !turnErrorMessage
              && !assistantTurnIsStreaming(message)
              ? (companionMode ? companionVisibleSpeech : responseText.trim())
              : "";
            // Codex parity: settled turns carry a quiet measured token-usage
            // label near the turn meta; streaming turns and surfaces without
            // wire facts render nothing.
            const turnUsageLabel = message.role === "assistant"
              && !assistantTurnIsStreaming(message)
              && !companionMode
              && !agentInboxMessage
              && !groupTranscriptMessage
              ? resolveConversationTurnUsageLabel(message.usageStats, lang)
              : null;
            // SFT curation actions share the copy affordance's gate and stay
            // out of companion/inbox/group surfaces by contract.
            const messageCurationGate = Boolean(copyableAnswerText)
              && !companionMode
              && !agentInboxMessage
              && !groupTranscriptMessage;
            const messageCurationDecision = messageCurationGate
              ? resolveMessageCurationState(messageCurationMap, message.id)
              : null;
            const canRegenerateAnswer = message.role === "assistant"
              && !turnErrorMessage
              && !assistantTurnIsStreaming(message)
              && Boolean(onRegenerateAssistantMessage)
              // Any settled answer on a branch can regenerate; messages without
              // a journal node id keep the legacy latest-only fallback.
              && (Boolean(message.nodeId) || message.id === regenerableAssistantMessageId);
            // A settled failed turn offers in-place recovery: retry reruns the
            // turn's original user message through the same branch-aware
            // regenerate pipeline as the regenerate action. Without a journal
            // node id only the legacy latest-turn fallback remains, so the
            // entry is hidden for older untargetable failures.
            const canRetryFailedTurnMessage = message.role === "assistant"
              && turnErrorMessage
              && !assistantTurnIsStreaming(message)
              && !agentInboxMessage
              && !groupTranscriptMessage
              && Boolean(onRegenerateAssistantMessage)
              && (Boolean(message.nodeId) || message.id === regenerableAssistantMessageId);
            const branchInfo = message.branch;
            const siblingNodeIds = Array.isArray(branchInfo?.siblingNodeIds)
              ? branchInfo.siblingNodeIds.filter((value): value is string => Boolean(value))
              : [];
            const siblingCount = Math.max(
              Number(branchInfo?.siblingCount ?? 0) || 0,
              siblingNodeIds.length,
            );
            const siblingIndex = Number(branchInfo?.siblingIndex ?? 0) || 0;
            const currentNodeId = String(message.nodeId || "").trim();
            // Fork exit: any settled journal node (user or assistant) can seed a
            // new session; companion/private/group surfaces stay out of scope.
            const canForkSessionFromMessage = Boolean(onForkSessionFromNode)
              && !companionMode
              && !agentInboxMessage
              && !groupTranscriptMessage
              && !assistantTurnIsStreaming(message)
              && Boolean(currentNodeId);
            const showVersionSwitcher = Boolean(onSwitchMessageVersion)
              && siblingCount > 1
              && siblingNodeIds.length > 1
              && siblingIndex >= 1
              && siblingIndex <= siblingNodeIds.length
              && Boolean(currentNodeId)
              && siblingNodeIds.includes(currentNodeId);
            const versionSwitchDisabled = Boolean(branchVersionSwitchDisabled);
            const previousSiblingNodeId = siblingIndex > 1 ? siblingNodeIds[siblingIndex - 2] : "";
            const nextSiblingNodeId = siblingIndex < siblingNodeIds.length
              ? siblingNodeIds[siblingIndex]
              : "";
            const showResponseSpinner = isResponseStreaming && !hasActiveProcess;
            const defaultResponseExpanded = assistantTurnIsStreaming(message) || defaultExpandedResponseIds.has(message.id);
            const responseExpanded = getExpansionState(message.id, "response", defaultResponseExpanded);
            const responseSegments = showResponseBlock && !isStreamingStatusPlaceholder && !isResponseStreaming
              ? getCachedResponseSegments(responseText)
              : [];
            const codexTranscript = (
              displayPlan.shouldRenderCodexSurface
              && !agentInboxMessage
              && !groupTranscriptMessage
            )
              ? renderCodexTranscriptCells(
                message,
                codexTranscriptCells,
                rowIdentity,
                companionMode,
                companionVisibleSpeech,
              )
              : null;
            const codexTranscriptNode = codexTranscript?.node ?? null;
            // Todo checklist card: client-derived from the latest journaled
            // todo_write call in this turn (no extra SSE event). Companion and
            // private-message surfaces stay minimal by contract.
            const todoChecklistSnapshot = message.role === "assistant"
              && !companionMode
              && !agentInboxMessage
              && !groupTranscriptMessage
              ? deriveLatestTodoChecklist(message.turnItems)
              : undefined;
            const todoChecklistNode = todoChecklistSnapshot ? (
              <ConversationTodoChecklist
                snapshot={todoChecklistSnapshot}
                lang={lang}
                turnSettled={hasTerminalCanonicalTurnOutcome(message)}
              />
            ) : null;
            // Only force the answer body open while tokens are still streaming.
            // Tying this to defaultResponseExpanded made the last few answers
            // impossible to collapse (toggle flipped aria state but body stayed).
            const shouldForceResponseBodyVisible = isResponseStreaming;
            const isEditingMessage = userAuthoredMessage && message.id === editingMessageId;
            const editingUserMessage = isEditingMessage && message.role === "user" ? message : null;
            const agentInboxExpanded = getExpansionState(message.id, "agentInbox", false);
            const agentInboxPreview = agentInboxMessage ? compactPreview(agentInboxSummary(message), 140) : "";
            const researchOrgChips = researchOrgMessageChips(message);
            const contextNode = !companionMode && (agentRenderState.contextSections?.length ?? 0) > 0 ? (
              <React.Suspense fallback={null}>
                <AgentContextSectionsView sections={agentRenderState.contextSections} lang={lang} />
              </React.Suspense>
            ) : null;
            const turnClassName = [
              // Hover-reveal anchor: per-message action buttons fade in only
              // while the pointer (or keyboard focus) is on this row.
              "group",
              groupTranscriptMessage
                ? styles.groupTranscriptTurn
                : message.role === "assistant"
                  ? styles.assistantTurn
                  : agentInboxMessage
                  ? styles.agentInboxTurn
                  : styles.userTurn,
              turnErrorMessage ? styles.turnErrorTurn : "",
              compactTurnHeader ? styles.assistantTurnContinuation : "",
              isEditingMessage ? styles.turnEditing : "",
            ].filter(Boolean).join(" ");
            const speakerLabel = groupTranscriptMessage
              ? groupRoomTranscriptLabel(message)
              : message.role === "assistant"
                ? assistantLabel
                : agentInboxMessage
                  ? agentInboxSourceLabel(message)
                  : userLabel;
            const editDisabled = Boolean(editUserMessageDisabled);
            const processTone = operationCollectionTone(operationGroups.timeline);
            const processDefaultExpanded = processTone === "running";
            const renderAgentProcessDetails = (defaultExpandedOverride?: boolean) => (
              <>
                {renderOperationGroup(
                  message.id,
                  "thought",
                  operationGroups.thoughts,
                  defaultExpandedOverride ?? assistantTurnIsStreaming(message),
                )}
                {renderAgentMentalPanel(
                  message.id,
                  latestAgentMentalPart(processSections),
                  defaultExpandedOverride,
                  assistantTurnIsStreaming(message) && operationGroups.tools.length === 0 && !agentSections.hasResponseBlock,
                )}
                {renderOperationGroup(
                  message.id,
                  "tools",
                  operationGroups.tools,
                  defaultExpandedOverride ?? shouldExpandToolGroupByDefault(message, operationGroups.tools),
                )}
              </>
            );
            const renderProcessDetails = () => {
              if (hasAgentMessageTimeline) {
                return renderAgentMessageTimeline(message, agentMessageTimelineItems, rowIdentity, agentRenderState.processSectionIds);
              }
              if (hasFeedbackTimeline) {
                return renderFeedbackTimelineDetails(message.id, operationGroups.timeline);
              }
              return renderAgentProcessDetails(true);
            };
            // One assistant turn has one display source: its local turnItems cell surface.
            const responseSectionNode = null;
            // The fallback process rail is only useful while a future producer has
            // not emitted a canonical cell yet. It never receives assistant text.
            const processNode = companionMode || displayPlan.suppressProjectedProcess
              ? null
              : displayPlan.renderMode === "turn_items"
                ? null
                : hasAgentMessageTimeline
                  ? renderAgentMessageTimeline(message, agentMessageTimelineItems, rowIdentity, agentRenderState.processSectionIds)
                  : hasFeedbackTimeline
                    ? renderFeedbackTimelineGroup(
                      message.id,
                      operationGroups.timeline,
                      false,
                      agentRenderState.processSectionIds,
                    )
                    : null;
            const showCompactActiveTurnPlaceholder = shouldRenderCompactActiveTurnPlaceholder(message, {
              showResponseBlock,
              hasFeedbackTimeline,
              hasActiveProcess: hasRunningToolOperation,
              turnErrorMessage,
              // The visible work disclosure owns routine progress; its advisories remain below.
              hasCodexSurface: Boolean(displayPlan.shouldRenderCodexSurface),
            });
            // Prefer compact active-turn note over projected turnStatus for in-flight shells.
            const turnStatusNode = !companionMode && !showCompactActiveTurnPlaceholder
              && !displayPlan.suppressProjectedTurnStatus
              && noFinalAnswerStatusText ? (
              <div className={styles.turnStatusNote} role="status" aria-live="polite">
                <span className={styles.turnStatusLabel}>{lang === "zh" ? "状态" : "Status"}</span>
                <span className={styles.turnStatusText}>{noFinalAnswerStatusText}</span>
              </div>
            ) : null;
            const hasVisibleWorkDisclosure = Boolean(codexTranscript?.hasWorkDisclosure);
            const showWorkAdvisories = hasVisibleWorkDisclosure && assistantTurnIsInFlight(message) && !turnErrorMessage;
            const compactActiveTurnPlaceholderNode = !companionMode && (showCompactActiveTurnPlaceholder || showWorkAdvisories) ? (
              <ConversationActiveTurnStatusNote
                message={message}
                lang={lang}
                phase={phase}
                advisoriesOnly={hasVisibleWorkDisclosure}
                statusLabel={lang === "zh" ? "状态" : "Status"}
              />
            ) : null;
            // Turn-envelope dividers above the row: model switches ride the
            // turn-opening user row; the fork-provenance marker is a dormant
            // hook until the backend projects per-message fork metadata.
            const modelSwitchBoundary = message.role === "user"
              ? timelineModelSwitchBoundaries.get(message.id)
              : undefined;
            const modelSwitchDividerNode = modelSwitchBoundary ? (
              <div
                className={styles.turnDividerRow}
                data-conversation-model-switch-divider={modelSwitchBoundary.kind}
              >
                <span className={styles.turnDividerRule} aria-hidden="true" />
                <span className={styles.turnDividerIcon} aria-hidden="true">
                  {modelSwitchBoundary.kind === "initial"
                    ? <Sparkles size={13} />
                    : <ArrowLeftRight size={13} />}
                </span>
                <span className={styles.turnDividerLabel}>
                  {modelSwitchBoundary.kind === "initial"
                    ? replaceDividerPlaceholder(
                      t("modelSwitchInitialLabel"),
                      "model",
                      conversationModelLabel(modelSwitchBoundary.toModelId),
                    )
                    : replaceDividerPlaceholder(
                      replaceDividerPlaceholder(
                        t("modelSwitchChangeLabel"),
                        "from",
                        conversationModelLabel(modelSwitchBoundary.fromModelId),
                      ),
                      "to",
                      conversationModelLabel(modelSwitchBoundary.toModelId),
                    )}
                </span>
                <span className={styles.turnDividerRule} aria-hidden="true" />
              </div>
            ) : null;
            const forkMarkerDividerNode = isForkedSessionMarkerMessage(message) ? (
              <div
                className={styles.turnDividerRow}
                data-conversation-fork-marker-divider="true"
              >
                <span className={styles.turnDividerRule} aria-hidden="true" />
                <span className={styles.turnDividerIcon} aria-hidden="true">
                  <GitFork size={13} />
                </span>
                <span className={styles.turnDividerLabel}>{t("forkedSessionMarkerLabel")}</span>
                <span className={styles.turnDividerRule} aria-hidden="true" />
              </div>
            ) : null;
            return (
              <>
                {modelSwitchDividerNode}
                {forkMarkerDividerNode}
                <AgentMessageTurnView
                  key={rowIdentity.rowKey}
                rowKey={rowIdentity.rowKey}
                messageKey={rowIdentity.messageKey}
                agentMessageId={agentMessage.id}
                sectionCount={agentSections.sectionCount}
                sectionKinds={agentRenderState.sectionKinds}
                className={turnClassName}
                compactHeader={false}
                avatar={
                  <ConversationTurnAvatarContent
                    content={resolveMessageTurnAvatar(message, {
                      resolveTurnAvatar,
                      assistantAvatarImageUrl,
                      assistantAvatarFallback,
                      assistantLabel,
                      userAvatarImageUrl,
                      userAvatarLabel,
                      agentInboxMessage,
                      groupTranscriptMessage,
                    })}
                  />
                }
                speakerLabel={speakerLabel}
                identityAccessory={
                  isEditingMessage
                    ? <span className={styles.turnEditBadge}>{t("editMessage")}</span>
                    : steerGuidanceMessage
                      ? (
                        <VChip data-conversation-guidance-status="received">
                          {resolvedSafeGuidanceLabel} · {lang === "zh" ? "已接收" : "Received"}
                        </VChip>
                      )
                      : null
                }
                metaActions={
                  <>
                    {turnUsageLabel ? (
                      <span
                        className={styles.turnUsageLabel}
                        title={turnUsageLabel.titleLines.join("\n")}
                        data-conversation-turn-usage="1"
                      >
                        {turnUsageLabel.label}
                      </span>
                    ) : null}
                    {message.timestamp ? <span>{formatTimestamp(message.timestamp)}</span> : null}
                    <span
                      className={isEditingMessage ? styles.turnHoverActionsVisible : styles.turnHoverActions}
                      data-conversation-hover-actions="1"
                    >
                    {showVersionSwitcher ? (
                      <VActionGroup
                        ariaLabel={t("branchVersionLabel")}
                        className={styles.turnVersionSwitcher}
                      >
                        <VButton
                          type="button"
                          className={styles.turnIconButton}
                          onClick={() => onSwitchMessageVersion?.(message, previousSiblingNodeId)}
                          isDisabled={versionSwitchDisabled || !previousSiblingNodeId}
                          title={t("switchBranchVersionPrevious")}
                          aria-label={t("switchBranchVersionPrevious")}
                          isIconOnly
                          icon={<ChevronLeft size={14}/>} />
                        <span className={styles.turnVersionLabel} aria-live="polite">
                          {`${siblingIndex}/${siblingCount}`}
                        </span>
                        <VButton
                          type="button"
                          className={styles.turnIconButton}
                          onClick={() => onSwitchMessageVersion?.(message, nextSiblingNodeId)}
                          isDisabled={versionSwitchDisabled || !nextSiblingNodeId}
                          title={t("switchBranchVersionNext")}
                          aria-label={t("switchBranchVersionNext")}
                          isIconOnly
                          icon={<ChevronRight size={14}/>} />
                      </VActionGroup>
                    ) : null}
                    {copyableAnswerText ? (
                      <VButton
                        type="button"
                        className={styles.turnIconButton}
                        onClick={() => handleCopyAnswer(message.id, copyableAnswerText)}
                        title={t("copyAnswer")}
                        aria-label={t("copyAnswer")}
                        isIconOnly
                        icon={copiedAnswerMessageId === message.id ? <Check size={14}/> : <Copy size={14}/>} />
                    ) : null}
                    {messageCurationGate ? (
                      <>
                        <VButton
                          type="button"
                          className={
                            messageCurationDecision === "include"
                              ? `${styles.turnIconButton} ${styles.turnIconButtonActive}`
                              : styles.turnIconButton
                          }
                          aria-pressed={messageCurationDecision === "include"}
                          onClick={() => handleCurateMessage(message.id, "include")}
                          title={
                            curationFeedback?.messageId === message.id && curationFeedback.action === "include" && curationFeedback.message
                              ? curationFeedback.message
                              : t("addToDataset")
                          }
                          aria-label={t("addToDataset")}
                          isIconOnly
                          icon={<ListPlus size={14}/>} />
                        <VButton
                          type="button"
                          className={
                            messageCurationDecision === "exclude"
                              ? `${styles.turnIconButton} ${styles.turnIconButtonActive}`
                              : styles.turnIconButton
                          }
                          aria-pressed={messageCurationDecision === "exclude"}
                          onClick={() => handleCurateMessage(message.id, "exclude")}
                          title={
                            curationFeedback?.messageId === message.id && curationFeedback.action === "exclude" && curationFeedback.message
                              ? curationFeedback.message
                              : t("excludeFromDataset")
                          }
                          aria-label={t("excludeFromDataset")}
                          isIconOnly
                          icon={<CircleMinus size={14}/>} />
                      </>
                    ) : null}
                    {canForkSessionFromMessage ? (
                      <VButton
                        type="button"
                        className={styles.turnIconButton}
                        onClick={() => openForkDialog(message)}
                        isDisabled={versionSwitchDisabled}
                        title={t("forkSessionFromMessage")}
                        aria-label={t("forkSessionFromMessage")}
                        isIconOnly
                        icon={<GitFork size={14}/>} />
                    ) : null}
                    {canRegenerateAnswer ? (
                      <VButton
                        type="button"
                        className={styles.turnIconButton}
                        onClick={() => onRegenerateAssistantMessage?.(message)}
                        isDisabled={regenerateDisabled}
                        isPending={regeneratePending}
                        title={regeneratePending ? t("regeneratePending") : t("regenerateAnswer")}
                        aria-label={regeneratePending ? t("regeneratePending") : t("regenerateAnswer")}
                        isIconOnly
                        icon={<RefreshCw size={14}/>} />
                    ) : null}
                    {userAuthoredMessage && !steerGuidanceMessage && onEditUserMessage ? (
                      <VButton
                        type="button"
                        className={
                          isEditingMessage
                            ? `${styles.turnIconButton} ${styles.turnIconButtonActive}`
                            : styles.turnIconButton
                        }
                        onClick={() => onEditUserMessage(message)}
                        isDisabled={editDisabled}
                        aria-pressed={isEditingMessage}
                        title={editDisabled ? composerPlaceholder : editUserMessageLabel ?? t("editMessage")}
                        aria-label={editUserMessageLabel ?? t("editMessage")}
                        isIconOnly
                        icon={<Pencil size={14}/>} />
                    ) : null}
                    </span>
                  </>
                }
              >

                  <span
                    hidden
                    data-codex-transcript-cell-count={codexTranscriptCells.length}
                    data-codex-transcript-surface-mode={codexTranscriptSurface?.mode ?? "empty"}
                    data-codex-transcript-native-primary={displayPlan.nativePrimary ? "true" : "false"}
                    data-assistant-render-mode={displayPlan.renderMode}
                    data-assistant-has-turn-item-package={displayPlan.hasTurnItemPackage ? "true" : "false"}
                    data-codex-transcript-projection-gap-reason={codexTranscriptSurface?.projectionGap?.reason ?? ""}
                    data-codex-transcript-projection-gap-projected-cell-count={codexTranscriptSurface?.projectionGap?.projectedCellCount ?? 0}
                  />
                  {agentInboxMessage ? (
                    <section className={styles.agentInboxSection}>
                      {researchOrgChips.length > 0 ? (
                        <div className={styles.researchOrgChipRow} aria-label={lang === "zh" ? "科研组织消息标签" : "Research organization message labels"}>
                          {researchOrgChips.map((chip) => (
                            <span
                              key={chip.key}
                              className={`${styles.researchOrgChip} ${styles[`researchOrgChip_${chip.tone}`]}`}
                            >
                              {chip.label}
                            </span>
                          ))}
                        </div>
                      ) : null}
                      <VButton
                        type="button"
                        className={styles.agentInboxToggle}
                        aria-expanded={agentInboxExpanded}
                        onClick={() => toggleSection(message.id, "agentInbox", false)}
                        title={agentInboxExpanded ? (lang === "zh" ? "折叠私信内容" : "Collapse private message") : (lang === "zh" ? "展开私信内容" : "Expand private message")}
                        icon={agentInboxExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}><span>{lang === "zh" ? "私信内容" : "Private message"}</span>
                        {agentInboxPreview ? <span className={styles.agentInboxPreview}>{agentInboxPreview}</span> : null}</VButton>
                      {agentInboxExpanded ? (
                        <div className={styles.agentInboxMessageBody}>
                          {renderResponseText(assistantFinalAnswerText(message))}
                        </div>
                      ) : null}
                    </section>
                  ) : editingUserMessage ? (
                    <ConversationUserInlineEditor
                      lang={lang}
                      value={composerValue}
                      onValueChange={onComposerChange}
                      onSubmit={handleSendAndFollowLatest}
                      onCancel={() => onCancelComposerMode?.()}
                      disabled={composerDisabled}
                      pending={Boolean(editUserMessageDisabled)}
                      submitLabel={submitLabel?.trim() || t("saveAndRerunMessage")}
                      cancelLabel={cancelComposerModeLabel ?? t("cancelEditMessage")}
                      ariaLabel={editUserMessageLabel ?? t("editMessage")}
                      error={composerError ?? ""}
                      attachments={editingUserMessage.attachments ?? []}
                      references={editingUserMessage.references ?? []}
                      inputRef={inlineEditInputRef}
                    />
                  ) : showUserContent ? (
                    <AgentUserContentSectionView userContentSectionIds={agentRenderState.userContentSectionIds}>
                      {renderUserContentWithSlashEcho(userContentText, userAuthoredMessage)}
                    </AgentUserContentSectionView>
                  ) : null}
                  {groupTranscriptMessage ? (
                    <div className={styles.groupTranscriptBody}>
                      {renderConversationInlineMarkdown(assistantFinalAnswerText(message), groupTranscriptInlineClassNames)}
                    </div>
                  ) : null}
                  {contextNode}

                  {/*
                    Codex-aligned order: process / tools first, then final answer surface.
                    - renderCodexTranscriptCells already does processCells → finalCells inside.
                    - When tools only exist on feedback/timeline (alongside), processNode must
                      still precede codexTranscriptNode so the answer is not above the tools.
                  */}
                  {/* Checklist overview sits above the process trail: it is a
                      progress summary, not a second process row. */}
                  {todoChecklistNode}
                  {processNode}
                  {compactActiveTurnPlaceholderNode}
                  {codexTranscriptNode}
                  {turnStatusNode}
                  {shouldRenderLegacyTurnError ? (
                    <div className={styles.turnErrorNotice} role="status" aria-live="polite">
                      <div className={styles.turnErrorNoticeIcon} aria-hidden="true">
                        <TerminalSquare size={15} />
                      </div>
                      <div className={styles.turnErrorNoticeBody}>
                        <div className={styles.turnErrorNoticeMeta}>
                          <span>{lang === "zh" ? "运行提示" : "Runtime notice"}</span>
                          {turnErrorTypeLabelKey ? (
                            <span title={resolveConversationTurnErrorType(message)}>{t(turnErrorTypeLabelKey)}</span>
                          ) : null}
                        </div>
                        <div className={styles.turnErrorNoticeText}>{renderResponseText(assistantFinalAnswerText(message))}</div>
                        {buildConversationTurnErrorReasonRows(message, lang).length > 0 ? (
                          <details className={styles.turnErrorDiagnostics}>
                            <summary className={styles.turnErrorDiagnosticsSummary}>
                              {lang === "zh" ? "诊断详情" : "Diagnostics"}
                            </summary>
                            <dl className={styles.turnErrorReasonList}>
                              {buildConversationTurnErrorReasonRows(message, lang).map((row) => (
                                <div key={`${row.label}-${row.value}`} className={styles.turnErrorReasonRow}>
                                  <dt>{row.label}</dt>
                                  <dd>{row.value}</dd>
                                </div>
                              ))}
                            </dl>
                          </details>
                        ) : null}
                        {turnErrorRecoveryAction === "compress_context" && onOpenComposerContextDetail ? (
                          <div className={styles.turnErrorActions}>
                            <VButton
                              type="button"
                              contentLayout="plain"
                              className={styles.turnErrorRetryButton}
                              onClick={onOpenComposerContextDetail}
                              title={t("turnErrorActionCompressContextTitle")}
                              aria-label={t("turnErrorActionCompressContext")}
                            >
                              <Gauge size={12}/>
                              <span>{t("turnErrorActionCompressContext")}</span>
                            </VButton>
                          </div>
                        ) : null}
                        {canRetryFailedTurnMessage ? (
                          <div
                            className={styles.turnErrorActionsHover}
                            data-conversation-hover-actions="1"
                          >
                            <VButton
                              type="button"
                              contentLayout="plain"
                              className={styles.turnErrorRetryButton}
                              onClick={() => onRegenerateAssistantMessage?.(message)}
                              isDisabled={regenerateDisabled}
                              isPending={regeneratePending}
                              title={regeneratePending ? t("retryFailedTurnPending") : t("retryFailedTurn")}
                              aria-label={regeneratePending ? t("retryFailedTurnPending") : t("retryFailedTurn")}
                            >
                              <RefreshCw size={12}/>
                              <span>{t("retryFailedTurn")}</span>
                            </VButton>
                          </div>
                        ) : null}
                      </div>
                    </div>
                  ) : null}
                  {answerOnlyProcessMode ? responseSectionNode : null}
                  {imageArtifact ? (
                    <ConversationImageArtifactView
                      artifact={imageArtifact}
                      lang={lang}
                      onPreviewImage={openImagePreview}
                    />
                  ) : null}

                  {!answerOnlyProcessMode ? responseSectionNode : null}
              </AgentMessageTurnView>
              </>
            );
                }}
              />
              </div>
              );
  }

  return { renderTimelineRow };
}
