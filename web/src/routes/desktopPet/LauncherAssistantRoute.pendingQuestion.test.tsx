// @vitest-environment happy-dom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ConversationViewProps } from "../../components/conversation/conversationViewTypes";
import type { SessionPendingQuestion, SessionReferenceAttachment } from "../../api/types";
import { LauncherAssistantEmbeddedRoute } from "./LauncherAssistantRoute";
import { loadLauncherComposer, saveLauncherComposer } from "./launcherAssistantComposerStorage";

vi.mock("./DesktopPetCharacter", () => ({ DesktopPetCharacter: () => null }));
vi.mock("../../i18n/useShellI18n", () => ({ useShellI18n: () => ({
  lang: "zh", t: (key: string) => key, statusLabel: (status: string) => status,
}) }));
// Only the transcript renderer is replaced with its public composer contract.
let conversation: ConversationViewProps | undefined;
vi.mock("../../components/conversation/LazyConversationView", () => ({
  LazyConversationView: (props: ConversationViewProps) => {
    conversation = props;
    return createElement("div", { "data-testid": "native-conversation" },
      props.composerPrecedingContent ?? null,
      createElement("textarea", { "aria-label": "聊天输入框", value: props.composerValue, hidden: props.composerHidden,
        disabled: props.composerDisabled, onChange: event => props.onComposerChange(event.currentTarget.value) }));
  },
}));

const STATUS = {
  assistant: { agentId: "a", directSessionId: "s", displayName: "助理" },
  operatorAssetsVersion: 1,
  attachmentVersion: 1,
  settings: { ok: true, displayName: "助理", modelId: "model-1",
    preferences: { characterId: "dafeiyu", showStatus: true, showTitles: true, showCompletion: true, idleMessage: "在的，随时吩咐。" } },
};
const QUESTION: SessionPendingQuestion = { id: "q-1", questionText: "要继续部署吗？", askedAt: "2026-05-22T10:00:00Z", turnId: "turn-9" };
const SECOND_QUESTION: SessionPendingQuestion = { ...QUESTION, id: "q-2", questionText: "下一项处理什么？" };
const REFERENCE: SessionReferenceAttachment = { referenceId: "reference-1", kind: "session", sessionId: "source-session", title: "普通聊天引用" };
function detailWith(options: Record<string, unknown> = {}) {
  return {
    id: "s", agentId: "a", status: "ready", messages: [], lastTurnTerminalTurnId: "turn-9",
    pendingQuestion: QUESTION, ...options,
  };
}

let root: Root | undefined;
let container: HTMLDivElement;
let invoke: ReturnType<typeof vi.fn>;
let client: QueryClient;
let fetchMock: ReturnType<typeof vi.fn>;
let sendHandler: (request: Record<string, unknown>) => unknown;
let activeSession: string;
let details: Map<string, Record<string, unknown>>;
afterEach(async () => {
  await act(async () => root?.unmount()); root = undefined;
  container?.remove(); conversation = undefined;
  client?.clear(); localStorage.clear();
  if (fetchMock) expect(fetchMock).not.toHaveBeenCalled();
  vi.unstubAllGlobals(); vi.restoreAllMocks();
});
async function settle() {
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)); });
}
async function renderEmbedded(detail: Record<string, unknown>) {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  fetchMock = vi.fn(() => { throw new Error("HTTP is forbidden in this window"); });
  vi.stubGlobal("fetch", fetchMock);
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:question-test");
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
  activeSession = "s";
  details = new Map([["s", detail]]);
  sendHandler = () => ({ accepted: true, turnId: "answer-turn" });
  invoke = vi.fn(async (request: Record<string, unknown>) => {
    switch (request.operation) {
      case "status": return { ...STATUS, assistant: { ...STATUS.assistant, directSessionId: activeSession } };
      case "config": return { language: "zh" };
      case "detail": return details.get(activeSession);
      case "approvals": return [];
      case "dispatches": return { dispatches: [] };
      case "operatorAsset": return { schemaVersion: 1, kind: request.kind, image: null, readability: "standard" };
      case "readAttachment": return { contentType: "image/png", dataBase64: "AQI=" };
      case "uploadAttachment": return { artifactId: "ordinary-attachment.png", filename: "ordinary.png", contentType: "image/png", sizeBytes: 2, kind: "user_image", status: "ready" };
      case "send": return sendHandler(request);
      default: throw new Error("unexpected_operation");
    }
  });
  vi.stubGlobal("vibelutionLauncherAssistant", { invoke });
  client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 30_000, gcTime: Infinity } } });
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
  await act(async () => root!.render(createElement(QueryClientProvider, { client }, createElement(LauncherAssistantEmbeddedRoute))));
  await settle(); await settle();
}

