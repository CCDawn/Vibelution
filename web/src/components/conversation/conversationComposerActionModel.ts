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

export function resolveComposerGuidanceUi(input: {
  runningGuidanceActionsEnabled: boolean;
  composerValue: string;
  composerDisabled: boolean;
  safeGuidancePending: boolean;
  interruptGuidancePending: boolean;
}) {
  const guidanceDraftReady = Boolean(input.composerValue.trim());
  const guidanceActionDisabled =
    !guidanceDraftReady
    || input.composerDisabled
    || input.safeGuidancePending
    || input.interruptGuidancePending;
  return {
    guidanceDraftReady,
    guidanceActionDisabled,
    showSafeGuidanceAction: input.runningGuidanceActionsEnabled && guidanceDraftReady,
  };
}
