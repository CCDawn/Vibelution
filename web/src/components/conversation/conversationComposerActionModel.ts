/**
 * Conversation composer primary-action pure resolution (claim: composer action state).
 * Pure: no React / DOM.
 */
export type ComposerActionMode = "send" | "stop" | string;

export function resolveComposerActionMode(composerActionMode?: ComposerActionMode | null) {
  return composerActionMode ?? "send";
}

export function resolveComposerActionDisabled(input: {
  actionMode: ComposerActionMode;
  composerActionDisabled?: boolean;
  composerDisabled: boolean;
  composerValue: string;
  hasAttachments: boolean;
  hasReferences: boolean;
}) {
  if (input.composerActionDisabled !== undefined) {
    return input.composerActionDisabled;
  }
  if (input.actionMode === "stop") {
    return input.composerDisabled;
  }
  return input.composerDisabled
    || (!input.composerValue.trim() && !input.hasAttachments && !input.hasReferences);
}

export function resolveComposerActionLabels(input: {
  actionMode: ComposerActionMode;
  stopLabel?: string;
  submitLabel?: string;
  stopPendingLabel?: string;
  submitPendingLabel?: string;
  fallbackStop: string;
  fallbackSend: string;
  fallbackStopPending: string;
  fallbackSendPending: string;
}) {
  const isStop = input.actionMode === "stop";
  return {
    actionLabel: isStop ? (input.stopLabel ?? input.fallbackStop) : (input.submitLabel ?? input.fallbackSend),
    pendingLabel: isStop
      ? (input.stopPendingLabel ?? input.fallbackStopPending)
      : (input.submitPendingLabel ?? input.fallbackSendPending),
  };
}

export function resolveComposerEditMode(input: {
  modeNotice?: string | null;
  modeTargetPreview?: string | null;
  turnErrorMessage?: string | null;
  compactPreview: (value: string, maxLength?: number) => string;
  failureNotice: string;
}) {
  const editModeActive = Boolean(input.modeNotice);
  return {
    editModeActive,
    targetPreview: editModeActive ? input.compactPreview(input.modeTargetPreview ?? "", 96) : "",
    failureNote: editModeActive && input.turnErrorMessage ? input.failureNotice : "",
  };
}

export function resolveComposerPrimaryActionFlags(input: {
  actionMode: ComposerActionMode;
  editModeActive: boolean;
}) {
  const primaryActionIsEditSubmit = input.actionMode === "send" && input.editModeActive;
  return {
    primaryActionIsEditSubmit,
    runningGuidanceActionsEnabled: input.actionMode === "stop",
  };
}

export type ComposerEnterDelivery = "none" | "send" | "queue" | "steer";

/**
 * ZCode followupModeSettings.resolveOppositeFollowupDelivery parity (claim:
 * composer action state). While a turn runs, bare Enter queues the draft and
 * Ctrl/⌘+Enter flips the delivery to immediate (steer the draft into the
 * running turn via the existing safe-guidance channel). When the immediate
 * channel cannot carry the payload (no handler, or attachments/references
 * riding the draft) the flip falls back to queueing instead of dropping the
 * message. Idle behavior is unchanged: bare Enter sends, modifier Enter stays
 * unbound. Pure: no React / DOM.
 */
export function resolveComposerEnterDelivery(input: {
  key: string;
  shiftKey: boolean;
  ctrlKey: boolean;
  metaKey: boolean;
  altKey: boolean;
  isComposing: boolean;
  actionMode: ComposerActionMode;
  canDeliverImmediately: boolean;
}): ComposerEnterDelivery {
  if (input.isComposing || input.key !== "Enter" || input.shiftKey || input.altKey) {
    return "none";
  }
  const modifierFlip = input.ctrlKey || input.metaKey;
  if (input.actionMode === "stop") {
    if (!modifierFlip) {
      return "queue";
    }
    return input.canDeliverImmediately ? "steer" : "queue";
  }
  return modifierFlip ? "none" : "send";
}

/**
 * Fallback Esc→stop yield decision (claim: composer action state). The composer
 * keydown handler consumes Escape for ghost dismiss, slash suggestions, and
 * reference typeahead first; only when none of those surfaces claims the key
 * and the event is still pristine may Escape stop the running turn. IME
 * composition also yields: Escape cancels the composing text, it never stops.
 * Pure: no React / DOM.
 */
export function shouldStopComposerOnEscape(input: {
  key: string;
  defaultPrevented: boolean;
  composing: boolean;
  actionMode: ComposerActionMode;
  hasStopHandler: boolean;
  ghostVisible?: boolean;
  slashSuggestionsOpen?: boolean;
  referenceTypeaheadOpen?: boolean;
}) {
  if (input.key !== "Escape" || input.defaultPrevented || input.composing) {
    return false;
  }
  if (input.actionMode !== "stop" || !input.hasStopHandler) {
    return false;
  }
  return !input.ghostVisible && !input.slashSuggestionsOpen && !input.referenceTypeaheadOpen;
}

export function resolveComposerGuidanceUi(input: {
  runningGuidanceActionsEnabled: boolean;
  composerValue: string;
  composerDisabled: boolean;
  safeGuidancePending: boolean;
  interruptGuidancePending: boolean;
  queueCount?: number;
}) {
  const queueCount = input.queueCount ?? 0;
  const guidanceDraftReady = Boolean(input.composerValue.trim());
  const showQueuePrimary = input.runningGuidanceActionsEnabled && (
    guidanceDraftReady || queueCount > 0
  );
  const guidanceActionDisabled =
    !showQueuePrimary
    || input.composerDisabled
    || input.safeGuidancePending
    || input.interruptGuidancePending;
  return {
    guidanceDraftReady,
    guidanceActionDisabled,
    showSafeGuidanceAction: showQueuePrimary,
    showQueuePrimary,
    queuePrimaryIsImmediate: input.runningGuidanceActionsEnabled && !guidanceDraftReady && queueCount > 0,
  };
}
