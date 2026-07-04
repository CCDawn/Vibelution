import { describe, expect, it } from "vitest";

import {
  buildConversationComposerBridgeState,
  mapChatComposerImageAttachments,
  type ChatConversationComposerBridgeLabels,
} from "./ChatConversationComposerBridge";

const labels: ChatConversationComposerBridgeLabels = {
  editMessageModeNotice: "editing",
  editMessagePlaceholder: "edit message",
  loadingSession: "loading",
  messageInputPlaceholder: "message",
};

describe("ChatConversationComposerBridge", () => {
  it("keeps send disabled until text, image attachments, or references exist", () => {
    const emptyState = buildConversationComposerBridgeState({
      imageAttachments: [],
      imageInputUnsupported: false,
      interruptGuidancePending: false,
      labels,
      references: [],
      safeGuidancePending: false,
      sessionBusy: false,
      sessionId: "session-1",
      sessionStopping: false,
      stopPending: false,
      submitPending: false,
      value: "  ",
    });
    expect(emptyState.actionMode).toBe("send");
    expect(emptyState.disabled).toBe(false);
    expect(emptyState.actionDisabled).toBe(true);
    expect(emptyState.placeholder).toBe("message");

    const attachmentState = buildConversationComposerBridgeState({
      ...emptyStateInput(),
      imageAttachments: [{
        id: "image-1",
        filename: "diagram.png",
        previewUrl: "blob:image",
        sizeBytes: 42,
        contentType: "image/png",
      }],
    });
    expect(attachmentState.actionDisabled).toBe(false);
    expect(attachmentState.attachments).toEqual([{
      id: "image-1",
      filename: "diagram.png",
      previewUrl: "blob:image",
      sizeBytes: 42,
      contentType: "image/png",
    }]);
  });

  it("switches active-send controls into stop mode while preserving route-owned stop pending state", () => {
    const state = buildConversationComposerBridgeState({
      ...emptyStateInput(),
      sessionBusy: true,
      stopPending: true,
      value: "hello",
    });

    expect(state.actionMode).toBe("stop");
    expect(state.pending).toBe(true);
    expect(state.actionDisabled).toBe(true);
    expect(state.placeholder).toBe("");
  });

  it("disables image input in edit mode or when the active model cannot read images", () => {
    const editingState = buildConversationComposerBridgeState({
      ...emptyStateInput(),
      editTargetMessageId: "message-1",
      value: "rewrite",
    });
    expect(editingState.attachmentInputDisabled).toBe(true);
    expect(editingState.modeNotice).toBe("editing");
    expect(editingState.placeholder).toBe("edit message");
    expect(editingState.editingMessageId).toBe("message-1");

    const unsupportedState = buildConversationComposerBridgeState({
      ...emptyStateInput(),
      imageInputUnsupported: true,
    });
    expect(unsupportedState.attachmentInputDisabled).toBe(true);
  });

  it("maps route-owned image attachments to the public ConversationView composer DTO", () => {
    const mapped = mapChatComposerImageAttachments([{
      id: "a",
      filename: "a.webp",
      previewUrl: "blob:a",
      sizeBytes: 7,
      contentType: "image/webp",
    }]);

    expect(mapped).toEqual([{
      id: "a",
      filename: "a.webp",
      previewUrl: "blob:a",
      sizeBytes: 7,
      contentType: "image/webp",
    }]);
  });
});

function emptyStateInput() {
  return {
    imageAttachments: [],
    imageInputUnsupported: false,
    interruptGuidancePending: false,
    labels,
    references: [],
    safeGuidancePending: false,
    sessionBusy: false,
    sessionId: "session-1",
    sessionStopping: false,
    stopPending: false,
    submitPending: false,
    value: "",
  };
}
