export type ComposerFocusRequestState = {
  composerDisabled: boolean;
  focusSignal: string;
  hasCompetingFocus: boolean;
  lastAppliedFocusSignal: string;
};

/**
 * Delete handoff may restore focus only for a new explicit request and only
 * while no other control has claimed focus in the meantime.
 */
export function shouldApplyComposerFocusRequest(
  state: ComposerFocusRequestState,
): boolean {
  const focusSignal = String(state.focusSignal || "").trim();
  return Boolean(
    focusSignal
    && !state.composerDisabled
    && !state.hasCompetingFocus
    && focusSignal !== state.lastAppliedFocusSignal,
  );
}
