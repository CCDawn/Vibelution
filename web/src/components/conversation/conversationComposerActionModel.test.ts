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
  it("resolves enter delivery: idle bare Enter sends, idle modifier Enter stays unbound", () => {
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
    expect(resolveComposerEnterDelivery({ ...idle, ctrlKey: true })).toBe("none");
    expect(resolveComposerEnterDelivery({ ...idle, metaKey: true })).toBe("none");
  });

  it("resolves enter delivery: running bare Enter queues, Ctrl/⌘+Enter flips to steer", () => {
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
    expect(resolveComposerEnterDelivery(running)).toBe("queue");
    expect(resolveComposerEnterDelivery({ ...running, ctrlKey: true })).toBe("steer");
    expect(resolveComposerEnterDelivery({ ...running, metaKey: true })).toBe("steer");
  });

  it("falls the Ctrl/⌘+Enter flip back to queueing when the payload cannot ride guidance", () => {
    const running = {
      key: "Enter",
      shiftKey: false,
      ctrlKey: true,
      metaKey: false,
      altKey: false,
      isComposing: false,
      actionMode: "stop" as const,
      canDeliverImmediately: false,
    };
    expect(resolveComposerEnterDelivery(running)).toBe("queue");
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
