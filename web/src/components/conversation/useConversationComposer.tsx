import {
  ArrowUp,
  BookOpen,
  CirclePlus,
  Cpu,
  FileText,
  Gauge,
  ImagePlus,
  Link2,
  LoaderCircle,
  MessageSquareText,
  Quote,
  RefreshCw,
  Square,
  X,
} from "lucide-react";
import React, {
  DragEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from "react";

import type {
  ConversationMessage,
  SessionReferenceAttachment,
  SessionTurnError,
  SkillLibraryItem,
} from "../../api/types";
import type { Language, TranslationKey } from "../../i18n/dictionaryTypes";
import type { ComposerContextRingModel } from "../../routes/chat/composerContextModel";
import { AgentPermissionPresetControl } from "../vui/product/agent-management";
import { VButton, VNativeInput, VNativeTextarea } from "../vui";
import { ComposerContextRing } from "./ComposerContextRing";
import { ConversationFollowupQueueBar } from "./ConversationFollowupQueueBar";
import { ConversationInferenceControl } from "./ConversationInferenceControl";
import type { ConversationImagePreviewRequest } from "./ConversationImagePreviewDialog";
import { ConversationTurnModelControl } from "./ConversationTurnModelControl";
import { attachmentSizeLabel, isImageAttachment } from "./attachmentPresentation";
import type { ComposerQueueItem } from "./composerFollowupQueueModel";
import { resolveComposerQueuePrimaryKind } from "./composerFollowupQueueModel";
import {
  MAX_COMPOSER_STARTERS,
  resolveComposerPlaceholder,
  shouldAcceptComposerGhost,
  type ComposerStarter,
} from "./composerPromptSuggestionModel";
import {
  resolveComposerActionDisabled,
  resolveComposerActionLabels,
  resolveComposerActionMode,
  resolveComposerEditMode,
  resolveComposerEnterDelivery,
  resolveComposerGuidanceUi,
  resolveComposerPrimaryActionFlags,
  shouldStopComposerOnEscape,
} from "./conversationComposerActionModel";
import {
  extractComposerImageDropFiles,
  extractComposerSessionReferenceDrop,
  hasComposerImageDragPayload,
  hasComposerSessionReferenceDragPayload,
} from "./conversationComposerDropPayload";
import { shouldApplyComposerFocusRequest } from "./conversationComposerFocus";
import { scheduleComposerFocusAttempts } from "./conversationComposerFocusSchedule";
import { extractComposerPastedTextOverflow } from "./conversationComposerPastePayload";
import {
  composerAttachmentAcceptAttribute,
  isComposerAttachableFile,
} from "./conversationConstants";
import { navigatePromptHistory, readPromptHistory } from "./conversationPromptHistory";
import {
  detectReferenceToken,
  filterReferenceTypeaheadOptions,
  removeReferenceToken,
  type ReferenceTypeaheadOption,
  type ReferenceTypeaheadToken,
} from "./conversationReferenceTypeahead";
import {
  groupSlashCommandSuggestionsBySection,
  insertSlashCommandSuggestion,
  mergeSlashCommandSuggestions,
  moveSlashCommandActiveIndex,
  parseSideSlashCommand,
  shouldShowSlashCommandSuggestions,
  type BuiltinSlashCommand,
  type BuiltinSlashCommandId,
  type SlashCommandSuggestion,
} from "./conversationSlashCommandSuggestions";
import { compactConversationPreview } from "./conversationOperationPresentation";
import type { TimelineUserScrollIntent } from "./conversationTimelineFollowState";
import type {
  ConversationComposerAttachment,
  ConversationComposerVariant,
  ConversationLlmControl,
  ConversationPermissionControl,
  ConversationTurnModelControl as ConversationTurnModelControlModel,
} from "./conversationViewTypes";
import { useComposerPromptSuggestion } from "./useComposerPromptSuggestion";
import styles from "./ConversationView.styles";

// How long the "long paste became an attachment" status row stays visible.
const COMPOSER_PASTE_NOTICE_VISIBLE_MS = 8000;

export type UseConversationComposerInput = {
  sessionId: string;
  messages: ConversationMessage[];
  showComposer: boolean;
  composerVariant: ConversationComposerVariant;
  composerValue: string;
  composerPlaceholder: string;
  composerDisabled: boolean;
  promptSuggestionEnabled: boolean;
  composerFocusSignal: string;
  onComposerFocusRequestSettled?: (focusSignal: string) => void;
  composerActionDisabled?: boolean;
  composerActionMode?: "send" | "stop";
  composerPending: boolean;
  composerSafeGuidancePending: boolean;
  composerInterruptGuidancePending: boolean;
  composerError?: string;
  composerGuidance?: string;
  followupQueue: ComposerQueueItem[];
  composerAttachments: ConversationComposerAttachment[];
  composerReferences: SessionReferenceAttachment[];
  slashCommandSuggestions: SkillLibraryItem[];
  slashSkillsCatalogState: "ready" | "loading" | "error";
  composerReferenceOptions: ReferenceTypeaheadOption[];
  composerAttachmentInputDisabled?: boolean;
  composerLeadingControl?: ReactNode;
  permissionControl?: ConversationPermissionControl;
  llmControl?: ConversationLlmControl;
  turnModelControl?: ConversationTurnModelControlModel;
  onOpenAgentModelConfig?: () => void;
  composerContextRing?: ComposerContextRingModel | null;
  onOpenComposerContextDetail?: () => void;
  onCreateSession?: () => void;
  onOpenSideChat?: (draft: string, send: boolean) => void;
  turnError?: SessionTurnError | null;
  submitLabel?: string;
  submitPendingLabel?: string;
  stopLabel?: string;
  stopPendingLabel?: string;
  safeGuidanceLabel?: string;
  safeGuidancePendingLabel?: string;
  editingMessageId?: string;
  composerModeNotice?: string;
  composerModeTargetPreview?: string;
  onComposerChange: (value: string) => void;
  onAddComposerAttachments?: (files: FileList | File[]) => void;
  onRemoveComposerAttachment?: (attachmentId: string) => void;
  onRetryComposerAttachment?: (attachmentId: string) => void;
  onRetryComposerAttachmentUploads?: () => void;
  onAddComposerReference?: (reference: SessionReferenceAttachment) => void;
  onRemoveComposerReference?: (referenceId: string) => void;
  onSubmit: () => void;
  onStop?: () => void;
  onSafeGuidance?: () => void;
  onFollowupQueueUpdate?: (id: string, text: string) => void;
  onFollowupQueueRemove?: (id: string) => void;
  onFollowupQueueMove?: (fromIndex: number, toIndex: number) => void;
  onFollowupQueueSteer?: (id: string) => void;
  onFollowupQueueSendNow?: (id: string) => void;
  followupQueueSteerLabel?: string;
  composerInputRef: RefObject<HTMLTextAreaElement | null>;
  inlineEditInputRef: RefObject<HTMLTextAreaElement | null>;
  lang: Language;
  t: (key: TranslationKey) => string;
  timelineRef: RefObject<HTMLDivElement | null>;
  followLatestRef: { current: boolean };
  atBottomRef: { current: boolean };
  userScrollIntentRef: { current: TimelineUserScrollIntent };
  userScrollIntentAtRef: { current: number };
  setIsAtBottom: (value: boolean) => void;
  scrollTimelineToBottom: (
    timeline: HTMLDivElement,
    options?: { followLatest?: boolean; behavior?: ScrollBehavior },
  ) => void;
  conversationFindOpen: boolean;
  closeConversationFind: () => void;
  openImagePreview: (image: ConversationImagePreviewRequest) => void;
};

/**
 * Composer region extracted from ConversationView with identical output:
 * slash suggestions, mention/reference completion, drag-drop, prompt history,
 * send/stop/queue actions, and the submit path that re-pins follow-latest.
 * Timeline scroll refs stay in ConversationView and are injected here.
 */
export function useConversationComposer({
  sessionId,
  messages,
  showComposer,
  composerVariant,
  composerValue,
  composerPlaceholder,
  composerDisabled,
  promptSuggestionEnabled,
  composerFocusSignal,
  onComposerFocusRequestSettled,
  composerActionDisabled,
  composerActionMode,
  composerPending,
  composerSafeGuidancePending,
  composerInterruptGuidancePending,
  composerError,
  composerGuidance,
  followupQueue,
  composerAttachments,
  composerReferences,
  slashCommandSuggestions,
  slashSkillsCatalogState,
  composerReferenceOptions,
  composerAttachmentInputDisabled,
  composerLeadingControl,
  permissionControl,
  llmControl,
  turnModelControl,
  onOpenAgentModelConfig,
  composerContextRing,
  onOpenComposerContextDetail,
  onCreateSession,
  onOpenSideChat,
  turnError,
  submitLabel,
  submitPendingLabel,
  stopLabel,
  stopPendingLabel,
  safeGuidanceLabel,
  safeGuidancePendingLabel,
  editingMessageId,
  composerModeNotice,
  composerModeTargetPreview,
  onComposerChange,
  onAddComposerAttachments,
  onRemoveComposerAttachment,
  onRetryComposerAttachment,
  onRetryComposerAttachmentUploads,
  onAddComposerReference,
  onRemoveComposerReference,
  onSubmit,
  onStop,
  onSafeGuidance,
  onFollowupQueueUpdate,
  onFollowupQueueRemove,
  onFollowupQueueMove,
  onFollowupQueueSteer,
  onFollowupQueueSendNow,
  followupQueueSteerLabel,
  composerInputRef,
  inlineEditInputRef,
  lang,
  t,
  timelineRef,
  followLatestRef,
  atBottomRef,
  userScrollIntentRef,
  userScrollIntentAtRef,
  setIsAtBottom,
  scrollTimelineToBottom,
  conversationFindOpen,
  closeConversationFind,
  openImagePreview,
}: UseConversationComposerInput) {
  // Prompt history browse state (ArrowUp/Down on an empty draft). Refs instead
  // of state so the keydown closure never reads a stale index or stash.
  const promptHistoryIndexRef = useRef<number | null>(null);
  const promptHistoryDraftRef = useRef<string | null>(null);
  const attachmentInputRef = useRef<HTMLInputElement | null>(null);
  const lastComposerFocusSignalRef = useRef("");
  const lastComposerRestoreSignalRef = useRef("");
  const composerDisabledRef = useRef(composerDisabled);
  composerDisabledRef.current = composerDisabled;
  const [composerDragActive, setComposerDragActive] = useState(false);

  const resolvedActionMode = resolveComposerActionMode(composerActionMode);
  const composerPromptSuggestion = useComposerPromptSuggestion(
    {
      sessionId,
      language: lang,
      suggestionEnabled: promptSuggestionEnabled && !composerDisabled && !editingMessageId,
      starterEnabled: !composerDisabled && !editingMessageId,
      busy: resolvedActionMode === "stop" || composerPending,
      draft: composerValue,
      hasConversation: messages.length > 0,
    },
    (suggestion) => {
      onComposerChange(suggestion);
      requestAnimationFrame(() => composerInputRef.current?.focus());
    },
  );
  const fallbackComposerStarters = useMemo<ComposerStarter[]>(() => [
    { heading: t("sessionStarterOrganizeHeading"), command: t("sessionStarterOrganizeCommand") },
    { heading: t("sessionStarterResearchHeading"), command: t("sessionStarterResearchCommand") },
    { heading: t("sessionStarterDraftHeading"), command: t("sessionStarterDraftCommand") },
  ], [t]);
  // Backend starters win; without them the dictionary keeps generic research
  // starters so the empty session still offers a clickable first step.
  const composerStarters = composerPromptSuggestion.starters.length > 0
    ? composerPromptSuggestion.starters.slice(0, MAX_COMPOSER_STARTERS)
    : fallbackComposerStarters;
  const hasComposerAttachments = composerAttachments.length > 0;
  const hasComposerReferences = composerReferences.length > 0;
  const attachmentInputDisabled = composerAttachmentInputDisabled ?? composerDisabled;
  const resolvedActionDisabled = resolveComposerActionDisabled({
    actionMode: resolvedActionMode,
    composerActionDisabled,
    composerDisabled,
    composerValue,
    hasAttachments: hasComposerAttachments,
    hasReferences: hasComposerReferences,
  });
  const { actionLabel: resolvedActionLabel, pendingLabel: resolvedPendingLabel } = resolveComposerActionLabels({
    actionMode: resolvedActionMode,
    stopLabel,
    submitLabel,
    stopPendingLabel,
    submitPendingLabel,
    fallbackStop: t("stop"),
    fallbackSend: t("send"),
    fallbackStopPending: t("stopPending"),
    fallbackSendPending: t("sendPending"),
  });

  const {
    editModeActive: composerEditModeActive,
  } = resolveComposerEditMode({
    modeNotice: composerModeNotice,
    modeTargetPreview: composerModeTargetPreview,
    turnErrorMessage: turnError?.message,
    compactPreview: compactConversationPreview,
    failureNotice: t("editMessageFailureRerunNotice"),
  });
  const { primaryActionIsEditSubmit, runningGuidanceActionsEnabled } = resolveComposerPrimaryActionFlags({
    actionMode: resolvedActionMode,
    editModeActive: composerEditModeActive,
  });
  const {
    guidanceActionDisabled,
    showQueuePrimary,
    queuePrimaryIsImmediate,
  } = resolveComposerGuidanceUi({
    runningGuidanceActionsEnabled,
    composerValue,
    composerDisabled,
    safeGuidancePending: composerSafeGuidancePending,
    interruptGuidancePending: composerInterruptGuidancePending,
    queueCount: followupQueue.length,
  });
  const queuePrimaryKind = resolveComposerQueuePrimaryKind({
    sessionBusy: runningGuidanceActionsEnabled,
    draft: composerValue,
    queueCount: followupQueue.length,
  });
  const primaryActionIsQueueSubmit = runningGuidanceActionsEnabled && showQueuePrimary;
  const resolvedQueueFollowupLabel = t("queueFollowup");
  const resolvedImmediateSteerLabel = t("immediateSteer");
  const resolvedSafeGuidanceLabel = safeGuidanceLabel ?? t("safeGuidance");
  const resolvedSafeGuidancePendingLabel = safeGuidancePendingLabel ?? t("safeGuidancePending");
  const resolvedBusyPrimaryLabel = queuePrimaryIsImmediate
    ? resolvedImmediateSteerLabel
    : resolvedQueueFollowupLabel;
  // Tooltip carries the keyboard contract: running Enter delivers immediately
  // (or queues the draft when guidance cannot carry it); the button itself
  // stays the explicit queue entry.
  const resolvedBusyPrimaryHint = queuePrimaryIsImmediate
    ? t("composerSteerEnterHint")
    : t("composerQueueSteerEnterHint");
  const baseComposerPlaceholder = composerPlaceholder.trim()
    ? composerPlaceholder
    : resolvedActionMode === "stop"
      ? (followupQueue.length ? t("sessionBusyQueuedPlaceholder") : t("sessionBusyPlaceholder"))
      : composerPlaceholder;
  const resolvedComposerPlaceholder = resolveComposerPlaceholder({
    ghost: composerPromptSuggestion.ghost,
    exampleCommand: composerPromptSuggestion.exampleCommand,
    hasConversation: messages.length > 0,
    lang,
    fallback: baseComposerPlaceholder,
  });
  // Edit/rerun and running-turn queue/steer are labeled primary pills. Do not mix in
  // round icon-only geometry (composerRoundButtonPrimary forces a square slot).
  const primaryActionClassName = primaryActionIsEditSubmit || primaryActionIsQueueSubmit
    ? styles.composerEditSubmitButton
    : `${styles.sendButton} ${styles.composerRoundButton} ${styles.composerRoundButtonPrimary}`;
  const composerCanAcceptImageDrop = Boolean(onAddComposerAttachments) && !attachmentInputDisabled;
  const composerCanAcceptReferenceDrop = Boolean(onAddComposerReference) && !composerDisabled;
  // Recomputed per render on purpose: `t` is not a stable identity and the list
  // is tiny; keyboard state is keyed on composerValue, not on these arrays.
  const builtinSlashCommands: BuiltinSlashCommand[] = [];
  if (onCreateSession) {
    builtinSlashCommands.push({
      id: "new_session",
      command: t("slashBuiltinNewSessionCommand"),
      aliases: String(t("slashBuiltinNewSessionAliases")).split(/\s+/).filter(Boolean),
      description: t("slashBuiltinNewSessionDescription"),
    });
  }
  if (onOpenAgentModelConfig) {
    builtinSlashCommands.push({
      id: "model",
      command: t("slashBuiltinModelCommand"),
      aliases: String(t("slashBuiltinModelAliases")).split(/\s+/).filter(Boolean),
      description: t("slashBuiltinModelDescription"),
    });
  }
  if (onOpenComposerContextDetail) {
    builtinSlashCommands.push({
      id: "compress_context",
      command: t("slashBuiltinCompressCommand"),
      aliases: String(t("slashBuiltinCompressAliases")).split(/\s+/).filter(Boolean),
      description: t("slashBuiltinCompressDescription"),
    });
  }
  if (onOpenSideChat) {
    builtinSlashCommands.push({
      id: "side",
      command: t("slashBuiltinSideCommand"),
      aliases: String(t("slashBuiltinSideAliases")).split(/\s+/).filter(Boolean),
      description: t("slashBuiltinSideDescription"),
    });
  }
  const slashSuggestions = mergeSlashCommandSuggestions(
    builtinSlashCommands,
    slashCommandSuggestions,
    composerValue,
  );
  // Escape dismisses the list for the exact draft that produced it; any edit
  // (including the builtin clearing the draft) re-arms suggestions.
  const [slashDismissedAtValue, setSlashDismissedAtValue] = useState<string | null>(null);
  const [slashActiveIndex, setSlashActiveIndex] = useState(-1);
  useEffect(() => {
    setSlashActiveIndex(-1);
    setReferenceActiveIndex(-1);
  }, [composerValue]);
  const showSlashSuggestions = !composerDisabled
    && slashDismissedAtValue !== composerValue
    && (slashSuggestions.length > 0
      // ZCode panel parity: a still-loading or failed skill catalog must not
      // read as silence — the panel opens to say so instead of staying shut.
      || (shouldShowSlashCommandSuggestions(composerValue) && slashSkillsCatalogState !== "ready"));
  const activeSlashIndex = showSlashSuggestions
    ? (slashActiveIndex >= 0 && slashActiveIndex < slashSuggestions.length ? slashActiveIndex : 0)
    : -1;
  const slashSuggestionListId = `conversation-${sessionId}-slash-suggestions`;
  // "@" reference type-ahead: caret-aware token detection over the same draft.
  // The composer never inserts reference markup; selecting a candidate registers
  // the same structured reference chip as the plus-menu picker and removes the
  // "@fragment" from the draft.
  const [composerReferenceCaret, setComposerReferenceCaret] = useState(0);
  const [composerComposing, setComposerComposing] = useState(false);
  // Oversized plain-text pastes convert into a document attachment; this status
  // row is the light notice (auto-dismisses, never steals focus from the draft).
  const [composerPasteNotice, setComposerPasteNotice] = useState("");
  const [referenceDismissedAtValue, setReferenceDismissedAtValue] = useState<string | null>(null);
  const [referenceActiveIndex, setReferenceActiveIndex] = useState(-1);
  const activeReferenceToken: ReferenceTypeaheadToken | null = useMemo(
    () => (
      composerComposing || composerDisabled || editingMessageId || !onAddComposerReference
        ? null
        : detectReferenceToken(composerValue, composerReferenceCaret)
    ),
    [composerComposing, composerDisabled, composerReferenceCaret, composerValue, editingMessageId, onAddComposerReference],
  );
  const referenceSuggestions = useMemo(
    () => (activeReferenceToken
      ? filterReferenceTypeaheadOptions(composerReferenceOptions, activeReferenceToken.query)
      : []),
    [activeReferenceToken, composerReferenceOptions],
  );
  const showReferenceSuggestions = !composerDisabled
    && composerReferenceOptions.length > 0
    && referenceDismissedAtValue !== composerValue
    && referenceSuggestions.length > 0;
  const activeReferenceIndex = showReferenceSuggestions
    ? (referenceActiveIndex >= 0 && referenceActiveIndex < referenceSuggestions.length ? referenceActiveIndex : 0)
    : -1;
  const referenceSuggestionListId = `conversation-${sessionId}-reference-suggestions`;
  useEffect(() => {
    if (!composerPasteNotice) {
      return;
    }
    const timer = window.setTimeout(
      () => setComposerPasteNotice(""),
      COMPOSER_PASTE_NOTICE_VISIBLE_MS,
    );
    return () => window.clearTimeout(timer);
  }, [composerPasteNotice]);
  function syncComposerReferenceCaret(element: HTMLTextAreaElement | null) {
    setComposerReferenceCaret(element ? element.selectionStart ?? element.value.length : 0);
  }
  function handleReferenceTypeaheadSelect(option: ReferenceTypeaheadOption) {
    if (!activeReferenceToken) {
      return;
    }
    const token = activeReferenceToken;
    // Same structured-reference path as the plus-menu knowledge/file picker.
    onAddComposerReference?.(option.reference);
    const removed = removeReferenceToken(composerValue, token);
    onComposerChange(removed.text);
    setReferenceActiveIndex(-1);
    setReferenceDismissedAtValue(null);
    requestAnimationFrame(() => {
      const input = composerInputRef.current;
      if (!input) {
        return;
      }
      input.focus();
      input.setSelectionRange(removed.caretIndex, removed.caretIndex);
      setComposerReferenceCaret(removed.caretIndex);
    });
  }
  function handleReferenceTypeaheadDismiss() {
    setReferenceDismissedAtValue(composerValue);
    setReferenceActiveIndex(-1);
  }

  useEffect(() => {
    if (!composerCanAcceptImageDrop && !composerCanAcceptReferenceDrop && composerDragActive) {
      setComposerDragActive(false);
    }
  }, [composerCanAcceptImageDrop, composerCanAcceptReferenceDrop, composerDragActive]);

  function handleSlashCommandSuggestion(suggestion: SlashCommandSuggestion) {
    if (suggestion.builtin) {
      // Builtin commands execute immediately: clear the draft so the listbox
      // gate (no leading slash token) closes it, then run the action.
      onComposerChange("");
      setSlashDismissedAtValue("");
      setSlashActiveIndex(-1);
      executeBuiltinSlashCommand(suggestion.builtinId);
      return;
    }
    if (suggestion.skill) {
      onComposerChange(insertSlashCommandSuggestion(composerValue, suggestion.skill.command));
      requestAnimationFrame(() => composerInputRef.current?.focus());
    }
  }

  function executeBuiltinSlashCommand(builtinId?: BuiltinSlashCommandId) {
    switch (builtinId) {
      case "new_session":
        onCreateSession?.();
        break;
      case "model":
        onOpenAgentModelConfig?.();
        break;
      case "compress_context":
        onOpenComposerContextDetail?.();
        break;
      case "side":
        onOpenSideChat?.("", false);
        break;
    }
  }

  function handleSlashCommandDismiss() {
    setSlashDismissedAtValue(composerValue);
    setSlashActiveIndex(-1);
  }

  function handleStarterCardActivate(starter: ComposerStarter) {
    // Fill the composer for editing; the starter is never auto-submitted.
    onComposerChange(starter.command);
    requestAnimationFrame(() => composerInputRef.current?.focus());
  }

  function handleComposerDragEnter(event: DragEvent<HTMLDivElement>) {
    const acceptsImage = composerCanAcceptImageDrop && hasComposerImageDragPayload(event.dataTransfer);
    const acceptsReference = composerCanAcceptReferenceDrop && hasComposerSessionReferenceDragPayload(event.dataTransfer);
    if (!acceptsImage && !acceptsReference) {
      return;
    }
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    setComposerDragActive(true);
  }

  function handleComposerDragOver(event: DragEvent<HTMLDivElement>) {
    const acceptsImage = composerCanAcceptImageDrop && hasComposerImageDragPayload(event.dataTransfer);
    const acceptsReference = composerCanAcceptReferenceDrop && hasComposerSessionReferenceDragPayload(event.dataTransfer);
    if (!acceptsImage && !acceptsReference) {
      return;
    }
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    setComposerDragActive(true);
  }

  function handleComposerDragLeave(event: DragEvent<HTMLDivElement>) {
    if (event.currentTarget.contains(event.relatedTarget as Node | null)) {
      return;
    }
    setComposerDragActive(false);
  }

  function handleComposerDrop(event: DragEvent<HTMLDivElement>) {
    const reference = composerCanAcceptReferenceDrop ? extractComposerSessionReferenceDrop(event.dataTransfer) : null;
    if (reference && onAddComposerReference) {
      event.preventDefault();
      event.dataTransfer.dropEffect = "copy";
      setComposerDragActive(false);
      onAddComposerReference(reference);
      return;
    }
    if (!composerCanAcceptImageDrop || !onAddComposerAttachments) {
      setComposerDragActive(false);
      return;
    }
    const files = extractComposerImageDropFiles(event.dataTransfer);
    if (!files.length) {
      setComposerDragActive(false);
      return;
    }
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    setComposerDragActive(false);
    onAddComposerAttachments(files);
  }

  /**
   * ChatGPT/Claude: sending always re-pins the viewport to the latest turn.
   * Do this before onSubmit so optimistic user + active-turn paint under followLatest.
   */
  function pinFollowLatestForSubmit() {
    userScrollIntentRef.current = "none";
    userScrollIntentAtRef.current = 0;
    followLatestRef.current = true;
    atBottomRef.current = true;
    setIsAtBottom(true);
    const timeline = timelineRef.current;
    if (timeline) {
      scrollTimelineToBottom(timeline, { followLatest: true });
    }
    // Optimistic message height lands after React commit + virtual range rebuild.
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => {
        if (!followLatestRef.current) {
          return;
        }
        const nextTimeline = timelineRef.current;
        if (nextTimeline) {
          scrollTimelineToBottom(nextTimeline, { followLatest: true });
        }
      });
    });
  }

  function exitComposerPromptHistoryBrowse() {
    promptHistoryIndexRef.current = null;
    promptHistoryDraftRef.current = null;
  }

  /**
   * ZCode parity: ArrowUp/ArrowDown on an empty draft (or while already
   * browsing) recall recently sent prompts. Runs after find-bar/slash/ghost/
   * typeahead/IME claims, so it never steals their arrow navigation, and it
   * leaves multi-line caret movement alone for a non-empty draft.
   */
  function handleComposerPromptHistoryNavigation(
    event: React.KeyboardEvent<HTMLTextAreaElement>,
  ): boolean {
    if (event.key !== "ArrowUp" && event.key !== "ArrowDown") {
      return false;
    }
    if (event.nativeEvent.isComposing || composerComposing) {
      return false;
    }
    if (event.shiftKey || event.ctrlKey || event.metaKey || event.altKey) {
      return false;
    }
    // History navigation only takes over from an empty draft or while
    // already browsing; a non-empty draft keeps native caret movement.
    if (promptHistoryIndexRef.current === null && composerValue.length > 0) {
      return false;
    }
    const result = navigatePromptHistory(
      readPromptHistory(),
      promptHistoryIndexRef.current,
      event.key === "ArrowUp" ? "up" : "down",
    );
    if (!result.shouldHandle) {
      return false;
    }
    event.preventDefault();
    if (result.nextIndex === null) {
      // Past the newest entry: hand the composer back to the stashed draft.
      const stashedDraft = promptHistoryDraftRef.current ?? "";
      exitComposerPromptHistoryBrowse();
      onComposerChange(stashedDraft);
      return true;
    }
    if (promptHistoryIndexRef.current === null) {
      // Entering browse mode: stash the (empty) draft for later restore.
      promptHistoryDraftRef.current = composerValue;
    }
    promptHistoryIndexRef.current = result.nextIndex;
    onComposerChange(result.nextValue);
    return true;
  }

  function handleSideChatCommand(): boolean {
    const sideCommand = onOpenSideChat ? parseSideSlashCommand(composerValue) : null;
    if (sideCommand) {
      onComposerChange("");
      onOpenSideChat?.(sideCommand.prompt, Boolean(sideCommand.prompt));
      return true;
    }
    return false;
  }

  function handleQueueSubmit() {
    if (!handleSideChatCommand()) {
      onSubmit();
    }
  }

  function handleSendAndFollowLatest() {
    if (handleSideChatCommand()) {
      return;
    }
    exitComposerPromptHistoryBrowse();
    pinFollowLatestForSubmit();
    onSubmit();
  }

  const handlePrimaryAction = resolvedActionMode === "stop"
    ? (onStop ?? onSubmit)
    : handleSendAndFollowLatest;

  useEffect(() => {
    const focusSignal = String(editingMessageId || "").trim();
    if (!focusSignal) {
      // Reset so re-editing the same message after a cancel refocuses.
      lastComposerFocusSignalRef.current = "";
      return;
    }
    if (focusSignal === lastComposerFocusSignalRef.current || composerDisabled) {
      return;
    }
    lastComposerFocusSignalRef.current = focusSignal;
    // Inline edit lives in the timeline row, not the composer; the row editor
    // mounts in this same commit, so focus it on the next frame.
    const raf = window.requestAnimationFrame(() => {
      const input = inlineEditInputRef.current;
      if (!input) {
        return;
      }
      input.focus();
      const cursorPosition = input.value.length;
      input.setSelectionRange(cursorPosition, cursorPosition);
    });
    return () => window.cancelAnimationFrame(raf);
  }, [composerDisabled, editingMessageId]);

  useEffect(() => {
    const focusSignal = String(composerFocusSignal || "").trim();
    if (!focusSignal) {
      return;
    }
    if (!shouldApplyComposerFocusRequest({
      composerDisabled,
      focusSignal,
      hasCompetingFocus: false,
      lastAppliedFocusSignal: lastComposerRestoreSignalRef.current,
    })) {
      return;
    }

    const settleFocusRequest = () => {
      lastComposerRestoreSignalRef.current = focusSignal;
      onComposerFocusRequestSettled?.(focusSignal);
    };

    return scheduleComposerFocusAttempts({
      getInput: () => composerInputRef.current,
      isDisabled: () => composerDisabledRef.current,
      shouldAbort: () => false,
      onSuccess: settleFocusRequest,
      onGiveUp: settleFocusRequest,
    });
  }, [composerDisabled, composerFocusSignal, onComposerFocusRequestSettled]);

  // Shared so the queue bar stays visible while an inline edit hides the
  // composer field (one edit UI lives in the row, the queue is session status).
  const composerFollowupQueueBar = followupQueue.length ? (
    <ConversationFollowupQueueBar
      items={followupQueue}
      lang={lang}
      variant={composerVariant}
      editLabel={t("editFollowupQueue")}
      withdrawLabel={t("withdrawFollowupQueue")}
      steerLabel={followupQueueSteerLabel ?? t("immediateSteer")}
      saveEditLabel={t("saveFollowupQueueEdit")}
      cancelEditLabel={t("cancelFollowupQueueEdit")}
      dragHandleLabel={t("dragFollowupQueue")}
      sendNowLabel={t("sendFollowupQueueNow")}
      sendNowPendingLabel={t("sendFollowupQueueNowPending")}
      turnRunning={runningGuidanceActionsEnabled}
      onUpdate={onFollowupQueueUpdate ?? (() => undefined)}
      onRemove={onFollowupQueueRemove ?? (() => undefined)}
      onMove={onFollowupQueueMove ?? (() => undefined)}
      onSteer={onFollowupQueueSteer}
      onSendNow={onFollowupQueueSendNow}
    />
  ) : null;

  const composerActions = (
    <div className={styles.composerActionStack}>
      {resolvedActionMode === "stop" && composerPending ? (
        <span
          className={styles.composerStopPendingFeedback}
          role="status"
          aria-live="polite"
          data-testid="composer-stop-pending-feedback"
        >
          {resolvedPendingLabel}
        </span>
      ) : null}
      {!runningGuidanceActionsEnabled || showQueuePrimary ? (
        <VButton
          className={primaryActionClassName}
          isIconOnly={!primaryActionIsEditSubmit && !primaryActionIsQueueSubmit}
          isDisabled={runningGuidanceActionsEnabled ? guidanceActionDisabled : resolvedActionDisabled}
          type="button"
          onClick={runningGuidanceActionsEnabled ? handleQueueSubmit : handlePrimaryAction}
          icon={
            primaryActionIsEditSubmit
              ? (
                composerPending || composerSafeGuidancePending
                  ? <LoaderCircle className={styles.statusSpinner} size={14} aria-hidden="true" />
                  : <RefreshCw size={14} aria-hidden="true" />
              )
              : undefined
          }
          title={
            runningGuidanceActionsEnabled
              ? composerSafeGuidancePending
                ? resolvedSafeGuidancePendingLabel
                : resolvedBusyPrimaryHint
              : composerPending
                ? resolvedPendingLabel
                : primaryActionIsEditSubmit
                  ? resolvedActionLabel
                  : t("composerSendEnterHint")
          }
          aria-label={
            runningGuidanceActionsEnabled
              ? composerSafeGuidancePending
                ? resolvedSafeGuidancePendingLabel
                : resolvedBusyPrimaryLabel
              : composerPending
                ? resolvedPendingLabel
                : resolvedActionLabel
          }
        >
          {primaryActionIsEditSubmit
            ? (composerPending || composerSafeGuidancePending ? resolvedPendingLabel : resolvedActionLabel)
            : primaryActionIsQueueSubmit
              ? (composerSafeGuidancePending ? resolvedSafeGuidancePendingLabel : resolvedBusyPrimaryLabel)
            : (composerPending || composerSafeGuidancePending
              ? <LoaderCircle className={styles.statusSpinner} size={17} aria-hidden="true" />
              : <ArrowUp size={16} aria-hidden="true" />)}
        </VButton>
      ) : null}
      {runningGuidanceActionsEnabled ? (
        <VButton
          className={`${styles.composerRoundButton} ${styles.stopButton}`}
          isIconOnly
          isDisabled={resolvedActionDisabled}
          type="button"
          onClick={handlePrimaryAction}
          title={composerPending ? resolvedPendingLabel : resolvedActionLabel}
          aria-label={composerPending ? resolvedPendingLabel : resolvedActionLabel}
        >
          {composerPending ? (
            <LoaderCircle className={styles.statusSpinner} size={17} aria-hidden="true" />
          ) : (
            <Square size={14} aria-hidden="true" />
          )}
        </VButton>
      ) : null}
    </div>
  );

  const composerSurface = showComposer ? (
      <div className={composerVariant === "codex" ? styles.composerCodex : styles.composer}>
        {/* Inline edit owns the row editor; the composer field steps aside and
            only session status (the followup queue) keeps its slot here. */}
        {editingMessageId ? (
          composerFollowupQueueBar
        ) : (
        <div
          className={
            composerDragActive
              ? `${composerVariant === "codex" ? styles.composerFieldCodex : styles.composerField} ${styles.composerFieldDragActive}`
              : composerVariant === "codex" ? styles.composerFieldCodex : styles.composerField
          }
          onDragEnter={handleComposerDragEnter}
          onDragOver={handleComposerDragOver}
          onDragLeave={handleComposerDragLeave}
          onDrop={handleComposerDrop}
        >
          {/* Upload-failure repair: the error row grows a retry-all action only
              while failed attachment chips exist, so unrelated composer errors
              stay plain. */}
          {composerError ? (
            <p className={styles.composerError} role="alert">
              {composerError}
              {composerAttachments.some((attachment) => attachment.uploadStatus === "failed") && onRetryComposerAttachmentUploads ? (
                <VButton
                  className={styles.composerErrorRetryButton}
                  variant="ghost"
                  type="button"
                  isDisabled={composerPending}
                  onClick={onRetryComposerAttachmentUploads}
                  title={t("retryUpload")}
                  icon={<RefreshCw size={12} aria-hidden="true" />}
                >
                  <span>{t("retryUpload")}</span>
                </VButton>
              ) : null}
            </p>
          ) : null}
          {composerGuidance ? (
            <div className={styles.composerGuidance} role="status" aria-live="polite" data-composer-guidance>
              <span className={styles.composerGuidanceIcon} aria-hidden="true">i</span>
              <span>{composerGuidance}</span>
            </div>
          ) : null}
          {composerPasteNotice ? (
            <div className={styles.composerGuidance} role="status" aria-live="polite" data-composer-paste-notice="true">
              <span className={styles.composerGuidanceIcon} aria-hidden="true">i</span>
              <span>{composerPasteNotice}</span>
            </div>
          ) : null}
          {composerFollowupQueueBar}
          {composerAttachments.length ? (
            <div
              className={styles.composerAttachmentTray}
              role="list"
              aria-label={t("composerAttachmentTrayLabel")}
            >
              {composerAttachments.map((attachment) => {
                const attachmentIsImage = isImageAttachment(attachment);
                const previewLabel = t("composerAttachmentPreviewLabel").replace("{filename}", attachment.filename);
                const sizeLabel = attachmentSizeLabel(attachment.sizeBytes);
                const uploadFailed = attachment.uploadStatus === "failed";
                const uploading = attachment.uploadStatus === "uploading";
                return (
                  <div
                    key={attachment.id}
                    className={uploadFailed
                      ? `${styles.composerAttachmentChip} ${styles.composerAttachmentChipFailed}`
                      : styles.composerAttachmentChip}
                    role="listitem"
                    aria-invalid={uploadFailed || undefined}
                    title={uploadFailed ? t("attachmentUploadFailedRetryHint") : undefined}
                  >
                    {attachmentIsImage ? (
                      <VButton
                        className={styles.composerAttachmentPreview}
                        variant="ghost"
                        type="button"
                        onClick={() => openImagePreview({
                          src: attachment.previewUrl,
                          alt: attachment.filename,
                          downloadUrl: attachment.previewUrl,
                          downloadName: attachment.filename,
                        })}
                        title={previewLabel}
                        aria-label={previewLabel}
                      >
                        <span className={styles.composerAttachmentThumbFrame}>
                          <img className={styles.composerAttachmentThumb} src={attachment.previewUrl} alt="" />
                          <span className={styles.composerAttachmentThumbHint} aria-hidden="true">
                            {lang === "zh" ? "看大图" : "Zoom"}
                          </span>
                        </span>
                      </VButton>
                    ) : (
                      <span className={styles.composerAttachmentFileBadge} aria-hidden="true">
                        <FileText size={15} />
                      </span>
                    )}
                    <span className={styles.composerAttachmentCopy}>
                      <span className={styles.composerAttachmentName} title={attachment.filename}>{attachment.filename}</span>
                      {uploading ? (
                        <span className={styles.composerAttachmentStatusUploading}>
                          <LoaderCircle size={11} aria-hidden="true" className={styles.composerAttachmentUploadingIcon} />
                          {t("attachmentUploading")}
                        </span>
                      ) : sizeLabel ? (
                        <span className={styles.composerAttachmentMeta}>{sizeLabel}</span>
                      ) : null}
                      {uploadFailed ? (
                        <span className={styles.composerAttachmentStatusFailed}>{t("attachmentUploadFailedRetryHint")}</span>
                      ) : null}
                    </span>
                    {uploadFailed && onRetryComposerAttachment ? (
                      <VButton
                        className={styles.composerAttachmentRetryButton}
                        isIconOnly
                        variant="ghost"
                        type="button"
                        onClick={() => onRetryComposerAttachment(attachment.id)}
                        title={t("retryUpload")}
                        aria-label={`${t("retryUpload")}: ${attachment.filename}`}
                      >
                        <RefreshCw size={13} aria-hidden="true" />
                      </VButton>
                    ) : null}
                    {onRemoveComposerAttachment ? (
                      <VButton
                        className={styles.composerAttachmentRemoveButton}
                        isIconOnly
                        type="button"
                        onClick={() => onRemoveComposerAttachment(attachment.id)}
                        title={t("composerAttachmentRemove")}
                        aria-label={t("composerAttachmentRemove")}
                      >
                        <X size={13} aria-hidden="true" />
                      </VButton>
                    ) : null}
                  </div>
                );
              })}
            </div>
          ) : null}
          {composerReferences.length ? (
            <div
              className={styles.composerReferenceTray}
              role="list"
              aria-label={t("composerReferenceTrayLabel")}
            >
              {composerReferences.map((reference) => {
                const referenceId = reference.referenceId || reference.sessionId || reference.artifactId || "";
                const title = reference.title || reference.sessionId || reference.artifactId || "";
                const agentLabel = reference.agentDisplayName || reference.agentCode || reference.agentId || "";
                const kind = String(reference.kind || "session");
                const kindLabel = kind === "knowledge_base"
                  ? t("composerReferenceKindKnowledgeBase")
                  : kind === "knowledge_item"
                    ? t("composerReferenceKindKnowledgeItem")
                    : kind === "file"
                      ? t("composerReferenceKindFile")
                      : kind === "message"
                        ? t("composerReferenceKindMessage")
                        : t("composerReferenceKindSession");
                return (
                  <div key={`${kind}:${referenceId}`} className={styles.composerReferenceChip} role="listitem">
                    <span className={styles.composerReferenceIcon} aria-hidden="true">
                      {kind === "knowledge_base" || kind === "knowledge_item"
                        ? <BookOpen size={13} />
                        : kind === "file"
                          ? <FileText size={13} />
                          : kind === "message"
                            ? <Quote size={13} />
                            : <Link2 size={13} />}
                    </span>
                    <span className={styles.composerReferenceCopy}>
                      <strong title={title}>{title}</strong>
                      <small title={agentLabel || kindLabel}>{agentLabel || kindLabel}</small>
                    </span>
                    {onRemoveComposerReference ? (
                      <VButton
                        type="button"
                        onClick={() => onRemoveComposerReference(referenceId)}
                        title={t("composerReferenceRemove")}
                        aria-label={t("composerReferenceRemove")}
                        isIconOnly
                        icon={<X size={13} aria-hidden="true"/>} />
                    ) : null}
                  </div>
                );
              })}
            </div>
          ) : null}
          {showSlashSuggestions ? (
            <div
              id={slashSuggestionListId}
              role="listbox"
              aria-label={lang === "zh" ? "斜杠指令" : "Slash commands"}
              className={styles.slashCommandSuggestions}
            >
              {/* ZCode panel sections: two labeled groups (builtins vs skills);
                  ArrowUp/Down and the active index stay flat over the merged
                  ranked list, so option ids keep their flat positions. */}
              {(() => {
                let flatIndex = -1;
                const sections = groupSlashCommandSuggestionsBySection(slashSuggestions);
                return (
                  <>
                    {sections.map((section) => (
                      <div
                        key={section.id}
                        role="group"
                        aria-label={section.id === "commands" ? t("slashPanelCommandsSection") : t("slashPanelSkillsSection")}
                        className={styles.slashCommandSection}
                        data-slash-section={section.id}
                      >
                        <div className={styles.slashCommandSectionHeader} aria-hidden="true">
                          {section.id === "commands" ? t("slashPanelCommandsSection") : t("slashPanelSkillsSection")}
                        </div>
                        {section.suggestions.map((suggestion) => {
                          flatIndex += 1;
                          const index = flatIndex;
                          return (
                            <div
                              id={`${slashSuggestionListId}-option-${index}`}
                              key={suggestion.key}
                              role="option"
                              aria-selected={index === activeSlashIndex}
                              aria-label={suggestion.command}
                              className={styles.slashCommandSuggestionOption}
                              data-active={index === activeSlashIndex ? "true" : "false"}
                            >
                              <VButton
                                type="button"
                                className={
                                  index === activeSlashIndex
                                    ? `${styles.slashCommandSuggestionButton} ${styles.slashCommandSuggestionButtonActive}`
                                    : styles.slashCommandSuggestionButton
                                }
                                onMouseDown={(event) => event.preventDefault()}
                                onClick={() => handleSlashCommandSuggestion(suggestion)}
                              >
                                {suggestion.builtin ? (
                                  <span className={styles.slashCommandSuggestionIcon} aria-hidden="true">
                                    {suggestion.builtinId === "new_session" ? (
                                      <CirclePlus size={13} />
                                    ) : suggestion.builtinId === "model" ? (
                                      <Cpu size={13} />
                                    ) : (
                                      <Gauge size={13} />
                                    )}
                                  </span>
                                ) : null}
                                <code className={styles.slashCommandSuggestionCode}>
                                  {suggestion.command}
                                </code>
                                <span className={styles.slashCommandSuggestionDescription}>{suggestion.description}</span>
                                {suggestion.builtin ? (
                                  <span className={styles.slashCommandBuiltinBadge} data-vui="slash-builtin-badge">
                                    {t("slashBuiltinBadge")}
                                  </span>
                                ) : null}
                              </VButton>
                            </div>
                          );
                        })}
                      </div>
                    ))}
                    {/* Skills catalog health: a failed or still-loading library
                        must not read as "no skills" — the section says so. */}
                    {slashSkillsCatalogState === "loading" ? (
                      <div className={styles.slashCommandCatalogNotice} data-slash-catalog-state="loading">
                        {t("slashSkillsCatalogLoading")}
                      </div>
                    ) : slashSkillsCatalogState === "error" ? (
                      <div className={styles.slashCommandCatalogNotice} data-slash-catalog-state="error" role="status">
                        {t("slashSkillsCatalogError")}
                      </div>
                    ) : slashCommandSuggestions.length === 0 ? (
                      <div className={styles.slashCommandCatalogNotice} data-slash-catalog-state="empty">
                        {t("slashSkillsCatalogEmpty")}
                      </div>
                    ) : null}
                  </>
                );
              })()}
            </div>
          ) : null}
          {showReferenceSuggestions ? (
            <div
              id={referenceSuggestionListId}
              role="listbox"
              aria-label={t("composerReferenceTypeaheadListLabel")}
              className={styles.slashCommandSuggestions}
            >
              {referenceSuggestions.map((option, index) => (
                <div
                  id={`${referenceSuggestionListId}-option-${index}`}
                  key={option.id}
                  role="option"
                  aria-selected={index === activeReferenceIndex}
                  aria-label={option.title}
                  className={styles.slashCommandSuggestionOption}
                  data-active={index === activeReferenceIndex ? "true" : "false"}
                >
                  <VButton
                    type="button"
                    className={
                      index === activeReferenceIndex
                        ? `${styles.slashCommandSuggestionButton} ${styles.slashCommandSuggestionButtonActive}`
                        : styles.slashCommandSuggestionButton
                    }
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => handleReferenceTypeaheadSelect(option)}
                  >
                    <span className={styles.slashCommandSuggestionIcon} aria-hidden="true">
                      {option.reference.kind === "file" ? (
                        <FileText size={13} />
                      ) : option.reference.kind === "session" ? (
                        <MessageSquareText size={13} />
                      ) : (
                        <BookOpen size={13} />
                      )}
                    </span>
                    <strong className={styles.slashCommandSuggestionCode}>
                      {option.title}
                    </strong>
                    {option.meta ? (
                      <span className={styles.slashCommandSuggestionDescription}>{option.meta}</span>
                    ) : null}
                    <span className={styles.slashCommandBuiltinBadge} data-vui="reference-typeahead-badge">
                      {t("composerReferenceTypeaheadBadge")}
                    </span>
                  </VButton>
                </div>
              ))}
            </div>
          ) : null}
          <VNativeTextarea
            ref={composerInputRef}
            className={composerVariant === "codex" ? styles.inputCodex : styles.input}
            value={composerValue}
            disabled={composerDisabled && resolvedActionMode !== "stop"}
            placeholder={resolvedComposerPlaceholder}
            data-composer-prompt-suggestion={composerPromptSuggestion.ghost ? "true" : undefined}
            aria-label={lang === "zh" ? "发送消息" : "Message"}
            aria-controls={
              showSlashSuggestions
                ? slashSuggestionListId
                : showReferenceSuggestions
                  ? referenceSuggestionListId
                  : undefined
            }
            aria-expanded={showSlashSuggestions || showReferenceSuggestions ? true : undefined}
            aria-autocomplete={showSlashSuggestions || showReferenceSuggestions ? "list" : undefined}
            aria-activedescendant={
              showSlashSuggestions && activeSlashIndex >= 0
                ? `${slashSuggestionListId}-option-${activeSlashIndex}`
                : showReferenceSuggestions && activeReferenceIndex >= 0
                  ? `${referenceSuggestionListId}-option-${activeReferenceIndex}`
                  : undefined
            }
            onChange={(event) => {
              // Any manual edit (typing, IME, cut) leaves the history browse
              // mode; programmatic history fills do not go through onChange.
              exitComposerPromptHistoryBrowse();
              onComposerChange(event.target.value);
              syncComposerReferenceCaret(event.currentTarget);
            }}
            onCompositionStart={() => setComposerComposing(true)}
            onCompositionEnd={(event) => {
              // IME text was just committed: re-evaluate the token with the
              // post-composition caret so CJK "@引用" arms only after commit.
              setComposerComposing(false);
              syncComposerReferenceCaret(event.currentTarget);
            }}
            onSelect={() => syncComposerReferenceCaret(composerInputRef.current)}
            onKeyUp={() => syncComposerReferenceCaret(composerInputRef.current)}
            onPaste={(event) => {
              if (!onAddComposerAttachments || attachmentInputDisabled) {
                return;
              }
              const files = Array.from(event.clipboardData.files || []).filter((file) => isComposerAttachableFile(file));
              if (files.length) {
                event.preventDefault();
                onAddComposerAttachments(files);
                return;
              }
              // ZCode parity: an oversized plain-text paste silently becomes a
              // document attachment instead of flooding the draft; the attachment
              // chip plus the status row carry the notice.
              const pastedTextOverflow = extractComposerPastedTextOverflow(event.clipboardData);
              if (pastedTextOverflow) {
                event.preventDefault();
                onAddComposerAttachments([pastedTextOverflow]);
                setComposerPasteNotice(
                  t("composerPastedTextAttachmentNotice").replace("{filename}", pastedTextOverflow.name),
                );
              }
            }}
            onKeyDown={(event) => {
              // Find-in-transcript Esc first（优先于停止语义）：查找条打开时
              // Esc 只关查找条，绝不触发轮次停止。
              if (conversationFindOpen && event.key === "Escape" && !event.nativeEvent.isComposing) {
                event.preventDefault();
                closeConversationFind();
                return;
              }
              if (
                shouldAcceptComposerGhost({
                  ghost: composerPromptSuggestion.ghost,
                  key: event.key,
                  shiftKey: event.shiftKey,
                  ctrlKey: event.ctrlKey,
                  metaKey: event.metaKey,
                  altKey: event.altKey,
                })
              ) {
                event.preventDefault();
                composerPromptSuggestion.acceptGhost();
                return;
              }
              if (composerPromptSuggestion.ghost && event.key === "Escape") {
                event.preventDefault();
                composerPromptSuggestion.dismissGhost();
                return;
              }
              if (showSlashSuggestions && !event.shiftKey && !event.ctrlKey && !event.metaKey && !event.altKey) {
                if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                  event.preventDefault();
                  setSlashActiveIndex((current) => moveSlashCommandActiveIndex(
                    current,
                    event.key === "ArrowDown" ? 1 : -1,
                    slashSuggestions.length,
                  ));
                  return;
                }
                if (event.key === "Tab" || (event.key === "Enter" && !event.nativeEvent.isComposing)) {
                  event.preventDefault();
                  if (activeSlashIndex >= 0) {
                    handleSlashCommandSuggestion(slashSuggestions[activeSlashIndex]);
                  }
                  return;
                }
                if (event.key === "Escape") {
                  event.preventDefault();
                  handleSlashCommandDismiss();
                  return;
                }
              }
              if (showReferenceSuggestions && !event.shiftKey && !event.ctrlKey && !event.metaKey && !event.altKey) {
                if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                  event.preventDefault();
                  setReferenceActiveIndex((current) => moveSlashCommandActiveIndex(
                    current,
                    event.key === "ArrowDown" ? 1 : -1,
                    referenceSuggestions.length,
                  ));
                  return;
                }
                if (event.key === "Tab" || (event.key === "Enter" && !event.nativeEvent.isComposing)) {
                  event.preventDefault();
                  if (activeReferenceIndex >= 0) {
                    handleReferenceTypeaheadSelect(referenceSuggestions[activeReferenceIndex]);
                  }
                  return;
                }
                if (event.key === "Escape") {
                  event.preventDefault();
                  handleReferenceTypeaheadDismiss();
                  return;
                }
              }
              // Prompt history recall: claims bare ArrowUp/Down only when the
              // draft is empty (or browsing is already active); everything
              // above (find bar, ghost, slash, typeahead) already had its
              // chance, and IME composition is excluded inside.
              if (handleComposerPromptHistoryNavigation(event)) {
                return;
              }
              // Yield-aware Esc→stop: ghost/slash/typeahead branches above
              // return when they consume Escape; this fallback only fires when
              // the key is still unclaimed and a turn is running. Repeats are
              // deduped downstream by the sessionStopping stop guard.
              if (
                shouldStopComposerOnEscape({
                  key: event.key,
                  defaultPrevented: event.defaultPrevented,
                  composing: event.nativeEvent.isComposing,
                  actionMode: resolvedActionMode,
                  hasStopHandler: Boolean(onStop),
                  ghostVisible: Boolean(composerPromptSuggestion.ghost),
                  slashSuggestionsOpen: showSlashSuggestions,
                  referenceTypeaheadOpen: showReferenceSuggestions,
                })
              ) {
                event.preventDefault();
                onStop?.();
              }
              // Enter delivery: while a turn runs, Enter immediately steers
              // the draft via the existing safe-guidance channel, falling
              // back to queueing when the payload cannot ride guidance
              // (attachments/references) or no guidance handler exists.
              // Idle Enter sends. Modifier keys never change the delivery
              // (user decision removed the Ctrl/⌘+Enter flip).
              const composerEnterDelivery = resolveComposerEnterDelivery({
                key: event.key,
                shiftKey: event.shiftKey,
                ctrlKey: event.ctrlKey,
                metaKey: event.metaKey,
                altKey: event.altKey,
                isComposing: event.nativeEvent.isComposing,
                actionMode: resolvedActionMode,
                canDeliverImmediately: Boolean(onSafeGuidance)
                  && !hasComposerAttachments
                  && !hasComposerReferences,
              });
              if (composerEnterDelivery !== "none") {
                event.preventDefault();
                if (
                  composerEnterDelivery === "send"
                  && !resolvedActionDisabled
                  && (composerValue.trim() || hasComposerAttachments || hasComposerReferences)
                ) {
                  handleSendAndFollowLatest();
                } else if (composerEnterDelivery === "steer" && composerValue.trim() && onSafeGuidance) {
                  if (!guidanceActionDisabled && !handleSideChatCommand()) {
                    onSafeGuidance();
                  }
                } else if (
                  (queuePrimaryKind === "queue" || queuePrimaryKind === "immediate")
                  && !guidanceActionDisabled
                ) {
                  handleQueueSubmit();
                }
              }
            }}
          />
          <div className={composerVariant === "codex" ? styles.composerToolbarCodex : styles.composerToolbar}>
            <div className={styles.composerToolbarStart}>
              {composerLeadingControl ?? (
                <VButton
                  className={styles.attachButton}
                  isIconOnly
                  isDisabled={attachmentInputDisabled || !onAddComposerAttachments}
                  type="button"
                  onClick={() => attachmentInputRef.current?.click()}
                  title={t("composerAttachTooltip")}
                  aria-label={t("composerAttachTooltip")}
                >
                  <ImagePlus size={16} />
                </VButton>
              )}
              {permissionControl ? (
                <AgentPermissionPresetControl
                  {...permissionControl}
                  lang={lang}
                  surface="composer"
                />
              ) : null}
            </div>
            <div className={styles.composerToolbarEnd}>
              {turnModelControl ? <ConversationTurnModelControl {...turnModelControl} /> : null}
              {llmControl ? <ConversationInferenceControl {...llmControl} /> : null}
              {composerContextRing ? (
                <ComposerContextRing
                  model={composerContextRing}
                  lang={lang}
                  sessionId={sessionId}
                  onOpenDetail={onOpenComposerContextDetail}
                />
              ) : null}
              {composerVariant === "codex" ? composerActions : null}
            </div>
          </div>
        </div>
        )}
        <VNativeInput
          ref={attachmentInputRef}
          className={styles.hiddenAttachmentInput}
          type="file"
          accept={composerAttachmentAcceptAttribute()}
          multiple
          disabled={attachmentInputDisabled}
          onChange={(event) => {
            if (event.currentTarget.files && onAddComposerAttachments) {
              onAddComposerAttachments(event.currentTarget.files);
            }
            event.currentTarget.value = "";
          }}
        />
        {composerVariant === "compact" ? composerActions : null}
      </div>
  ) : null;

  return {
    composerSurface,
    composerStarters,
    handleStarterCardActivate,
    handleSendAndFollowLatest,
    resolvedSafeGuidanceLabel,
  };
}
