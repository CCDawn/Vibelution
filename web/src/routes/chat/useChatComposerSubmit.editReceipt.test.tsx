/** @vitest-environment happy-dom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { act, useEffect, useRef, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { editResubmitSessionMessage, stopSessionTurn } from "../../api/chat";
import { queryKeys } from "../../api/queryKeys";
import type { ConversationMessage, SessionDetail, SessionTurnItem } from "../../api/types";
import type { TranslationKey } from "../../i18n/dictionary";
import { mergeAssistantDeltaIntoActiveTurnLayer, type ActiveTurnLayerState } from "../chatActiveTurnLayer";
import { mergeSessionDetailMessageWindow } from "../chatSessionState";
import { createChatWorkspaceCache } from "../chatWorkspaceCache";
import { fetchSessionDetailWindow, isStaleLedgerUpdate } from "./chatSessionDetailHelpers";
import { useChatComposerBridgeState } from "./useChatComposerBridgeState";
import { useChatComposerSubmitActions, useChatComposerTurnMutations } from "./useChatComposerSubmit";

vi.mock("../../api/chat", async (importOriginal) => ({
  ...await importOriginal<typeof import("../../api/chat")>(),
  editResubmitSessionMessage: vi.fn(),
  stopSessionTurn: vi.fn(),
}));
vi.mock("./chatSessionDetailHelpers", async (importOriginal) => ({
  ...await importOriginal<typeof import("./chatSessionDetailHelpers")>(),
  fetchSessionDetailWindow: vi.fn(),
}));
vi.mock("./chatSubmitTelemetry", () => ({ postSubmitTelemetry: vi.fn() }));
vi.mock("../../app/userActionTelemetry", () => ({
  startUserAction: () => ({ succeeded: vi.fn(), failed: vi.fn(), blocked: vi.fn() }),
}));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const sessionId = "session-1";
const translate = (key: TranslationKey) => String(key);
const describeError = (error: unknown, fallback: string) => error instanceof Error ? error.message : fallback;
let controls: {
  edit: (submissionId?: string) => void;
  stop: () => void;
  select: (id: string) => void;
  seedLayer: (terminal?: boolean, turnId?: string) => void;
  layers: Record<string, ActiveTurnLayerState>;
  errors: Record<string, string>;
  pending: boolean;
  actionMode: string;
};

function message(id: string, role: "user" | "assistant", content: string, metadata?: Record<string, unknown>): ConversationMessage {
  return { id, role, content, metadata } as ConversationMessage;
}
function detail(overrides: Partial<SessionDetail> = {}): SessionDetail {
  return {
    id: sessionId, title: "Session", status: "ready", taskSummary: "", lastActive: "", updatedAt: "",
    currentPhase: "ready", defaultFileContext: "", previewTabs: [], activePreviewPath: "", changedFiles: [],
    readFiles: [], messages: [message("u2", "user", "U2", { turnId: "turn-2", clientSubmissionId: "old-submission" }), message("a2", "assistant", "A2", { turnId: "turn-2" })],
    stopRequested: false, stopRequestedAt: "", stopReason: "", ledgerSeq: 1,
    lastTurnStatus: "completed", terminalReason: "success", ...overrides,
  } as SessionDetail;
}
function acceptedDetail(overrides: Partial<SessionDetail> = {}): SessionDetail {
  return detail({
    currentPhase: "running", status: "running", activeTurnId: "turn-new", ledgerSeq: 20,
    lastTurnStatus: "running", terminalReason: "",
    messages: [message("u2-new", "user", "U2", { clientSubmissionId: "edit-1", turnId: "turn-new" })],
    ...overrides,
  });
}
function answerItem(terminal: boolean, turnId = "turn-new"): SessionTurnItem {
  return {
    id: "answer:1", itemId: "answer", version: 3, sessionId, turnId, type: "agent_message",
    phase: terminal ? "final_answer" : "answering", status: terminal ? "completed" : "running",
    revision: 1, sequence: 1, terminal, text: terminal ? "SSE completed" : "partial",
    createdAt: "2026-01-01T00:00:00.000Z", updatedAt: "2026-01-01T00:00:00.000Z",
  };
}

function Harness({ queryClient }: { queryClient: QueryClient }) {
  const workspace = useRef(createChatWorkspaceCache(queryClient)).current;
  const [, redraw] = useState(0);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [selectedSession, setSelectedSession] = useState(sessionId);
  const [layers, setLayers] = useState<Record<string, ActiveTurnLayerState>>({});
  useEffect(() => queryClient.getQueryCache().subscribe(() => redraw((value) => value + 1)), [queryClient]);
  const mutations = useChatComposerTurnMutations({
    queryClient, chatWorkspaceCache: workspace, t: translate, describeError,
    syncSessionDetail: (incoming) => queryClient.setQueryData<SessionDetail>(queryKeys.session(incoming.id), (previous) =>
      isStaleLedgerUpdate(previous?.ledgerSeq, incoming.ledgerSeq)
        ? previous : mergeSessionDetailMessageWindow(previous, incoming)),
    setActiveTurnLayersBySession: setLayers, setSessionDrafts: setDrafts, setSessionComposerErrors: setErrors,
    setSessionImageAttachments: () => undefined, setSessionReferenceAttachments: () => undefined,
    setSessionEditTargets: () => undefined,
  });
  const currentDetail = queryClient.getQueryData<SessionDetail>(queryKeys.session(selectedSession));
  const bridge = useChatComposerBridgeState({
    activeSessionId: selectedSession, sessionDrafts: drafts, sessionFollowupQueues: {}, sessionComposerErrors: errors,
    sessionEditTargets: {}, sessionImageAttachments: {}, sessionReferenceAttachments: {}, sessionImageUploadPending: {},
    detail: currentDetail, agents: [], modelImageInputSupportById: new Map(), lang: "zh", t: translate,
    ...mutations,
  });
  const actions = useChatComposerSubmitActions({
    ...mutations, queryClient, lang: "zh", describeError, setSessionDrafts: setDrafts,
    sessionFollowupQueues: {}, setSessionFollowupQueues: () => undefined, setSessionComposerErrors: setErrors,
    setSessionImageAttachments: () => undefined, setSessionReferenceAttachments: () => undefined,
    setSessionImageUploadPending: () => undefined, setSessionEditTargets: () => undefined,
    imageUploadInFlightRef: useRef({}), activeSessionId: selectedSession,
    activeDraftEffective: "", activeImageAttachments: [], activeReferenceAttachments: [],
    mentalModelEnabledForNextTurn: false, runtimeStatusEnabledForNextTurn: false,
    resolvedEditTarget: null, activeEditTarget: null, composerDisabled: bridge.composerDisabled,
    sessionBusy: bridge.sessionBusy, sessionStopping: bridge.sessionStopping, activePhase: currentDetail?.currentPhase,
    activeAgentImageInputUnsupported: false, activeImageInputModelId: "model-1", activeTurnId: layers[selectedSession]?.turnId,
    detail: currentDetail, setMentalModelEnabledForNextTurn: () => undefined, setRuntimeStatusEnabledForNextTurn: () => undefined,
  });
  controls = {
    edit: (clientSubmissionId = "edit-1") => mutations.editResubmitMutation.mutate({
      sessionId: selectedSession, messageId: "u2", content: "edited", clientSubmissionId,
      mentalModelEnabled: false, runtimeStatusEnabled: false,
    }),
    stop: actions.handleStopTurn, select: setSelectedSession,
    seedLayer: (terminal = false, turnId = "turn-new") => {
      const layer = mergeAssistantDeltaIntoActiveTurnLayer(undefined, {
        type: "assistant_delta", sessionId, turnId, ledgerSeq: 20, stage: "answering", done: terminal,
        updatedAt: "2026-01-01T00:00:00.000Z", turnItems: [answerItem(terminal, turnId)],
      });
      if (layer) setLayers({ [sessionId]: layer });
    },
    layers, errors, pending: bridge.submitPending, actionMode: bridge.conversationComposer.actionMode,
  };
  return null;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
async function flush() { await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); }); }
async function step(action: () => void) { await act(async () => { action(); }); await flush(); }

describe("edit-resubmit receipt reconciliation", () => {
  let root: Root;
  let container: HTMLDivElement;
  let queryClient: QueryClient;
  beforeEach(async () => {
    vi.mocked(editResubmitSessionMessage).mockReset();
    vi.mocked(stopSessionTurn).mockReset().mockResolvedValue(detail({ currentPhase: "stopped", status: "stopped" }));
    vi.mocked(fetchSessionDetailWindow).mockReset().mockRejectedValue(new Error("readback unavailable"));
    queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    queryClient.setQueryData(queryKeys.session(sessionId), detail());
    queryClient.setQueryData(queryKeys.session("session-2"), detail({ id: "session-2" }));
    container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
    await act(async () => root.render(<QueryClientProvider client={queryClient}><Harness queryClient={queryClient} /></QueryClientProvider>));
  });
  afterEach(async () => { await act(async () => root.unmount()); container.remove(); queryClient.clear(); });
  function cache(next: SessionDetail) { queryClient.setQueryData(queryKeys.session(next.id), next); }


  it("edit transport failure should confirm the native acceptance before rollback", async () => {
    const request = deferred<SessionDetail>(); vi.mocked(editResubmitSessionMessage).mockReturnValue(request.promise);
    vi.mocked(fetchSessionDetailWindow).mockResolvedValue(acceptedDetail({ messages: [message("edited-u", "user", "edited", {clientSubmissionId:"edit-1",turnId:"turn-new"})] }));
    await step(() => controls.edit());
    await step(() => request.reject(new Error("lost edit receipt")));
    expect(fetchSessionDetailWindow).toHaveBeenCalledTimes(1);
    expect(controls.errors[sessionId] ?? "").toBe("");
    expect(queryClient.getQueryData<SessionDetail>(queryKeys.session(sessionId))?.messages.map((m) => m.content)).toEqual(["edited"]);
    expect(controls.layers[sessionId].turnId).toBe("turn-new");
  });
  it("edit SSE acceptance should preserve the pending Stop when HTTP fails", async () => {
    const request = deferred<SessionDetail>(); vi.mocked(editResubmitSessionMessage).mockReturnValue(request.promise);
    await step(() => controls.edit()); await step(() => controls.stop()); await step(() => controls.select("session-2"));
    await step(() => cache(acceptedDetail({messages:[message("edited-u", "user", "edited", {clientSubmissionId:"edit-1",turnId:"turn-new"})]})));
    await step(() => request.reject(new Error("lost edit receipt")));
    expect(stopSessionTurn).toHaveBeenCalledExactlyOnceWith(sessionId,"turn-new");
  });
  it("edit deferred Stop must not use another active turn from a late receipt", async () => {
    const request = deferred<SessionDetail>(); vi.mocked(editResubmitSessionMessage).mockReturnValue(request.promise);
    await step(() => controls.edit()); await step(() => controls.stop()); await step(() => controls.select("session-2"));
    const receipt=acceptedDetail({activeTurnId:"turn-other",messages:[message("edited-u", "user", "edited", {clientSubmissionId:"edit-1",turnId:"turn-new"}),message("another-u","user","another turn",{clientSubmissionId:"other-id",turnId:"turn-other"})]});
    await step(() => request.resolve(receipt));
    expect(stopSessionTurn).not.toHaveBeenCalled();
  });

  it.each(["success", "error"])("stops the exact edited turn after a cross-session %s receipt", async (transport) => {
    const request = deferred<SessionDetail>();
    vi.mocked(editResubmitSessionMessage).mockReturnValue(request.promise);
    await step(() => controls.edit());
    await step(() => controls.stop());
    await step(() => controls.select("session-2"));
    if (transport === "error") vi.mocked(fetchSessionDetailWindow).mockResolvedValue(acceptedDetail());
    await step(() => transport === "success" ? request.resolve(acceptedDetail()) : request.reject(new Error("receipt lost")));
    expect(stopSessionTurn).toHaveBeenCalledExactlyOnceWith(sessionId, "turn-new");
    expect(controls.errors[sessionId] ?? "").toBe("");
  });

  it("keeps a background edit Stop when another edit owns the mutation observer", async () => {
    const first = deferred<SessionDetail>();
    const second = deferred<SessionDetail>();
    vi.mocked(editResubmitSessionMessage).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    await step(() => controls.edit());
    await step(() => controls.stop());
    await step(() => controls.select("session-2"));
    await step(() => controls.edit("edit-b"));
    await step(() => first.resolve(acceptedDetail()));
    expect(stopSessionTurn).toHaveBeenCalledExactlyOnceWith(sessionId, "turn-new");
    expect(controls.layers["session-2"].clientSubmissionId).toBe("edit-b");
    await step(() => second.resolve(acceptedDetail({ id: "session-2", activeTurnId: "turn-b", messages: [
      message("u-b", "user", "edited", { clientSubmissionId: "edit-b", turnId: "turn-b" }),
    ] })));
    expect(stopSessionTurn).toHaveBeenCalledTimes(1);
  });

  it.each(["success", "error"].flatMap((transport) =>
    ["terminal", "another-turn", "queued", "wrong-session"].map((kind) => ({ transport, kind })),
  ))("does not stop $kind after a $transport receipt", async ({ transport, kind }) => {
    const request = deferred<SessionDetail>();
    vi.mocked(editResubmitSessionMessage).mockReturnValue(request.promise);
    await step(() => controls.edit());
    await step(() => controls.stop());
    await step(() => controls.select("session-2"));
    const receipt = acceptedDetail();
    if (kind === "terminal") {
      receipt.currentPhase = "completed"; receipt.status = "completed"; receipt.activeTurnId = "";
    }
    if (kind === "another-turn") await step(() => cache(acceptedDetail({ ledgerSeq: 21, activeTurnId: "turn-other", messages: [
      ...receipt.messages, message("other-u", "user", "another turn", { clientSubmissionId: "other-id", turnId: "turn-other" }),
    ] })));
    if (kind === "queued") {
      receipt.activeTurnId = "turn-other";
      receipt.messages = [message("other-u", "user", "another turn", { turnId: "turn-other" })];
      receipt.queuedTurns = [{ id: "queue-1", clientSubmissionId: "edit-1", status: "queued" }] as SessionDetail["queuedTurns"];
    }
    if (kind === "wrong-session") receipt.id = "session-2";
    if (transport === "error") vi.mocked(fetchSessionDetailWindow).mockResolvedValue(receipt);
    await step(() => transport === "success" ? request.resolve(receipt) : request.reject(new Error("receipt lost")));
    expect(stopSessionTurn).not.toHaveBeenCalled();
    expect(controls.layers[sessionId]).toBeUndefined();
    expect(queryClient.getQueryData<SessionDetail>(queryKeys.session(sessionId))?.stopRequested).toBe(false);
  });

  it.each([false, true])("preserves streamed output on error recovery (terminal=%s)", async (terminal) => {
    const request = deferred<SessionDetail>();
    vi.mocked(editResubmitSessionMessage).mockReturnValue(request.promise);
    await step(() => controls.edit());
    await step(() => { cache(acceptedDetail()); controls.seedLayer(terminal); });
    const painted = controls.layers[sessionId];
    await step(() => request.reject(new Error("receipt lost")));
    expect(fetchSessionDetailWindow).not.toHaveBeenCalled();
    expect(controls.layers[sessionId]).toBe(painted);
    expect(controls.errors[sessionId] ?? "").toBe("");
  });

  it("accepts SSE confirmation arriving while a failed readback is pending", async () => {
    const request = deferred<SessionDetail>();
    const readback = deferred<SessionDetail>();
    vi.mocked(editResubmitSessionMessage).mockReturnValue(request.promise);
    vi.mocked(fetchSessionDetailWindow).mockReturnValue(readback.promise);
    await step(() => controls.edit());
    await step(() => controls.stop());
    await step(() => controls.select("session-2"));
    await step(() => request.reject(new Error("receipt lost")));
    expect(fetchSessionDetailWindow).toHaveBeenCalledTimes(1);
    await step(() => cache(acceptedDetail()));
    await step(() => readback.reject(new Error("readback lost")));
    expect(stopSessionTurn).toHaveBeenCalledExactlyOnceWith(sessionId, "turn-new");
    expect(controls.errors[sessionId] ?? "").toBe("");
  });

  it("a newer edit remains intact when an earlier error readback finishes", async () => {
    const first = deferred<SessionDetail>();
    const second = deferred<SessionDetail>();
    const readback = deferred<SessionDetail>();
    vi.mocked(editResubmitSessionMessage).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    vi.mocked(fetchSessionDetailWindow).mockReturnValue(readback.promise);
    await step(() => controls.edit());
    await step(() => first.reject(new Error("first receipt lost")));
    await step(() => controls.edit("edit-2"));
    const newer = acceptedDetail({ ledgerSeq: 30, activeTurnId: "turn-later", messages: [
      message("later-u", "user", "new edit", { clientSubmissionId: "edit-2", turnId: "turn-later" }),
    ] });
    await step(() => { cache(newer); controls.seedLayer(false, "turn-later"); });
    const painted = controls.layers[sessionId];
    await step(() => readback.resolve(acceptedDetail()));
    expect(controls.layers[sessionId]).toBe(painted);
    expect(controls.errors[sessionId] ?? "").toBe("");
    expect(queryClient.getQueryData<SessionDetail>(queryKeys.session(sessionId))?.ledgerSeq).toBe(30);
    await step(() => second.resolve(newer));
  });

  it.each(["not-found", "failed"])("rolls back a genuinely unaccepted edit after %s readback", async (kind) => {
    const request = deferred<SessionDetail>();
    vi.mocked(editResubmitSessionMessage).mockReturnValue(request.promise);
    if (kind === "not-found") vi.mocked(fetchSessionDetailWindow).mockResolvedValue(detail());
    await step(() => controls.edit());
    await step(() => request.reject(new Error("edit rejected")));
    expect(controls.errors[sessionId]).toBe("edit rejected");
    expect(controls.layers[sessionId]).toBeUndefined();
    expect(queryClient.getQueryData<SessionDetail>(queryKeys.session(sessionId))?.messages.map((m) => m.content)).toEqual(["U2", "A2"]);
  });
});
