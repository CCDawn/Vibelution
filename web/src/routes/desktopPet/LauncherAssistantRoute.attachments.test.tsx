// @vitest-environment happy-dom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import type { ConversationViewProps } from "../../components/conversation/conversationViewTypes";
import { LauncherAssistantRoute } from "./LauncherAssistantRoute";

vi.mock("./DesktopPetCharacter", () => ({ DesktopPetCharacter: () => null }));
let conversation: ConversationViewProps;
vi.mock("../../components/conversation/LazyConversationView", () => ({ LazyConversationView: (props: ConversationViewProps) => { conversation = props; return null; } }));
const roots: ReturnType<typeof createRoot>[] = [];
afterEach(async () => {
  for (const root of roots.splice(0)) await act(async () => root.unmount());
  document.body.innerHTML = "";
  localStorage.clear();
  vi.unstubAllGlobals();
});
async function settle() { await act(async () => { await new Promise(resolve => setTimeout(resolve, 25)); }); }
async function setup(enabled: boolean, statusExtra: Record<string, unknown> = {}) {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  vi.stubGlobal("fetch", vi.fn(() => { throw new Error("HTTP forbidden"); }));
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:preview"), revokeObjectURL: vi.fn() }));
  let fail = false;
  let sendFailure: string | null = null;
  const invoke = vi.fn(async (request: Record<string, unknown>) => {
    switch (request.operation) {
      case "status": return { assistant: { agentId: "a", directSessionId: "s", displayName: "助手" },
        ...(enabled ? { attachmentVersion: 1 } : {}), ...statusExtra };
      case "config": return { language: "zh" };
      case "detail": return { id: "s", agentId: "a", status: "ready", messages: [{ id: "m", role: "user", content: "", attachments: [{ artifactId: "user-image-1.png", filename: "old.png", kind: "user_image", contentType: "image/png", sizeBytes: 2, status: "ready", url: "/api/secret", imageUrl: "/api/secret", downloadUrl: "/api/secret" }] }] };
      case "approvals": return [];
      case "dispatches": return { dispatches: [] };
      case "setExpanded": return { expanded: request.expanded };
      case "readAttachment": return { contentType: "image/png", dataBase64: "AQI=" };
      case "uploadAttachment": if (fail) throw new Error("failure"); else return { artifactId: "user-image-2.png", filename: "new.png", contentType: "image/png", sizeBytes: 2, kind: "user_image", status: "ready" };
      case "send": if (sendFailure !== null) throw new Error(sendFailure); return { accepted: true, turnId: "turn" };
      default: throw new Error("unexpected");
    }
  });
  vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const container = document.createElement("div"); document.body.append(container);
  const root = createRoot(container); roots.push(root);
  await act(async () => root.render(createElement(QueryClientProvider, { client }, createElement(LauncherAssistantRoute, { embedded: true, navigationOwned: true }))));
  await settle(); await settle();
  await act(async () => conversation.onVisibleTimelineMessageIds?.(["m"]));
  await settle();
  return {
    invoke,
    setFailure(value: boolean) { fail = value; },
    setSendFailure(message: string | null) { sendFailure = message; },
  };
}
it("keeps unsupported bridge closed and never renders the ordinary session URL", async () => {
  const { invoke } = await setup(false);
  expect(conversation.composerAttachmentInputDisabled).toBe(true);
  expect(conversation.messages[0].role === "user" && conversation.messages[0].attachments?.[0].url).toBe("");
  expect(invoke.mock.calls.some(([request]) => request.operation === "readAttachment")).toBe(false);
});
it("retains failed file, retries it, sends a pure attachment and reads history through IPC", async () => {
  const { invoke, setFailure } = await setup(true);
  expect(conversation.composerAttachmentInputDisabled).toBe(false);
  expect(conversation.messages[0].role === "user" && conversation.messages[0].attachments?.[0].imageUrl).toBe("data:image/png;base64,AQI=");
  const file = new File([new Uint8Array([1, 2])], "new.png", { type: "image/png" });
  await act(async () => conversation.onAddComposerAttachments!([file]));
  expect(conversation.composerAttachments).toHaveLength(1);
  setFailure(true);
  await act(async () => conversation.onSubmit()); await settle(); await settle();
  expect(conversation.composerAttachments?.[0].uploadStatus).toBe("failed");
  expect(invoke.mock.calls.some(([request]) => request.operation === "send")).toBe(false);
  setFailure(false);
  await act(async () => conversation.onRetryComposerAttachment!(conversation.composerAttachments![0].id)); await settle();
  expect(conversation.composerAttachments?.[0].uploadStatus).toBe("uploaded");
  await act(async () => conversation.onSubmit()); await settle(); await settle();
  const sent = invoke.mock.calls.find(([request]) => request.operation === "send")?.[0];
  expect(sent).toMatchObject({ message: "", attachmentIds: ["user-image-2.png"] });
  expect(conversation.composerAttachments).toHaveLength(0);
});

