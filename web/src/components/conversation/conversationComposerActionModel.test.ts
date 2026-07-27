import { describe, expect, it } from "vitest";

import {
  resolveComposerActionDisabled,
  resolveComposerActionLabels,
  resolveComposerActionMode,
  resolveComposerEditMode,
  resolveComposerGuidanceUi,
  resolveComposerPrimaryActionFlags,
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
    }).showSafeGuidanceAction).toBe(true);
  });
});
