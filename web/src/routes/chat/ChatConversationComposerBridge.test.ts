import { describe, expect, it } from "vitest";

import {
  buildComposerImageInputGuidance,
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
    expect(state.actionDisabled).toBe(false);
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

    expect(state.actionMode).toBe("stop");
    expect(state.disabled).toBe(false);
    expect(state.actionDisabled).toBe(false);
    expect(state.placeholder).toBe("message");
  });

  it("returns to send as soon as a stop is requested so the next message can be queued", () => {
    const pendingState = buildConversationComposerBridgeState({
      ...emptyStateInput(),
      sessionBusy: true,
      stopPending: true,
      sessionStopping: false,
      value: "hello",
    });
    expect(pendingState.actionMode).toBe("stop");
    expect(pendingState.pending).toBe(true);
    expect(pendingState.actionDisabled).toBe(false);

    const stoppingState = buildConversationComposerBridgeState({
      ...emptyStateInput(),
      sessionBusy: true,
      stopPending: true,
      sessionStopping: true,
      value: "hello",
    });
    expect(stoppingState.actionMode).toBe("send");
    expect(stoppingState.pending).toBe(false);
    expect(stoppingState.actionDisabled).toBe(false);
    expect(stoppingState.placeholder).toBe("message");

    const stoppingEmptyState = buildConversationComposerBridgeState({
      ...emptyStateInput(),
      sessionBusy: true,
      sessionStopping: true,
      value: "",
    });
    expect(stoppingEmptyState.actionMode).toBe("send");
    expect(stoppingEmptyState.actionDisabled).toBe(true);
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

  it("explains that a waiting image is held until the running turn ends", () => {
    expect(buildComposerImageInputGuidance({
      attachmentCount: 0,
      heldUntilTurnEnds: true,
      imageInputSupport: null,
      modelLabel: "model-x",
      lang: "zh",
    })).toBe("");
    expect(buildComposerImageInputGuidance({
      attachmentCount: 1,
      heldUntilTurnEnds: true,
      imageInputSupport: null,
      modelLabel: "model-x",
      lang: "zh",
    })).toBe("当前轮运行中：图片会保留在输入框，本轮结束后随下一条消息发送。");
    expect(buildComposerImageInputGuidance({
      attachmentCount: 1,
      heldUntilTurnEnds: true,
      imageInputSupport: true,
      modelLabel: "model-x",
      lang: "en",
    })).toBe("This turn is still running: the image stays in the composer and sends with your next message after the turn ends.");
    expect(buildComposerImageInputGuidance({
      attachmentCount: 1,
      heldUntilTurnEnds: false,
      imageInputSupport: null,
      modelLabel: "model-x",
      lang: "zh",
    })).toBe("model-x 的图像输入能力尚未验证；将尝试发送，失败时会保留诊断。");
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