it("retries an unconfirmed send with the identical request and attachment IDs", async () => {
  const { invoke, setSendFailure } = await setup(true);
  const file = new File([new Uint8Array([1, 2])], "new.png", { type: "image/png" });
  await act(async () => conversation.onAddComposerAttachments!([file]));
  setSendFailure("lost acknowledgement");
  await act(async () => conversation.onSubmit()); await settle(); await settle();
  expect(conversation.composerAttachments).toHaveLength(1);
  expect(conversation.composerAttachmentInputDisabled).toBe(true);
  // Unknown outcome: the unconfirmed banner keeps the backend's own message
  // visible next to it instead of silently discarding the diagnosis.
  expect(document.body.textContent).toContain("尚未确认消息是否收到");
  expect(document.body.textContent).toContain("lost acknowledgement");
  const first = invoke.mock.calls.find(([request]) => request.operation === "send")?.[0];
  setSendFailure(null);
  await act(async () => conversation.onSubmit()); await settle(); await settle();
  const sends = invoke.mock.calls.filter(([request]) => request.operation === "send").map(([request]) => request);
  expect(sends).toHaveLength(2);
  expect(sends[1]).toEqual(first);
  expect(invoke.mock.calls.filter(([request]) => request.operation === "uploadAttachment")).toHaveLength(1);
  expect(conversation.composerAttachments).toHaveLength(0);
});

it("unlocks the composer after a definite pre-admission rejection instead of dead-ending unconfirmed", async () => {
  const { invoke, setSendFailure } = await setup(true);
  await act(async () => conversation.onComposerChange!("可编辑草稿"));
  setSendFailure("ASSISTANT_REQUEST_INVALID");
  await act(async () => conversation.onSubmit()); await settle(); await settle();
  const first = invoke.mock.calls.find(([request]) => request.operation === "send");
  expect(first).toBeTruthy();
  // Definite refusal: no unconfirmed lock, editable composer, explanatory status.
  expect(conversation.composerDisabled).toBe(false);
  expect(conversation.composerError).toBe("");
  expect(conversation.composerValue).toBe("可编辑草稿");
  // A corrected resend builds a NEW request identity instead of replaying the refused one.
  setSendFailure(null);
  await act(async () => conversation.onComposerChange!("修改后的草稿"));
  await act(async () => conversation.onSubmit()); await settle(); await settle();
  const sends = invoke.mock.calls.filter(([request]) => request.operation === "send").map(([request]) => request);
  expect(sends).toHaveLength(2);
  expect(sends[1]).toMatchObject({ message: "修改后的草稿" });
  expect(sends[1].requestId).not.toBe(sends[0]!.requestId);
});

it("unlocks the composer on a retryable-busy host code, naming it, without the unconfirmed banner", async () => {
  const { invoke, setSendFailure } = await setup(true);
  await act(async () => conversation.onComposerChange!("稍后重试的草稿"));
  // Electron wraps the structured 503 quiescence gate across the context bridge.
  setSendFailure("Error invoking remote method 'launcherAssistant:invoke': Error: ASSISTANT_QUIESCING");
  await act(async () => conversation.onSubmit()); await settle(); await settle();
  const first = invoke.mock.calls.find(([request]) => request.operation === "send");
  expect(first).toBeTruthy();
  // Pre-admission gate: nothing executed, so the conservative unconfirmed
  // lock must not dead-end the composer and the draft survives for the retry.
  expect(conversation.composerDisabled).toBe(false);
  expect(conversation.composerValue).toBe("稍后重试的草稿");
  expect(conversation.composerError).toBe("");
  // The busy feedback names what happened and keeps the raw code for diagnosis.
  expect(document.body.textContent).toContain("助理正忙");
  expect(document.body.textContent).toContain("ASSISTANT_QUIESCING");
  // No unknown-outcome retry banner anywhere on the page.
  expect(document.body.textContent).not.toContain("尚未确认消息是否收到");
  // The retry resends from the unlocked composer (a fresh request identity,
  // exactly like the corrected resend after a definite rejection).
  setSendFailure(null);
  await act(async () => conversation.onSubmit()); await settle(); await settle();
  const sends = invoke.mock.calls.filter(([request]) => request.operation === "send").map(([request]) => request);
  expect(sends).toHaveLength(2);
  expect(sends[1]).toMatchObject({ message: "稍后重试的草稿" });
  expect(sends[1].requestId).not.toBe(sends[0]!.requestId);
  expect(invoke.mock.calls.filter(([request]) => request.operation === "uploadAttachment")).toHaveLength(0);
});