function card() { return container.querySelector<HTMLElement>("[data-launcher-assistant-pending-question]"); }
function answer() { return container.querySelector<HTMLTextAreaElement>('textarea[aria-label="回答此问题"]')!; }
function ordinary() { return container.querySelector<HTMLTextAreaElement>('textarea[aria-label="聊天输入框"]')!; }
function answerButton() { return card()!.querySelector<HTMLButtonElement>('button[type="submit"]')!; }
function sends() { return invoke.mock.calls.filter(([request]) => request.operation === "send").map(([request]) => request); }
async function typeAnswer(value: string) {
  const field = answer();
  expect(field, "the question must expose its own answer textarea").not.toBeNull();
  const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!;
  await act(async () => { setter.call(field, value); field.dispatchEvent(new Event("input", { bubbles: true })); });
}
async function submitAnswer() {
  await act(async () => answerButton().click());
  await settle(); await settle();
}
async function publishDetail(value: Record<string, unknown>, sessionId = activeSession) {
  details.set(sessionId, value);
  await act(async () => { client.setQueryData(["launcher-assistant", "detail", sessionId], value); });
  await settle();
}
async function switchSession(sessionId: string, detail: Record<string, unknown>) {
  details.set(sessionId, detail); activeSession = sessionId;
  await act(async () => { client.setQueryData(["launcher-assistant", "status"], { ...STATUS,
    assistant: { ...STATUS.assistant, directSessionId: sessionId } }); });
  await settle(); await settle();
}
function storeUnknownAnswer() {
  expect(saveLauncherComposer("s", "embedded", {
    draft: "普通聊天草稿", acceptedTurnId: "", queuedAcceptance: null,
    outstanding: { message: "先检查", requestId: "original.answer:1", draftSnapshot: "  先检查  ", preserveDraft: true, answerQuestion: QUESTION },
    questionDraft: { question: QUESTION, value: "  先检查  " },
  })).toBe(true);
}

