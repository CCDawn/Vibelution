// @vitest-environment happy-dom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import type { ConversationViewProps } from "../../components/conversation/conversationViewTypes";
import { LauncherAssistantRoute } from "./LauncherAssistantRoute";

vi.mock("./DesktopPetCharacter", () => ({ DesktopPetCharacter: () => null }));
let conversation: ConversationViewProps;
vi.mock("../../components/conversation/LazyConversationView", () => ({ LazyConversationView: (props: ConversationViewProps) => {
  conversation = props;
  // The composer leading control (ChatComposerPlusMenu) is the surface under
  // test for privacy attachments; render it so its dialog is reachable by DOM.
  return props.composerLeadingControl ?? null;
} }));
const roots: ReturnType<typeof createRoot>[] = [];
afterEach(async () => {
  for (const root of roots.splice(0)) await act(async () => root.unmount());
  document.body.innerHTML = "";
  localStorage.clear();
  vi.unstubAllGlobals();
});
async function settle() { await act(async () => { await new Promise(resolve => setTimeout(resolve, 25)); }); }
async function setup(enabled: boolean, statusExtra: Record<string, unknown> = {}, detailMessages?: unknown[]) {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  vi.stubGlobal("fetch", vi.fn(() => { throw new Error("HTTP forbidden"); }));
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:preview"), revokeObjectURL: vi.fn() }));
  let fail = false;
  let sendFailure: string | null = null;
  let secretFail = false;
  let secretSent = false;
  const invoke = vi.fn(async (request: Record<string, unknown>) => {
    switch (request.operation) {
      case "status": return { assistant: { agentId: "a", directSessionId: "s", displayName: "助手" },
        ...(enabled ? { attachmentVersion: 1 } : {}), ...statusExtra };
      case "config": return { language: "zh" };
      case "detail": return detailMessages ? { id: "s", agentId: "a", status: "ready", messages: detailMessages }
        : secretSent ? { id: "s", agentId: "a", status: "ready", messages: [
        { id: "m", role: "user", content: "", attachments: [{ artifactId: "user-image-1.png", filename: "old.png", kind: "user_image", contentType: "image/png", sizeBytes: 2, status: "ready", url: "/api/secret", imageUrl: "/api/secret", downloadUrl: "/api/secret" }] },
        { id: "m2", role: "user", content: "", attachments: [{ artifactId: "sec_test123", filename: "中转站密钥", kind: "user_secret", contentType: "application/octet-stream", sizeBytes: 0, status: "ready", url: "", imageUrl: "", downloadUrl: "" }] },
      ] } : { id: "s", agentId: "a", status: "ready", messages: [{ id: "m", role: "user", content: "", attachments: [{ artifactId: "user-image-1.png", filename: "old.png", kind: "user_image", contentType: "image/png", sizeBytes: 2, status: "ready", url: "/api/secret", imageUrl: "/api/secret", downloadUrl: "/api/secret" }] }] };
      case "approvals": return [];
      case "dispatches": return { dispatches: [] };
      case "setExpanded": return { expanded: request.expanded };
      case "readAttachment": return { contentType: "image/png", dataBase64: "AQI=" };
      case "uploadAttachment": if (fail) throw new Error("failure"); else return { artifactId: "user-image-2.png", filename: "new.png", contentType: "image/png", sizeBytes: 2, kind: "user_image", status: "ready" };
      case "upload_attachment": {
        if (request.kind !== "user_secret" || typeof request.value !== "string" || !request.value) throw new Error("ASSISTANT_REQUEST_INVALID");
        // The unified dialog sends no secretKind; the host echoes the label as a third key when one was sent.
        if ("secretKind" in request) throw new Error("ASSISTANT_REQUEST_INVALID");
        if (secretFail) throw new Error("Launcher 未确认隐私附件暂存。");
        return typeof request.label === "string" && request.label
          ? { attachmentId: "sec_test123", kind: "user_secret", label: request.label }
          : { attachmentId: "sec_test123", kind: "user_secret" };
      }
      case "send": if (sendFailure !== null) throw new Error(sendFailure); secretSent = true; return { accepted: true, turnId: "turn" };
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
    setSecretFailure(value: boolean) { secretFail = value; },
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

it("restores a persisted secret chip as a masked reference without reading any value", async () => {
  localStorage.setItem("vibelution.launcher-assistant.composer.v1:embedded:s", JSON.stringify({
    version: 1, sessionId: "s", surface: "embedded",
    snapshot: { draft: "", outstanding: null, acceptedTurnId: "", queuedAcceptance: null,
      attachments: [{ id: "sec-chip-1", artifactId: "sec_test123", filename: "隐私 · API 密钥", contentType: "application/octet-stream", sizeBytes: 0, kind: "secret" }] },
  }));
  const { invoke } = await setup(true);
  await settle(); await settle();
  expect(conversation.composerAttachments).toHaveLength(1);
  expect(conversation.composerAttachments?.[0]).toMatchObject({ id: "sec-chip-1", artifactId: "sec_test123",
    kind: "secret", uploadStatus: "uploaded", filename: "隐私 · API 密钥" });
  // No read attempt for the sec_ reference — it has no bytes here (the image
  // chip's own preview read is unrelated and allowed).
  expect(invoke.mock.calls.filter(([request]) => request.operation === "readAttachment")
    .some(([request]) => String(request.artifactId || "").startsWith("sec_"))).toBe(false);
  // The restored secret chip rides the next send as a reference.
  await act(async () => conversation.onSubmit()); await settle(); await settle();
  const sent = invoke.mock.calls.find(([request]) => request.operation === "send")?.[0];
  expect(sent).toMatchObject({ message: "", attachmentIds: ["sec_test123"] });
});

it("stages a private attachment through the closed verb, sends only the sec_ reference and never persists the plaintext", async () => {
  const PLAINTEXT = "sk-relay-9f8a-live-value";
  const { invoke, setSecretFailure } = await setup(true);
  // Open the plus menu, then the private attachment dialog.
  const trigger = document.querySelector<HTMLButtonElement>('button[aria-label="更多操作"]')!;
  await act(async () => trigger.click());
  const menuItem = [...document.querySelectorAll<HTMLButtonElement>('[data-plus-menu-item="true"]')]
    .find(button => button.textContent?.includes("隐私附件"));
  expect(menuItem).toBeTruthy();
  await act(async () => menuItem!.click());
  const password = document.querySelector<HTMLInputElement>('input[type="password"]');
  expect(password).not.toBeNull();
  const labelInput = document.querySelector<HTMLInputElement>('input[aria-label="隐私附件显示名"]')!;
  // One unified path: the dialog has no kind selector at all.
  expect(document.querySelector('[role="combobox"]')).toBeNull();
  // Failure first: the error surfaces in the dialog and nothing reaches the tray.
  setSecretFailure(true);
  const setInput = (element: HTMLInputElement, value: string) => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(element, value);
    element.dispatchEvent(new Event("input", { bubbles: true }));
  };
  await act(async () => {
    setInput(labelInput, "中转站密钥");
    setInput(password!, PLAINTEXT);
  });
  const submit = [...document.querySelectorAll<HTMLButtonElement>("button")].find(button => button.textContent?.trim() === "添加")!;
  await act(async () => submit.click());
  expect(document.querySelector('[role="alert"]')?.textContent).toContain("隐私附件暂存失败");
  expect(conversation.composerAttachments).toHaveLength(0);
  // Correction succeeds: the closed verb receives the plaintext exactly once.
  setSecretFailure(false);
  await act(async () => submit.click());
  const upload = invoke.mock.calls.filter(([request]) => request.operation === "upload_attachment");
  expect(upload).toHaveLength(2);
  // The unified request carries value + label, and no secretKind; the host echoed
  // the label as the third response key.
  expect(upload[1]![0]).toMatchObject({ operation: "upload_attachment", kind: "user_secret",
    value: PLAINTEXT, label: "中转站密钥" });
  expect("secretKind" in (upload[1]![0] as Record<string, unknown>)).toBe(false);
  // Success closes the dialog, burns the plaintext and mounts a masked chip.
  expect(document.querySelector('input[type="password"]')).toBeNull();
  expect(document.body.textContent).not.toContain(PLAINTEXT);
  expect(conversation.composerAttachments).toHaveLength(1);
  expect(conversation.composerAttachments?.[0]).toMatchObject({ kind: "secret", artifactId: "sec_test123",
    uploadStatus: "uploaded", filename: "隐私 · 中转站密钥" });
  // The plaintext never entered any persisted draft or snapshot.
  for (let index = 0; index < localStorage.length; index += 1) {
    expect(localStorage.getItem(localStorage.key(index) || "") || "").not.toContain(PLAINTEXT);
  }
  // Send rides the sec_ reference only; the mask card data stays unread and URL-less.
  await act(async () => conversation.onSubmit()); await settle(); await settle();
  const sent = invoke.mock.calls.filter(([request]) => request.operation === "send").at(-1)?.[0];
  expect(sent).toMatchObject({ message: "", attachmentIds: ["sec_test123"] });
  expect(invoke.mock.calls.filter(([request]) => request.operation === "readAttachment")
    .some(([request]) => String((request as Record<string, unknown>).artifactId || "").startsWith("sec_"))).toBe(false);
  const secretMessage = conversation.messages.find(message => message.id === "m2");
  expect(secretMessage && secretMessage.role === "user" ? secretMessage.attachments?.[0] : null).toMatchObject({
    kind: "user_secret", url: "", imageUrl: "", downloadUrl: "" });
  expect(document.body.textContent).not.toContain(PLAINTEXT);
  // The tray chip cleared after the accepted send.
  expect(conversation.composerAttachments).toHaveLength(0);
});

// The assistant `secret_request` tool receipt rides the canonical `tool_call`
// item's `output` JSON; the composer banner asks the operator to attach.
const SECRET_REQUEST_TURN_ITEMS = [
  { type: "agent_message", id: "a-item-text", itemId: "a-item-text", version: 3, sessionId: "s",
    turnId: "t-secret", status: "completed", revision: 1, sequence: 1, phase: "commentary",
    text: "我需要一个 API 密钥才能继续。" },
  { type: "tool_call", id: "a-item-tool", itemId: "a-item-tool", version: 3, sessionId: "s",
    turnId: "t-secret", status: "completed", revision: 2, sequence: 2, callId: "call-secret-1",
    toolName: "personal_assistant_manage_tool",
    output: JSON.stringify({ ok: true, action: "secret_request", status: "awaiting_user_attachment",
      purpose: "连接中转站需要 API 密钥", label: "中转站密钥", hint: "以 sk- 开头" }) },
];
function secretRequestMessages(): unknown[] {
  return [
    { id: "m-u1", timestamp: "2026-11-05T00:00:00Z", role: "user", content: "帮我配置中转站" },
    { id: "m-a1", timestamp: "2026-11-05T00:00:01Z", role: "assistant", turnId: "t-secret",
      status: "completed", content: "", turnItems: SECRET_REQUEST_TURN_ITEMS },
  ];
}
function secretRequestBanner(): Element | null {
  return document.querySelector('[data-testid="chat-composer-secret-request"]');
}
it("surfaces the newest secret_request receipt as a one-click composer banner", async () => {
  const { invoke } = await setup(true, {}, secretRequestMessages());
  await settle();
  const banner = secretRequestBanner();
  expect(banner).not.toBeNull();
  expect(banner!.textContent).toContain("助理请求隐私内容：连接中转站需要 API 密钥");
  expect(banner!.textContent).toContain("建议显示名：中转站密钥");
  // One click opens the same privacy dialog with the suggestion prefilled.
  const attach = [...document.querySelectorAll<HTMLButtonElement>("button")]
    .find(button => button.textContent?.trim() === "立即附加")!;
  await act(async () => attach.click());
  expect(document.querySelector<HTMLInputElement>('input[type="password"]')).not.toBeNull();
  expect(document.querySelector<HTMLInputElement>('input[aria-label="隐私附件显示名"]')!.value).toBe("中转站密钥");
  // Banner hides while the dialog is open; nothing was uploaded yet.
  expect(secretRequestBanner()).toBeNull();
  expect(invoke.mock.calls.some(([request]) => request.operation === "upload_attachment")).toBe(false);
});
it("keeps the banner hidden while a secret chip is staged in the tray", async () => {
  localStorage.setItem("vibelution.launcher-assistant.composer.v1:embedded:s", JSON.stringify({
    version: 1, sessionId: "s", surface: "embedded",
    snapshot: { draft: "", outstanding: null, acceptedTurnId: "", queuedAcceptance: null,
      attachments: [{ id: "sec-chip-1", artifactId: "sec_test123", filename: "隐私 · 中转站密钥",
        contentType: "application/octet-stream", sizeBytes: 0, kind: "secret" }] },
  }));
  await setup(true, {}, secretRequestMessages());
  await settle();
  expect(conversation.composerAttachments?.some(item => item.kind === "secret")).toBe(true);
  expect(secretRequestBanner()).toBeNull();
});
it("stays quiet after the operator dismisses the exact receipt", async () => {
  await setup(true, {}, secretRequestMessages());
  await settle();
  expect(secretRequestBanner()).not.toBeNull();
  const dismiss = [...document.querySelectorAll<HTMLButtonElement>("button")]
    .find(button => button.textContent?.trim() === "忽略")!;
  await act(async () => dismiss.click());
  expect(secretRequestBanner()).toBeNull();
  // Later detail readbacks re-resolve the same receipt; the keyed dismissal
  // keeps the banner quiet without re-asking.
  await settle(); await settle();
  expect(secretRequestBanner()).toBeNull();
});
