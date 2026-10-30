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
// Tests simulate the native assistant floating window (400×530 DIP), not the
// workbench main window, so the route starts in its collapsed pet stage.
const floatingWindowInnerWidth = 400;
const defaultInnerWidth = window.innerWidth;
afterEach(async () => {
  for (const root of roots.splice(0)) await act(async () => root.unmount());
  document.body.innerHTML = "";
  window.innerWidth = defaultInnerWidth;
  vi.unstubAllGlobals();
});
async function settle() { await act(async () => { await new Promise(resolve => setTimeout(resolve, 25)); }); }
async function setup(enabled: boolean) {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  vi.stubGlobal("fetch", vi.fn(() => { throw new Error("HTTP forbidden"); }));
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:preview"), revokeObjectURL: vi.fn() }));
  let fail = false;
  let failSend = false;
  const invoke = vi.fn(async (request: Record<string, unknown>) => {
    switch (request.operation) {
      case "status": return { assistant: { agentId: "a", directSessionId: "s", displayName: "助手" }, ...(enabled ? { attachmentVersion: 1 } : {}) };
      case "config": return { language: "zh" };
      case "detail": return { id: "s", agentId: "a", status: "ready", messages: [{ id: "m", role: "user", content: "", attachments: [{ artifactId: "user-image-1.png", filename: "old.png", kind: "user_image", contentType: "image/png", sizeBytes: 2, status: "ready", url: "/api/secret", imageUrl: "/api/secret", downloadUrl: "/api/secret" }] }] };
      case "approvals": return [];
      case "dispatches": return { dispatches: [] };
      case "setExpanded": return { expanded: request.expanded };
      case "readAttachment": return { contentType: "image/png", dataBase64: "AQI=" };
      case "uploadAttachment": if (fail) throw new Error("failure"); else return { artifactId: "user-image-2.png", filename: "new.png", contentType: "image/png", sizeBytes: 2, kind: "user_image", status: "ready" };
      case "send": if (failSend) throw new Error("lost acknowledgement"); return { accepted: true, turnId: "turn" };
      default: throw new Error("unexpected");
    }
  });
  vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
  window.innerWidth = floatingWindowInnerWidth;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const container = document.createElement("div"); document.body.append(container);
  const root = createRoot(container); roots.push(root);
  await act(async () => root.render(createElement(QueryClientProvider, { client }, createElement(LauncherAssistantRoute))));
  await settle(); await settle();
  await act(async () => container.querySelector<HTMLButtonElement>('button[aria-label="展开个人助理聊天"]')!.click());
  await settle(); await settle();
  await act(async () => conversation.onVisibleTimelineMessageIds?.(["m"]));
  await settle();
  return { invoke, setFailure(value: boolean) { fail = value; }, setSendFailure(value: boolean) { failSend = value; } };
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
  setSendFailure(true);
  await act(async () => conversation.onSubmit()); await settle(); await settle();
  expect(conversation.composerAttachments).toHaveLength(1);
  expect(conversation.composerAttachmentInputDisabled).toBe(true);
  const first = invoke.mock.calls.find(([request]) => request.operation === "send")?.[0];
  setSendFailure(false);
  await act(async () => conversation.onSubmit()); await settle(); await settle();
  const sends = invoke.mock.calls.filter(([request]) => request.operation === "send").map(([request]) => request);
  expect(sends).toHaveLength(2);
  expect(sends[1]).toEqual(first);
  expect(invoke.mock.calls.filter(([request]) => request.operation === "uploadAttachment")).toHaveLength(1);
  expect(conversation.composerAttachments).toHaveLength(0);
});
