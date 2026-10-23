import { describe, expect, it } from "vitest";

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
    expect(resolveComposerActionDisabled({
      actionMode: "continue",
      composerDisabled: false,
      composerValue: "",
      hasAttachments: false,
      hasReferences: false,
      hasContinueHandler: true,
    })).toBe(false);
    expect(resolveComposerActionDisabled({
      actionMode: "continue",
      composerDisabled: false,
      composerValue: "",
      hasAttachments: false,
      hasReferences: false,
    })).toBe(true);
    expect(resolveComposerActionLabels({
      actionMode: "stop",
      fallbackStop: "Stop",
      fallbackSend: "Send",
      fallbackStopPending: "Stopping",
      fallbackSendPending: "Sending",
    })).toEqual({ actionLabel: "Stop", pendingLabel: "Stopping" });
    expect(resolveComposerActionLabels({
      actionMode: "continue",
      continueLabel: "继续任务",
      continuePendingLabel: "正在继续…",
      fallbackStop: "Stop",
      fallbackSend: "Send",
      fallbackStopPending: "Stopping",
      fallbackSendPending: "Sending",
    })).toEqual({ actionLabel: "继续任务", pendingLabel: "正在继续…" });
    expect(resolveComposerActionLabels({
      actionMode: "continue",
      fallbackStop: "Stop",
      fallbackSend: "Send",
      fallbackStopPending: "Stopping",
      fallbackSendPending: "Sending",
    })).toEqual({ actionLabel: "Continue task", pendingLabel: "Continuing…" });
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
  it("resolves enter delivery: idle Enter sends and modifiers never change it", () => {
    const idle = {
      key: "Enter",
      shiftKey: false,
      ctrlKey: false,
      metaKey: false,
      altKey: false,
      isComposing: false,
      actionMode: "send" as const,
      canDeliverImmediately: true,
    };
    expect(resolveComposerEnterDelivery(idle)).toBe("send");
    expect(resolveComposerEnterDelivery({ ...idle, ctrlKey: true })).toBe("send");
    expect(resolveComposerEnterDelivery({ ...idle, metaKey: true })).toBe("send");
  });

  it("resolves empty Enter to continue while preserving Shift and IME guards", () => {
    const continuation = {
      key: "Enter",
      shiftKey: false,
      ctrlKey: false,
      metaKey: false,
      altKey: false,
      isComposing: false,
      actionMode: "continue" as const,
      canDeliverImmediately: false,
    };
    expect(resolveComposerEnterDelivery(continuation)).toBe("continue");
    expect(resolveComposerEnterDelivery({ ...continuation, shiftKey: true })).toBe("none");
    expect(resolveComposerEnterDelivery({ ...continuation, isComposing: true })).toBe("none");
  });

  it("resolves enter delivery: running Enter steers immediately regardless of modifiers", () => {
    const running = {
      key: "Enter",
      shiftKey: false,
      ctrlKey: false,
      metaKey: false,
      altKey: false,
      isComposing: false,
      actionMode: "stop" as const,
      canDeliverImmediately: true,
    };
    expect(resolveComposerEnterDelivery(running)).toBe("steer");
    expect(resolveComposerEnterDelivery({ ...running, ctrlKey: true })).toBe("steer");
    expect(resolveComposerEnterDelivery({ ...running, metaKey: true })).toBe("steer");
  });

  it("queues while running when the payload cannot ride guidance", () => {
    const running = {
      key: "Enter",
      shiftKey: false,
      ctrlKey: false,
      metaKey: false,
      altKey: false,
      isComposing: false,
      actionMode: "stop" as const,
      canDeliverImmediately: false,
    };
    expect(resolveComposerEnterDelivery(running)).toBe("queue");
    expect(resolveComposerEnterDelivery({ ...running, ctrlKey: true })).toBe("queue");
  });

  it("never submits during IME composition or with shift/alt held", () => {
    const base = {
      key: "Enter",
      shiftKey: false,
      ctrlKey: false,
      metaKey: false,
      altKey: false,
      isComposing: false,
      actionMode: "send" as const,
      canDeliverImmediately: true,
    };
    expect(resolveComposerEnterDelivery({ ...base, isComposing: true })).toBe("none");
    expect(resolveComposerEnterDelivery({ ...base, shiftKey: true })).toBe("none");
    expect(resolveComposerEnterDelivery({ ...base, altKey: true })).toBe("none");
    expect(resolveComposerEnterDelivery({ ...base, key: "a" })).toBe("none");
  });
});