it("blocks an over-limit draft locally before any upload or send", async () => {
  const { invoke } = await setup(true);
  await act(async () => conversation.onAddComposerAttachments!([new File([new Uint8Array([1, 2])], "new.png", { type: "image/png" })]));
  expect(invoke.mock.calls.some(([request]) => request.operation === "uploadAttachment")).toBe(false);
  await act(async () => conversation.onComposerChange!("字".repeat(64_001)));
  await act(async () => conversation.onSubmit()); await settle(); await settle();
  expect(invoke.mock.calls.some(([request]) => request.operation === "uploadAttachment")).toBe(false);
  expect(invoke.mock.calls.some(([request]) => request.operation === "send")).toBe(false);
  expect(conversation.composerAttachments).toHaveLength(1);
  expect(conversation.composerDisabled).toBe(false);
  // The exact limit still sends.
  await act(async () => conversation.onComposerChange!("字".repeat(64_000)));
  await act(async () => conversation.onSubmit()); await settle(); await settle();
  expect(invoke.mock.calls.some(([request]) => request.operation === "send")).toBe(true);
});

it("blocks sending image attachments when the dialogue model cannot accept images", async () => {
  const { invoke } = await setup(true, { settings: { ok: true, displayName: "助手", modelId: "m", supportsImageInput: false,
    preferences: { characterId: "dafeiyu", showStatus: true, showTitles: true, showCompletion: true, idleMessage: "" } } });
  await act(async () => conversation.onAddComposerAttachments!([new File([new Uint8Array([1, 2])], "new.png", { type: "image/png" })]));
  expect(conversation.composerAttachments).toHaveLength(1);
  // Tray guidance mirrors the chat page: only an explicit false explains itself.
  expect(conversation.composerError).toBe("当前模型不支持图片输入，请移除图片附件后再发送。");
  await act(async () => conversation.onSubmit()); await settle(); await settle();
  expect(invoke.mock.calls.some(([request]) => request.operation === "uploadAttachment")).toBe(false);
  expect(invoke.mock.calls.some(([request]) => request.operation === "send")).toBe(false);
  expect(conversation.composerAttachments).toHaveLength(1);
  expect(conversation.composerDisabled).toBe(false);
});

it("allows document attachments for a text-only model without showing an image warning", async () => {
  const { invoke } = await setup(true, { settings: { ok: true, displayName: "助手", modelId: "m", supportsImageInput: false,
    preferences: { characterId: "dafeiyu", showStatus: true, showTitles: true, showCompletion: true, idleMessage: "" } } });
  await act(async () => conversation.onAddComposerAttachments!([new File(["ok"], "notes.txt", { type: "text/plain" })]));
  expect(conversation.composerAttachments?.[0].kind).toBe("document");
  expect(conversation.composerError).toBe("");
  await act(async () => conversation.onSubmit()); await settle(); await settle();
  expect(invoke.mock.calls.some(([request]) => request.operation === "send")).toBe(true);
});

it("restores uploaded attachment chips across a reload and refills previews through the read IPC", async () => {
  localStorage.setItem("vibelution.launcher-assistant.composer.v1:embedded:s", JSON.stringify({
    version: 1, sessionId: "s", surface: "embedded",
    snapshot: { draft: "恢复的草稿", outstanding: null, acceptedTurnId: "", queuedAcceptance: null,
      attachments: [{ id: "chip-1", artifactId: "user-image-2.png", filename: "kept.png", contentType: "image/png", sizeBytes: 2, kind: "image" }] },
  }));
  await setup(true);
  await settle(); await settle();
  expect(conversation.composerValue).toBe("恢复的草稿");
  expect(conversation.composerAttachments).toHaveLength(1);
  expect(conversation.composerAttachments?.[0]).toMatchObject({ id: "chip-1", artifactId: "user-image-2.png",
    uploadStatus: "uploaded", filename: "kept.png" });
  // The preview is refilled from the uploaded artifact, not a stale blob: URL.
  expect(conversation.composerAttachments?.[0].previewUrl).toBe("data:image/png;base64,AQI=");
  // The restored chip resends without re-uploading.
  const { invoke } = await setup(true);
  await act(async () => conversation.onSubmit()); await settle(); await settle();
  expect(invoke.mock.calls.some(([request]) => request.operation === "uploadAttachment")).toBe(false);
  const sent = invoke.mock.calls.find(([request]) => request.operation === "send")?.[0];
  expect(sent).toMatchObject({ message: "恢复的草稿", attachmentIds: ["user-image-2.png"] });
  expect(conversation.composerAttachments).toHaveLength(0);
});
