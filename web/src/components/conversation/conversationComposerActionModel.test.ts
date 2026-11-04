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
      fallbackQueueSendPending: "Queueing",
    })).toEqual({ actionLabel: "Stop", pendingLabel: "Stopping" });
    expect(resolveComposerActionLabels({
      actionMode: "continue",
      continueLabel: "继续任务",
      continuePendingLabel: "正在继续…",
      fallbackStop: "Stop",
      fallbackSend: "Send",
      fallbackStopPending: "Stopping",
      fallbackSendPending: "Sending",
      fallbackQueueSendPending: "Queueing",
    })).toEqual({ actionLabel: "继续任务", pendingLabel: "正在继续…" });
    expect(resolveComposerActionLabels({
      actionMode: "continue",
      fallbackStop: "Stop",
      fallbackSend: "Send",
      fallbackStopPending: "Stopping",
      fallbackSendPending: "Sending",
      fallbackQueueSendPending: "Queueing",
    })).toEqual({ actionLabel: "Continue task", pendingLabel: "Continuing…" });
  });

  it("keeps the queue-send pending label separate from the stop pending copy", () => {
    const base = {
      actionMode: "stop" as const,
      stopPendingLabel: "正在停止…",
      queueSendPendingLabel: "正在排队…",
      fallbackStop: "终止",
      fallbackSend: "发送",
      fallbackStopPending: "终止中",
      fallbackSendPending: "正在发送…",
      fallbackQueueSendPending: "正在排队…",
    };
    // Queue/send RPC in flight while the turn runs: no stop is happening, so
    // the pending feedback must say "queueing", never borrow the stop copy.
    expect(resolveComposerActionLabels({ ...base, queueSendPendingActive: true }))
      .toEqual({ actionLabel: "终止", pendingLabel: "正在排队…" });
    // An actual stop request stays dominant, alone or together with a send.
    expect(resolveComposerActionLabels({ ...base, stopPendingActive: true }))
      .toEqual({ actionLabel: "终止", pendingLabel: "正在停止…" });
    expect(resolveComposerActionLabels({
      ...base, stopPendingActive: true, queueSendPendingActive: true,
    })).toEqual({ actionLabel: "终止", pendingLabel: "正在停止…" });
    // Neither source in flight keeps the legacy stop fallback.
    expect(resolveComposerActionLabels(base))
      .toEqual({ actionLabel: "终止", pendingLabel: "正在停止…" });
    // The queue-send source only speaks in stop mode; idle sends keep the
    // submit pending copy even while a queue/send RPC is in flight.
    expect(resolveComposerActionLabels({
      ...base, actionMode: "send" as const, queueSendPendingActive: true,
    })).toEqual({ actionLabel: "发送", pendingLabel: "正在发送…" });
    // Without a caller label the fallback still says queueing.
    expect(resolveComposerActionLabels({
      ...base, queueSendPendingLabel: undefined, queueSendPendingActive: true,
    }).pendingLabel).toBe("正在排队…");
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
