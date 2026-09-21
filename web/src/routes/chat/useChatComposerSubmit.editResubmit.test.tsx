/** @vitest-environment happy-dom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { act, useEffect, useRef, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ConversationMessage, SessionDetail, SessionTurnItem } from "../../api/types";
import { queryKeys } from "../../api/queryKeys";
import type { TranslationKey } from "../../i18n/dictionary";
import type { ChatEditTarget } from "../chatComposerState";
import { createChatWorkspaceCache } from "../chatWorkspaceCache";
import type { ActiveTurnLayerState } from "../chatActiveTurnLayer";
import { mergeAssistantDeltaIntoActiveTurnLayer } from "../chatActiveTurnLayer";
import { mergeSessionDetailMessageWindow } from "../chatSessionState";
import { useChatComposerSubmitActions, useChatComposerTurnMutations } from "./useChatComposerSubmit";

const apiMocks = vi.hoisted(() => ({
  editResubmitSessionMessage: vi.fn(),
}));

vi.mock("../../api/chat", () => ({
  editResubmitSessionMessage: apiMocks.editResubmitSessionMessage,
  querySessions: vi.fn(),
  regenerateSessionMessage: vi.fn(),
  stopSessionTurn: vi.fn(),
  submitSessionGuidance: vi.fn(),
  submitSessionMessage: vi.fn(),
  switchSessionHead: vi.fn(),
  uploadSessionImageAttachment: vi.fn(),
}));
vi.mock("./chatSubmitTelemetry", () => ({ postSubmitTelemetry: vi.fn() }));
vi.mock("../../app/userActionTelemetry", () => ({
  startUserAction: () => ({ succeeded: vi.fn(), failed: vi.fn(), blocked: vi.fn() }),
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function message(id: string, role: "user" | "assistant", content: string, metadata?: Record<string, unknown>): ConversationMessage {
  return { id, role, content, ...(metadata ? { metadata } : {}) } as ConversationMessage;
}

function detail(messages: ConversationMessage[]): SessionDetail {
  return {
    id: "session-1", title: "Session", status: "running", taskSummary: "", lastActive: "", updatedAt: "",
    currentPhase: "running", defaultFileContext: "", previewTabs: [], activePreviewPath: "", changedFiles: [],
    readFiles: [], messages, stopRequested: false, stopRequestedAt: "", stopReason: "",
  } as SessionDetail;
}

function Harness({ queryClient }: { queryClient: QueryClient }) {
  const workspace = useRef(createChatWorkspaceCache(queryClient)).current;
  const [, redraw] = useState(0);
  const [drafts, setDrafts] = useState<Record<string, string>>({ "session-1": "编辑后的 U2" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [targets, setTargets] = useState<Record<string, ChatEditTarget>>({
    "session-1": { messageId: "u2", nodeId: "node-u2", original: "U2" },
  });
  const [layers, setLayers] = useState<Record<string, ActiveTurnLayerState>>({});
  useEffect(() => queryClient.getQueryCache().subscribe(() => redraw((value) => value + 1)), [queryClient]);
  const mutations = useChatComposerTurnMutations({
    queryClient, chatWorkspaceCache: workspace,
    t: ((key: TranslationKey) => String(key)) as (key: TranslationKey) => string,
    describeError: (error: unknown, fallback: string) => error instanceof Error ? error.message : fallback,
    syncSessionDetail: (nextDetail) => {
      queryClient.setQueryData(queryKeys.session("session-1"), (previous) =>
        mergeSessionDetailMessageWindow(previous as SessionDetail | undefined, nextDetail));
    }, setActiveTurnLayersBySession: setLayers,
    setSessionDrafts: setDrafts, setSessionComposerErrors: setErrors,
    setSessionImageAttachments: () => undefined, setSessionReferenceAttachments: () => undefined,
    setSessionEditTargets: setTargets,
  });
  const actions = useChatComposerSubmitActions({
    ...mutations, queryClient, lang: "zh",
    describeError: (error: unknown, fallback: string) => error instanceof Error ? error.message : fallback,
    setSessionDrafts: setDrafts, sessionFollowupQueues: {}, setSessionFollowupQueues: () => undefined,
    setSessionComposerErrors: setErrors, setSessionImageAttachments: () => undefined,
    setSessionReferenceAttachments: () => undefined, setSessionImageUploadPending: () => undefined,
    setSessionEditTargets: setTargets, imageUploadInFlightRef: useRef({}), activeSessionId: "session-1",
    activeDraftEffective: drafts["session-1"] ?? "", activeImageAttachments: [], activeReferenceAttachments: [],
    mentalModelEnabledForNextTurn: false, runtimeStatusEnabledForNextTurn: false,
    resolvedEditTarget: targets["session-1"] ?? null, activeEditTarget: targets["session-1"] ?? null,
    composerDisabled: false, sessionBusy: false, sessionStopping: false, activePhase: "ready",
    activeAgentImageInputUnsupported: false, activeImageInputModelId: "model-1", activeTurnId: "turn-old",
    detail: queryClient.getQueryData<SessionDetail>(queryKeys.session("session-1")),
    setMentalModelEnabledForNextTurn: () => undefined, setRuntimeStatusEnabledForNextTurn: () => undefined,
  });
  const current = queryClient.getQueryData<SessionDetail>(queryKeys.session("session-1"));
  return <div>
    <output data-testid="messages">{JSON.stringify((current?.messages ?? []).map(({ id, role, content }) => ({ id, role, content })))}</output>
    <output data-testid="draft">{drafts["session-1"] ?? ""}</output>
    <output data-testid="layer">{JSON.stringify(layers)}</output>
    <output data-testid="error">{errors["session-1"] ?? ""}</output>
    <button data-testid="submit" type="button" onClick={() => actions.handleSubmitTurn()}>submit</button>
    <button data-testid="second-draft" type="button" onClick={() => { setDrafts({ "session-1": "第二次编辑" }); }}>second</button>
    <button data-testid="submit-second" type="button" onClick={() => actions.handleSubmitTurn()}>submit-second</button>
    <button data-testid="seed-terminal-layer" type="button" onClick={() => {
      const layer = mergeAssistantDeltaIntoActiveTurnLayer(undefined, {
        type: "assistant_delta", sessionId: "session-1", turnId: "turn-new", ledgerSeq: 20,
        stage: "answering", updatedAt: "2026-01-01T00:00:00.000Z", done: true,
        turnItems: [{
          id: "answer:1", itemId: "answer", version: 3, sessionId: "session-1", turnId: "turn-new",
          type: "agent_message", phase: "final_answer", status: "completed", revision: 1, sequence: 1,
          terminal: true, text: "SSE 已完成", createdAt: "2026-01-01T00:00:00.000Z", updatedAt: "2026-01-01T00:00:00.000Z",
        } satisfies SessionTurnItem],
      });
      if (layer) setLayers({ "session-1": layer });
    }}>seed-terminal-layer</button>
    <button data-testid="seed-stream-layer" type="button" onClick={() => {
      const layer = mergeAssistantDeltaIntoActiveTurnLayer(undefined, {
        type: "assistant_delta", sessionId: "session-1", turnId: "turn-new", ledgerSeq: 20,
        stage: "answering", turnItems: [{
          id: "answer:1", itemId: "answer", version: 3, sessionId: "session-1", turnId: "turn-new",
          type: "agent_message", phase: "answering", status: "running", revision: 1, sequence: 1,
          terminal: false, text: "partial", createdAt: "2026-01-01T00:00:00.000Z", updatedAt: "2026-01-01T00:00:00.000Z",
        } satisfies SessionTurnItem], updatedAt: "2026-01-01T00:00:00.000Z", done: false,
      });
      if (layer) setLayers({ "session-1": layer });
    }}>seed-stream-layer</button>
  </div>;
}

function setup() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        structuralSharing: (oldData, newData) => mergeSessionDetailMessageWindow(
          oldData as SessionDetail | undefined,
          newData as SessionDetail,
        ),
      },
      mutations: { retry: false },
    },
  });
  queryClient.setQueryData(queryKeys.session("session-1"), detail([
    message("u1", "user", "U1"), message("a1", "assistant", "A1", { turnId: "turn-1" }),
    message("u2", "user", "U2"), message("a2", "assistant", "A2", { turnId: "turn-2" }),
  ]));
  const container = document.createElement("div"); document.body.appendChild(container);
  const root = createRoot(container);
  return { queryClient, container, root };
}

async function renderHarness(queryClient: QueryClient, root: Root) {
  await act(async () => { root.render(<QueryClientProvider client={queryClient}><Harness queryClient={queryClient} /></QueryClientProvider>); });
}

async function flushTurn() {
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
}

describe("useChatComposerSubmit edit-resubmit", () => {
  let current: ReturnType<typeof setup> | undefined;
  afterEach(async () => {
    if (current) await act(async () => { current?.root.unmount(); });
    current?.container.remove(); current = undefined; apiMocks.editResubmitSessionMessage.mockReset();
  });

  it("immediately shows edited U2 and hides the superseded assistant tail", async () => {
    current = setup(); const { queryClient, root, container } = current;
    apiMocks.editResubmitSessionMessage.mockReturnValue(new Promise(() => undefined)); await renderHarness(queryClient, root);
    await act(async () => { container.querySelector<HTMLButtonElement>("[data-testid=submit]")?.click(); });
    await flushTurn();
    expect(JSON.parse(container.querySelector("[data-testid=messages]")!.textContent!)).toEqual([
      { id: "u1", role: "user", content: "U1" }, { id: "a1", role: "assistant", content: "A1" },
      { id: "u2", role: "user", content: "编辑后的 U2" },
    ]);
  });

  it("restores the complete pre-edit timeline and keeps the draft when HTTP rejects before ack", async () => {
    current = setup(); const { queryClient, root, container } = current;
    let reject!: (reason?: unknown) => void;
    apiMocks.editResubmitSessionMessage.mockReturnValue(new Promise((_resolve, r) => { reject = r; })); await renderHarness(queryClient, root);
    await act(async () => { container.querySelector<HTMLButtonElement>("[data-testid=submit]")?.click(); });
    await flushTurn();
    await act(async () => { reject(new Error("failed")); await Promise.resolve(); });
    expect(queryClient.getQueryData<SessionDetail>(queryKeys.session("session-1"))?.messages?.map((m) => m.content)).toEqual(["U1", "A1", "U2", "A2"]);
    expect(container.querySelector("[data-testid=draft]")?.textContent).toBe("编辑后的 U2");
  });

  it("does not roll back or clear the active layer after SSE ack followed by HTTP failure", async () => {
    current = setup(); const { queryClient, root, container } = current;
    let reject!: (reason?: unknown) => void;
    apiMocks.editResubmitSessionMessage.mockReturnValue(new Promise((_resolve, r) => { reject = r; })); await renderHarness(queryClient, root);
    await act(async () => { container.querySelector<HTMLButtonElement>("[data-testid=submit]")?.click(); });
    const submissionId = (apiMocks.editResubmitSessionMessage.mock.calls[0]?.[1] as { clientSubmissionId: string }).clientSubmissionId;
    await act(async () => {
      queryClient.setQueryData(queryKeys.session("session-1"), detail([
        message("u1", "user", "U1"), message("a1", "assistant", "A1", { turnId: "turn-1" }),
        message("u2", "user", "编辑后的 U2", { clientSubmissionId: submissionId, turnId: "turn-new" }),
        message("a-new", "assistant", "新 A2", { turnId: "turn-new" }),
      ]));
    });
    await act(async () => { reject(new Error("late HTTP failure")); await Promise.resolve(); });
    expect(queryClient.getQueryData<SessionDetail>(queryKeys.session("session-1"))?.messages?.map((m) => m.content)).toEqual(["U1", "A1", "编辑后的 U2", "新 A2"]);
    expect(container.querySelector("[data-testid=layer]")?.textContent).not.toBe("{}");
  });

  it("does not let the first rejected request overwrite the second submission", async () => {
    current = setup(); const { queryClient, root, container } = current;
    const deferred: Array<{ reject: (reason?: unknown) => void }> = [];
    apiMocks.editResubmitSessionMessage.mockImplementation(() => new Promise((_resolve, reject) => { deferred.push({ reject }); })); await renderHarness(queryClient, root);
    await act(async () => { container.querySelector<HTMLButtonElement>("[data-testid=submit]")?.click(); });
    await act(async () => { container.querySelector<HTMLButtonElement>("[data-testid=second-draft]")?.click(); });
    await act(async () => { container.querySelector<HTMLButtonElement>("[data-testid=submit-second]")?.click(); });
    expect(deferred).toHaveLength(2);
    await act(async () => { deferred[0].reject(new Error("first failed")); await Promise.resolve(); });
    expect(queryClient.getQueryData<SessionDetail>(queryKeys.session("session-1"))?.messages?.at(-1)?.content).toBe("第二次编辑");
    expect(queryClient.getQueryData<SessionDetail>(queryKeys.session("session-1"))?.messages?.some((m) => m.content === "A2")).toBe(false);
  });

  it("does not let a late first success clear the second draft or active layer", async () => {
    current = setup(); const { queryClient, root, container } = current;
    const deferred: Array<{ resolve: (value: SessionDetail) => void; reject: (reason?: unknown) => void }> = [];
    apiMocks.editResubmitSessionMessage.mockImplementation(() => new Promise((resolve, reject) => {
      deferred.push({ resolve, reject });
    }));
    await renderHarness(queryClient, root);
    await act(async () => { container.querySelector<HTMLButtonElement>("[data-testid=submit]")?.click(); });
    await flushTurn();
    await act(async () => { container.querySelector<HTMLButtonElement>("[data-testid=second-draft]")?.click(); });
    await act(async () => { container.querySelector<HTMLButtonElement>("[data-testid=submit-second]")?.click(); });
    await flushTurn();
    expect(deferred).toHaveLength(2);
    await act(async () => {
      deferred[0].resolve(detail([
        message("u1", "user", "U1"), message("a1", "assistant", "A1", { turnId: "turn-1" }),
        message("u2", "user", "编辑后的 U2", { clientSubmissionId: "first" }),
        message("a-new", "assistant", "旧请求的新 A2", { turnId: "turn-first" }),
      ]));
      await Promise.resolve();
    });
    expect(container.querySelector("[data-testid=draft]")?.textContent).toBe("第二次编辑");
    expect(container.querySelector("[data-testid=layer]")?.textContent).not.toBe("{}");
  });

  it("keeps an already completed SSE layer when the HTTP success snapshot is still running", async () => {
    current = setup(); const { queryClient, root, container } = current;
    let resolve!: (value: SessionDetail) => void;
    apiMocks.editResubmitSessionMessage.mockReturnValue(new Promise((r) => { resolve = r; }));
    await renderHarness(queryClient, root);
    await act(async () => { container.querySelector<HTMLButtonElement>("[data-testid=submit]")?.click(); });
    await flushTurn();
    const submissionId = (apiMocks.editResubmitSessionMessage.mock.calls[0]?.[1] as { clientSubmissionId: string }).clientSubmissionId;
    await act(async () => {
      queryClient.setQueryData(queryKeys.session("session-1"), detail([
        message("u1", "user", "U1"), message("a1", "assistant", "A1", { turnId: "turn-1" }),
        message("u2", "user", "编辑后的 U2", { clientSubmissionId: submissionId, turnId: "turn-new" }),
        message("a-new", "assistant", "SSE 已完成", { turnId: "turn-new" }),
      ]));
      container.querySelector<HTMLButtonElement>("[data-testid=seed-terminal-layer]")?.click();
    });
    await flushTurn();
    await act(async () => {
      resolve(detail([
        message("u1", "user", "U1"), message("a1", "assistant", "A1", { turnId: "turn-1" }),
        message("u2", "user", "编辑后的 U2", { clientSubmissionId: submissionId, turnId: "turn-new" }),
      ]));
      await Promise.resolve();
    });
    const layer = JSON.parse(container.querySelector("[data-testid=layer]")!.textContent!)["session-1"];
    expect(layer.clientSubmissionId).toBeUndefined();
    expect(layer.status).toBe("completed");
    expect(layer.turnId).toBe("turn-new");
    expect(layer.turnItems[0]?.text).toBe("SSE 已完成");
  });

  it("matches a stream-created layer by accepted turn when the delta has no submission id", async () => {
    current = setup(); const { queryClient, root, container } = current;
    let resolve!: (value: SessionDetail) => void;
    apiMocks.editResubmitSessionMessage.mockReturnValue(new Promise((r) => { resolve = r; }));
    await renderHarness(queryClient, root);
    await act(async () => { container.querySelector<HTMLButtonElement>("[data-testid=submit]")?.click(); });
    await flushTurn();
    const submissionId = (apiMocks.editResubmitSessionMessage.mock.calls[0]?.[1] as { clientSubmissionId: string }).clientSubmissionId;
    await act(async () => {
      queryClient.setQueryData(queryKeys.session("session-1"), detail([
        message("u1", "user", "U1"), message("a1", "assistant", "A1", { turnId: "turn-1" }),
        message("u2", "user", "编辑后的 U2", { clientSubmissionId: submissionId, turnId: "turn-new" }),
      ]));
      container.querySelector<HTMLButtonElement>("[data-testid=seed-stream-layer]")?.click();
    });
    await flushTurn();
    await act(async () => {
      resolve(detail([
        message("u1", "user", "U1"), message("a1", "assistant", "A1", { turnId: "turn-1" }),
        message("u2", "user", "编辑后的 U2", { clientSubmissionId: submissionId, turnId: "turn-new" }),
      ]));
      await Promise.resolve();
    });
    const layer = JSON.parse(container.querySelector("[data-testid=layer]")!.textContent!)["session-1"];
    expect(layer.clientSubmissionId).toBeUndefined();
    expect(layer.turnId).toBe("turn-new");
    expect(layer.status).toBe("running");
    expect(layer.turnItems[0]?.text).toBe("partial");
  });
});