describe("Launcher assistant question card integration", () => {
  it("renders a fresh question with an independent answer while keeping the ordinary composer mounted and hidden", async () => {
    await renderEmbedded(detailWith());
    expect(card()?.getAttribute("data-launcher-assistant-pending-question")).toBe("q-1");
    expect(card()?.textContent).toContain(QUESTION.questionText);
    const mountedOrdinary = ordinary();
    expect(mountedOrdinary.hidden).toBe(true);
    expect(answer()).not.toBe(mountedOrdinary);
    expect(document.activeElement).not.toBe(answer());
    await act(async () => conversation!.onComposerChange("保留普通草稿"));
    await typeAnswer("  独立回答  ");
    expect(answer().value).toBe("  独立回答  ");
    expect(ordinary()).toBe(mountedOrdinary);
    expect(ordinary().value).toBe("保留普通草稿");
    expect(loadLauncherComposer("s", "embedded")?.questionDraft).toEqual({ question: QUESTION, value: "  独立回答  " });
    expect(sends()).toHaveLength(0);
  });

  it("sends only the answer and restores the ordinary draft, uploaded attachments and references after ACK even with the old ready slot", async () => {
    await renderEmbedded(detailWith());
    const mountedOrdinary = ordinary();
    await act(async () => {
      conversation!.onComposerChange("  普通草稿  ");
      conversation!.onAddComposerAttachments!([new File([new Uint8Array([1, 2])], "ordinary.png", { type: "image/png" })]);
      conversation!.onAddComposerReference!(REFERENCE);
    });
    await act(async () => conversation!.onRetryComposerAttachment!(conversation!.composerAttachments![0].id));
    await settle();
    const keptAttachments = conversation!.composerAttachments!;
    expect(keptAttachments[0].uploadStatus).toBe("uploaded");
    await typeAnswer("  先检查再部署  "); await submitAnswer();
    expect(sends()).toHaveLength(1);
    expect(sends()[0]).toEqual({ operation: "send", message: "先检查再部署", requestId: expect.any(String) });
    expect(card()).toBeNull();
    expect(ordinary()).toBe(mountedOrdinary);
    expect(ordinary().hidden).toBe(false);
    expect(ordinary().value).toBe("  普通草稿  ");
    expect(conversation!.composerAttachments).toEqual(keptAttachments);
    expect(conversation!.composerReferences).toEqual([REFERENCE]);
    expect(loadLauncherComposer("s", "embedded")?.questionDraft).toBeNull();
    await publishDetail(detailWith());
    expect(card()).toBeNull();
  });

  it("keeps a definitively rejected answer editable and sends the correction with a new request ID", async () => {
    await renderEmbedded(detailWith());
    sendHandler = () => { throw new Error("ASSISTANT_REQUEST_INVALID"); };
    await typeAnswer("原回答"); await submitAnswer();
    const first = sends()[0];
    expect(first).toBeTruthy();
    expect(answer().disabled).toBe(false);
    expect(answer().value).toBe("原回答");
    expect(loadLauncherComposer("s", "embedded")?.outstanding).toBeNull();
    sendHandler = () => ({ accepted: true, turnId: "answer-turn" });
    await typeAnswer("修改后的回答"); await submitAnswer();
    expect(sends()).toHaveLength(2);
    expect(sends()[1].message).toBe("修改后的回答");
    expect(sends()[1].requestId).not.toBe(first.requestId);
    expect(card()).toBeNull();
  });

  it("keeps unknown outcomes locked with an accessible retry that replays the identical payload and request ID", async () => {
    await renderEmbedded(detailWith());
    sendHandler = () => { throw new Error("lost acknowledgement"); };
    await typeAnswer("  原回答  "); await submitAnswer();
    expect(answer().disabled).toBe(true);
    expect(answer().value).toBe("  原回答  ");
    expect(answerButton().disabled).toBe(false);
    expect(answerButton().textContent).toBe("重试");
    expect(card()?.textContent).toContain("lost acknowledgement");
    expect(ordinary().hidden).toBe(true);
    expect(loadLauncherComposer("s", "embedded")?.outstanding).toMatchObject({ requestId: sends()[0].requestId,
      preserveDraft: true, answerQuestion: QUESTION });
    sendHandler = () => ({ accepted: true, turnId: "answer-turn" });
    await submitAnswer();
    expect(sends()).toHaveLength(2);
    expect(sends()[1]).toEqual(sends()[0]);
    expect(card()).toBeNull();
    expect(ordinary().hidden).toBe(false);
  });

  it("keeps an unresolved submission pending and prevents its late ACK from clearing another session's answer", async () => {
    await renderEmbedded(detailWith());
    let release!: (value: unknown) => void;
    sendHandler = () => new Promise(resolve => { release = resolve; });
    await typeAnswer("s 的回答"); await submitAnswer();
    expect(sends()).toHaveLength(1);
    expect(answer().value).toBe("s 的回答");
    expect(answer().disabled).toBe(true);
    expect(answerButton().disabled).toBe(true);
    expect(answerButton().getAttribute("aria-busy")).toBe("true");
    expect(ordinary().hidden).toBe(true);
    expect(saveLauncherComposer("s-2", "embedded", { draft: "s2 普通草稿", outstanding: null,
      acceptedTurnId: "", queuedAcceptance: null, questionDraft: { question: SECOND_QUESTION, value: "s2 已存回答" } })).toBe(true);
    await switchSession("s-2", detailWith({ id: "s-2", pendingQuestion: SECOND_QUESTION }));
    expect(card()?.getAttribute("data-launcher-assistant-pending-question")).toBe("q-2");
    expect(answer().value).toBe("s2 已存回答");
    await act(async () => release({ accepted: true, turnId: "s-answer-turn" }));
    await settle();
    expect(answer().value).toBe("s2 已存回答");
    expect(ordinary().value).toBe("s2 普通草稿");
    expect(loadLauncherComposer("s-2", "embedded")?.questionDraft?.value).toBe("s2 已存回答");
    expect(sends()).toHaveLength(1);
  });

  it("keeps a newer answer flight pending when the prior answer's ACK arrives after exact queue readback in the same session", async () => {
    await renderEmbedded(detailWith());
    await act(async () => conversation!.onComposerChange("同会话普通草稿"));
    const mountedOrdinary = ordinary();
    const releases: Array<(value: unknown) => void> = [];
    sendHandler = () => new Promise(resolve => { releases.push(resolve); });
    await typeAnswer("第一题的回答"); await submitAnswer();
    const firstRequest = sends()[0];
    expect(releases).toHaveLength(1);
    expect(answerButton().getAttribute("aria-busy")).toBe("true");

    // Native admission is authoritative while the first RPC is still unresolved.
    await publishDetail(detailWith({ pendingQuestion: null, queuedTurns: [{ id: "queue-first", position: 1,
      status: "queued", content: firstRequest.message, clientSubmissionId: firstRequest.requestId }] }));
    expect(card()).toBeNull();
    expect(ordinary()).toBe(mountedOrdinary);
    expect(ordinary().hidden).toBe(false);
    expect(ordinary().value).toBe("同会话普通草稿");
    expect(loadLauncherComposer("s", "embedded")?.outstanding).toBeNull();

    // The completed queue has gone; a new terminal turn now owns question 2.
    const nextQuestion = { ...SECOND_QUESTION, turnId: "turn-10" };
    await publishDetail(detailWith({ pendingQuestion: nextQuestion, lastTurnTerminalTurnId: "turn-10", queuedTurns: [] }));
    expect(card()?.getAttribute("data-launcher-assistant-pending-question")).toBe("q-2");
    expect(answer().value).toBe("");
    await typeAnswer("第二题仍在发送的回答"); await submitAnswer();
    expect(releases).toHaveLength(2);
    const secondRequest = { ...sends()[1] };
    expect(secondRequest.requestId).not.toBe(firstRequest.requestId);
    expect(answer().disabled).toBe(true);
    expect(answerButton().disabled).toBe(true);

    // The retired first flight owns neither the new answer nor its pending flag.
    await act(async () => releases[0]({ accepted: true, turnId: "first-answer-turn" }));
    await settle();
    expect(card()?.getAttribute("data-launcher-assistant-pending-question")).toBe("q-2");
    expect(answer().value).toBe("第二题仍在发送的回答");
    expect(answer().disabled).toBe(true);
    expect(answerButton().disabled).toBe(true);
    expect(answerButton().getAttribute("aria-busy")).toBe("true");
    expect(ordinary().hidden).toBe(true);
    expect(sends()).toEqual([firstRequest, secondRequest]);
    expect(loadLauncherComposer("s", "embedded")).toMatchObject({
      outstanding: { requestId: secondRequest.requestId, message: "第二题仍在发送的回答", answerQuestion: nextQuestion },
      questionDraft: { question: nextQuestion, value: "第二题仍在发送的回答" },
    });

    await act(async () => releases[1]({ accepted: true, turnId: "second-answer-turn" }));
    await settle(); await settle();
    expect(card()).toBeNull();
    expect(ordinary()).toBe(mountedOrdinary);
    expect(ordinary().hidden).toBe(false);
    expect(ordinary().value).toBe("同会话普通草稿");
    expect(sends()).toHaveLength(2);
    expect(loadLauncherComposer("s", "embedded")).toMatchObject({ outstanding: null, questionDraft: null });
  });

  it.each(["empty slot", "earlier turn"])("restores unknown answer metadata and retries its original request with %s", async scene => {
    storeUnknownAnswer();
    await renderEmbedded(detailWith({ pendingQuestion: scene === "empty slot" ? null : { ...QUESTION, turnId: "turn-old" } }));
    expect(answer().value).toBe("  先检查  ");
    expect(answer().disabled).toBe(true);
    expect(answerButton().disabled).toBe(false);
    expect(ordinary().value).toBe("普通聊天草稿");
    expect(sends()).toHaveLength(0);
    await submitAnswer();
    expect(sends()).toEqual([{ operation: "send", message: "先检查", requestId: "original.answer:1" }]);
    expect(card()).toBeNull();
    expect(ordinary().hidden).toBe(false);
    expect(ordinary().value).toBe("普通聊天草稿");
  });

  it("retires a recovered answer from exact queued request readback without inventing transcript messages", async () => {
    storeUnknownAnswer();
    await renderEmbedded(detailWith({ pendingQuestion: null, queuedTurns: [{ id: "queue-1", position: 1,
      status: "queued", content: "先检查", clientSubmissionId: "original.answer:1" }] }));
    expect(card()).toBeNull();
    expect(ordinary().hidden).toBe(false);
    expect(ordinary().value).toBe("普通聊天草稿");
    expect(conversation!.messages).toEqual([]);
    expect(sends()).toHaveLength(0);
    expect(loadLauncherComposer("s", "embedded")).toMatchObject({ outstanding: null, questionDraft: null,
      queuedAcceptance: { id: "queue-1", clientSubmissionId: "original.answer:1", observed: true } });
  });

  it.each([
    ["busy", { status: "running" }],
    ["stale", { pendingQuestion: { ...QUESTION, turnId: "turn-old" } }],
    ["empty", { pendingQuestion: null }],
  ])("does not show a fresh card for a %s question slot", async (_label, options) => {
    await renderEmbedded(detailWith(options));
    expect(card()).toBeNull();
    expect(ordinary().hidden).toBe(false);
    expect(container.querySelector('[data-testid="native-conversation"]')).toBeTruthy();
  });

  it("does not leak an earlier answer into a new question or another session and restores each session's stored answer", async () => {
    await renderEmbedded(detailWith());
    await typeAnswer("q1 的旧回答");
    await publishDetail(detailWith({ pendingQuestion: SECOND_QUESTION }));
    expect(card()?.getAttribute("data-launcher-assistant-pending-question")).toBe("q-2");
    expect(answer().value).toBe("");
    await typeAnswer("s 的 q2 回答");
    await switchSession("s-2", detailWith({ id: "s-2", pendingQuestion: QUESTION }));
    expect(answer().value).toBe("");
    await typeAnswer("s2 的 q1 回答");
    await switchSession("s", detailWith({ pendingQuestion: SECOND_QUESTION }));
    expect(answer().value).toBe("s 的 q2 回答");
    await switchSession("s-2", detailWith({ id: "s-2", pendingQuestion: QUESTION }));
    expect(answer().value).toBe("s2 的 q1 回答");
    expect(sends()).toHaveLength(0);
  });
});
