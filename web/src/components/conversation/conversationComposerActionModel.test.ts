import { describe, expect, it } from "vitest";

import {
  resolveComposerActionDisabled,
  resolveComposerActionLabels,
  resolveComposerActionMode,
  resolveComposerEditMode,
  resolveComposerGuidanceUi,
  resolveComposerPrimaryActionFlags,
  shouldStopComposerOnEscape,
} from "./conversationComposerActionModel";

describe("conversationComposerActionModel", () => {
  it("resolves action mode, disabled state, and labels", () => {
    expect(resolveComposerActionMode(undefined)).toBe("send");
    expect(resolveComposerActionDisabled({
      actionMode: "send",
      composerDisabled: false,
      composerValue: "",
      hasAttachments: false,
      hasReferences: false,
    })).toBe(true);
    expect(resolveComposerActionDisabled({
      actionMode: "stop",
      composerDisabled: false,
      composerValue: "",
      hasAttachments: false,
      hasReferences: false,
    })).toBe(false);
    expect(resolveComposerActionLabels({
      actionMode: "stop",
      fallbackStop: "Stop",
      fallbackSend: "Send",
      fallbackStopPending: "Stopping",
      fallbackSendPending: "Sending",
    })).toEqual({ actionLabel: "Stop", pendingLabel: "Stopping" });
  });

  it("resolves edit mode and guidance UI flags", () => {
    const edit = resolveComposerEditMode({
      modeNotice: "editing",
      modeTargetPreview: "hello world",
      turnErrorMessage: "failed",
      compactPreview: (value) => value.slice(0, 5),
      failureNotice: "rerun",
    });
    expect(edit.editModeActive).toBe(true);
    expect(edit.targetPreview).toBe("hello");
    expect(edit.failureNote).toBe("rerun");
    expect(resolveComposerPrimaryActionFlags({ actionMode: "send", editModeActive: true }).primaryActionIsEditSubmit).toBe(true);
    expect(resolveComposerGuidanceUi({
      runningGuidanceActionsEnabled: true,
      composerValue: "go",
      composerDisabled: false,
      safeGuidancePending: false,
      interruptGuidancePending: false,
    }).showQueuePrimary).toBe(true);
    expect(resolveComposerGuidanceUi({
      runningGuidanceActionsEnabled: true,
      composerValue: "",
      composerDisabled: false,
      safeGuidancePending: false,
      interruptGuidancePending: false,
      queueCount: 1,
    }).queuePrimaryIsImmediate).toBe(true);
  });

  it("stops on unclaimed Escape only in stop mode with a handler and no live overlay", () => {
    const base = {
      key: "Escape",
      defaultPrevented: false,
      composing: false,
      actionMode: "stop" as const,
      hasStopHandler: true,
    };
    expect(shouldStopComposerOnEscape(base)).toBe(true);
    // Send mode never stops via Escape.
    expect(shouldStopComposerOnEscape({ ...base, actionMode: "send" as const })).toBe(false);
    // A already-consumed event must yield.
    expect(shouldStopComposerOnEscape({ ...base, defaultPrevented: true })).toBe(false);
    // IME composition owns Escape (cancel composition, not stop the turn).
    expect(shouldStopComposerOnEscape({ ...base, composing: true })).toBe(false);
    // No stop handler (e.g. legacy embed) stays inert.
    expect(shouldStopComposerOnEscape({ ...base, hasStopHandler: false })).toBe(false);
    // Non-Escape keys are not stop keys.
    expect(shouldStopComposerOnEscape({ ...base, key: "Enter" })).toBe(false);
    // Any live composer overlay claims Escape before the stop fallback.
    expect(shouldStopComposerOnEscape({ ...base, ghostVisible: true })).toBe(false);
    expect(shouldStopComposerOnEscape({ ...base, slashSuggestionsOpen: true })).toBe(false);
    expect(shouldStopComposerOnEscape({ ...base, referenceTypeaheadOpen: true })).toBe(false);
  });
});
