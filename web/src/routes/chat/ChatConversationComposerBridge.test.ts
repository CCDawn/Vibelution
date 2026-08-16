import { describe, expect, it } from "vitest";

import {
  buildConversationComposerBridgeState,
  mapChatComposerImageAttachments,
  type ChatConversationComposerBridgeLabels,
} from "./ChatConversationComposerBridge";
import { dictionary } from "../../i18n/dictionary";
import bridgeSource from "./ChatConversationComposerBridge.tsx?raw";

const labels: ChatConversationComposerBridgeLabels = {
  editMessageModeNotice: "editing",
  editMessagePlaceholder: "edit message",
  loadingSession: "loading",
  messageInputPlaceholder: "message",
  saveAndRerunMessage: "save and rerun",
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
      editTargetPreview: "Original prompt",
      value: "rewrite",
    });
    expect(editingState.attachmentInputDisabled).toBe(true);
    expect(editingState.modeNotice).toBe("editing");
    expect(editingState.modeTargetPreview).toBe("Original prompt");
    expect(editingState.submitLabel).toBe("save and rerun");
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

  it("uses concise dictionary placeholders for direct chat turns", () => {
    expect(dictionary.zh.messageInputPlaceholder).toBe("描述下一步要做什么...");
    expect(dictionary.en.messageInputPlaceholder).toBe("Describe the next step...");
    expect(dictionary.zh.sessionBusyPlaceholder).toBe("输入后排队，当前轮结束后自动发出");
    expect(dictionary.en.sessionBusyPlaceholder).toBe("Type to queue; it sends after this turn");
    expect(dictionary.zh.messageInputPlaceholder).not.toContain("当前会话");
    expect(dictionary.en.messageInputPlaceholder).not.toContain("current session");
  });

  it("keeps the composer enabled while submit is pending but the session is idle", () => {
    const state = buildConversationComposerBridgeState({
      ...emptyStateInput(),
      submitPending: true,
      sessionBusy: false,
      sessionStopping: false,
      value: "",
    });

    expect(state.disabled).toBe(false);
    expect(state.actionDisabled).toBe(true);
    expect(state.placeholder).toBe("message");
  });

  it("disables the composer while submit is pending during a busy session", () => {
    const state = buildConversationComposerBridgeState({
      ...emptyStateInput(),
      submitPending: true,
      sessionBusy: true,
      value: "queued",
    });

    expect(state.disabled).toBe(true);
    expect(state.actionMode).toBe("stop");
  });

  it("marks the primary Chat composer as the Codex variant", () => {
    expect(bridgeSource).toContain('composerVariant="codex"');
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
