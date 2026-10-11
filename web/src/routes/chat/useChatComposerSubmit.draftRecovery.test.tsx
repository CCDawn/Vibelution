// @vitest-environment happy-dom
import React, { act, useMemo, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { onlineManager, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { queryKeys } from "../../api/queryKeys";
import type { SessionDetail, SessionTurnAcceptedResponse } from "../../api/types";
import { stopSessionTurn, submitSessionMessage, uploadSessionImageAttachment } from "../../api/chat";
import { createOptimisticActiveTurnLayer, type ActiveTurnLayerState } from "../chatActiveTurnLayer";
import { createActiveTurnLayersStore } from "./activeTurnLayersStore";
import { createChatWorkspaceCache } from "../chatWorkspaceCache";
import { useChatComposerSubmitActions, useChatComposerTurnMutations } from "./useChatComposerSubmit";
import { fetchSessionDetailWindow } from "./chatSessionDetailHelpers";
import type { ComposerImageAttachment } from "./chatComposerSubmitModel";
import { flushPendingSessionDraftWrites, readStoredSessionDrafts, resetChatDraftPersistenceForTests } from "./chatDraftPersistence";

vi.mock("../../api/chat", async (importOriginal) => ({
  ...await importOriginal<typeof import("../../api/chat")>(),
  submitSessionMessage: vi.fn(),
  stopSessionTurn: vi.fn(),
  uploadSessionImageAttachment: vi.fn(),
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
const sid = "draft-recovery-session";
const secondSid = "draft-recovery-session-b";
const rebasedSid = "draft-recovery-session-created";
const originalDraft = "发送失败后仍需要保留的文字";
let controls: {
  change: (value: string) => void;
  submit: () => void;
  stop: () => void;
  cancelEdit: () => void;
  switchSession: (sessionId: string) => void;
  draft: string;
  error: string;
  activeTurnLayer?: ActiveTurnLayerState;
  setActiveTurnLayer: (layer: ActiveTurnLayerState | undefined) => void;
  rebaseSession: (fromSessionId: string, toSessionId: string) => void;
  deferDraftUpdates: () => void;
  replayDeferredDraftUpdates: () => void;
};
const roots: Root[] = [];
const clients: QueryClient[] = [];

function acceptedReceipt(sessionId: string, clientSubmissionId: string, turnId: string): SessionTurnAcceptedResponse {
  return {
    accepted: true,
    sessionId,
    clientSubmissionId,
    turnId,
    status: "accepted",
    acceptedAt: "2026-10-12T00:00:00.000Z",
  };
}

function terminalDetail(sessionId: string, clientSubmissionId: string, turnId: string): SessionDetail {
  return {
    id: sessionId,
    status: "completed",
    currentPhase: "completed",
    activeTurnId: "",
    ledgerSeq: 22,
    messages: [
      {
        id: "canonical-user",
        role: "user",
        content: "accepted prompt",
        timestamp: "2026-10-12T00:00:01.000Z",
        metadata: { clientSubmissionId, turnId },
      },
      {
        id: "canonical-assistant",
        role: "assistant",
        content: "done",
        turnId,
        status: "completed",
        timestamp: "2026-10-12T00:00:02.000Z",
        turnItems: [{
          id: "final-answer",
          itemId: "final-answer",
          version: 3,
          sessionId,
          turnId,
          type: "agent_message",
          phase: "final_answer",
          status: "completed",
          revision: 1,
          sequence: 1,
          terminal: true,
          text: "done",
        }],
      },
    ],
  } as SessionDetail;
}

async function unmountLatest() {
  const root = roots.pop();
  if (root) await act(async () => root.unmount());
}

async function flushMutationMicrotasks() {
  await act(async () => {
    for (let index = 0; index < 12; index += 1) await Promise.resolve();
  });
}

function Harness({
  client,
  attachments,
  initialDraft = originalDraft,
}: {
  client: QueryClient;
  attachments: ComposerImageAttachment[];
  initialDraft?: string;
}) {
  const [activeSessionId, setActiveSessionId] = useState(sid);
  const [drafts, setDraftsState] = useState<Record<string, string>>({ [sid]: initialDraft, [secondSid]: "" });
  const deferredDraftUpdatesRef = useRef<Array<(current: Record<string, string>) => Record<string, string>> | null>(null);
  const setDrafts: Dispatch<SetStateAction<Record<string, string>>> = (action) => {
    if (typeof action === "function" && deferredDraftUpdatesRef.current) {
      deferredDraftUpdatesRef.current.push(action as (current: Record<string, string>) => Record<string, string>);
      return;
    }
    setDraftsState(action);
  };
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [images, setImages] = useState<Record<string, ComposerImageAttachment[]>>({ [sid]: attachments });
  const activeTurnLayersStore = useMemo(() => createActiveTurnLayersStore(), []);
  const uploadInFlight = useRef<Record<string, boolean>>({});
  const activeDetail = client.getQueryData<SessionDetail>(queryKeys.session(activeSessionId));
  const mutations = useChatComposerTurnMutations({
    queryClient: client,
    chatWorkspaceCache: createChatWorkspaceCache(client),
    activeSessionId,
    activeTurnLayersStore,
    t: ((key: string) => key) as never,
    describeError: (error, fallback) => error instanceof Error ? error.message : fallback,
    syncSessionDetail: (incoming) => client.setQueryData(queryKeys.session(incoming.id), incoming),
    setActiveTurnLayersBySession: activeTurnLayersStore.setActiveTurnLayersBySession,
    setSessionDrafts: setDrafts,
    setSessionComposerErrors: setErrors,
    setSessionImageAttachments: setImages,
    setSessionReferenceAttachments: () => undefined,
    setSessionEditTargets: () => undefined,
  });
  const actions = useChatComposerSubmitActions({
    ...mutations, queryClient: client, lang: "zh",
    describeError: (error, fallback) => error instanceof Error ? error.message : fallback,
    setSessionDrafts: setDrafts, setSessionComposerErrors: setErrors,
    setSessionImageAttachments: setImages, setSessionReferenceAttachments: () => undefined,
    setSessionImageUploadPending: () => undefined, setSessionEditTargets: () => undefined,
    sessionFollowupQueues: {}, imageUploadInFlightRef: uploadInFlight,
    activeSessionId, activeDraftEffective: drafts[activeSessionId] ?? "",
    activeImageAttachments: images[activeSessionId] ?? [], activeReferenceAttachments: [],
    mentalModelEnabledForNextTurn: false, runtimeStatusEnabledForNextTurn: false,
    turnModelSelection: null, resolvedEditTarget: null, activeEditTarget: null,
    composerDisabled: false, sessionBusy: false, sessionStopping: false, activePhase: "ready",
    activeAgentImageInputUnsupported: false, activeImageInputModelId: "model-1",
    latestUserMessageId: "", activeTurnId: activeTurnLayersStore.getSnapshot()[activeSessionId]?.turnId, detail: activeDetail,
    setMentalModelEnabledForNextTurn: () => undefined, setRuntimeStatusEnabledForNextTurn: () => undefined,
  });
  controls = {
    change: actions.handleComposerChange,
    submit: actions.handleSubmitTurn,
    stop: actions.handleStopTurn,
    cancelEdit: actions.handleCancelEditMessage,
    switchSession: setActiveSessionId,
    draft: drafts[activeSessionId] ?? "",
    error: errors[activeSessionId] ?? "",
    get activeTurnLayer() { return activeTurnLayersStore.getSnapshot()[activeSessionId]; },
    setActiveTurnLayer: (layer) => activeTurnLayersStore.setActiveTurnLayersBySession((current) => {
      if (!layer) {
        const { [activeSessionId]: _removed, ...remaining } = current;
        return remaining;
      }
      return { ...current, [activeSessionId]: layer };
    }),
    rebaseSession: (fromSessionId, toSessionId) => {
      actions.rebaseComposerPreviewOwners(fromSessionId, toSessionId);
      setDraftsState((current) => {
        const { [fromSessionId]: draft, ...remaining } = current;
        return Object.hasOwn(current, fromSessionId) && !Object.hasOwn(remaining, toSessionId)
          ? { ...remaining, [toSessionId]: draft }
          : remaining;
      });
      setImages((current) => {
        const { [fromSessionId]: sessionImages, ...remaining } = current;
        return Object.hasOwn(current, fromSessionId) && !Object.hasOwn(remaining, toSessionId)
          ? { ...remaining, [toSessionId]: sessionImages }
          : remaining;
      });
      setActiveSessionId(toSessionId);
    },
    deferDraftUpdates: () => { deferredDraftUpdatesRef.current = []; },
    replayDeferredDraftUpdates: () => {
      const updates = deferredDraftUpdatesRef.current ?? [];
      deferredDraftUpdatesRef.current = null;
      setDraftsState((current) => updates.reduce((next, update) => update(next), current));
    },
  };
  return null;
}

function mount(attachments: ComposerImageAttachment[] = [], options: { initialDraft?: string; persistInitialDraft?: boolean } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  clients.push(client);
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  roots.push(root);
  act(() => root.render(<QueryClientProvider client={client}><Harness client={client} attachments={attachments} initialDraft={options.initialDraft} /></QueryClientProvider>));
  if (options.persistInitialDraft !== false) act(() => controls.change(options.initialDraft ?? originalDraft));
  flushPendingSessionDraftWrites();
  if (options.persistInitialDraft !== false) expect(readStoredSessionDrafts()[sid]).toBe(options.initialDraft ?? originalDraft);
  return client;
}

async function settle() {
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 10)); });
}

beforeEach(() => {
  localStorage.clear();
  resetChatDraftPersistenceForTests();
  vi.mocked(submitSessionMessage).mockReset().mockRejectedValue(new Error("network disconnected"));
  vi.mocked(stopSessionTurn).mockReset().mockResolvedValue({} as SessionDetail);
  vi.mocked(uploadSessionImageAttachment).mockReset().mockRejectedValue(new Error("upload rejected"));
  vi.mocked(fetchSessionDetailWindow).mockReset().mockRejectedValue(new Error("readback unavailable"));
});
afterEach(() => {
  roots.splice(0).forEach((root) => act(() => root.unmount()));
  clients.splice(0).forEach((client) => client.clear());
  resetChatDraftPersistenceForTests();
  document.body.replaceChildren();
  onlineManager.setOnline(true);
  vi.useRealTimers();
});

describe("failed composer draft recovery", () => {
  it("attempts an offline submission and recovers instead of silently pausing until reconnect", async () => {
    mount();
    onlineManager.setOnline(false);
    await act(async () => controls.submit());
    await settle();
    expect(submitSessionMessage).toHaveBeenCalledTimes(1);
    expect(controls.error).not.toBe("");
    expect(controls.draft).toBe(originalDraft);
    flushPendingSessionDraftWrites();
    expect(readStoredSessionDrafts()[sid]).toBe(originalDraft);
    act(() => controls.change("离线失败后用户改写的新内容"));
    onlineManager.setOnline(true);
    await settle();
    expect(submitSessionMessage).toHaveBeenCalledTimes(1);
    expect(controls.draft).toBe("离线失败后用户改写的新内容");
  });

  it.each(["message", "attachment"])("persists the recovered text after %s failure", async (kind) => {
    const attachments: ComposerImageAttachment[] = kind === "attachment" ? [{
      id: "image-1", file: new File(["bytes"], "test.png", { type: "image/png" }),
      filename: "test.png", previewUrl: "blob:test", sizeBytes: 5, contentType: "image/png", kind: "image",
    }] : [];
    mount(attachments);
    await act(async () => controls.submit());
    await settle();
    expect(controls.error).not.toBe("");
    expect(controls.draft).toBe(originalDraft);
    flushPendingSessionDraftWrites();
    expect(readStoredSessionDrafts()[sid]).toBe(originalDraft);
    if (kind === "attachment") expect(submitSessionMessage).not.toHaveBeenCalled();
  });

  it("keeps newer input when an older message request fails", async () => {
    let rejectRequest!: (error: Error) => void;
    vi.mocked(submitSessionMessage).mockImplementation(() => new Promise((_, reject) => { rejectRequest = reject; }));
    mount();
    await act(async () => controls.submit());
    await settle();
    act(() => controls.change("用户在等待时输入的新草稿"));
    await act(async () => rejectRequest(new Error("late failure")));
    await settle();
    flushPendingSessionDraftWrites();
    expect(controls.draft).toBe("用户在等待时输入的新草稿");
    expect(readStoredSessionDrafts()[sid]).toBe("用户在等待时输入的新草稿");
  });

  it.each(["failed readback", "stale readback"] as const)(
    "keeps an SSE-confirmed submission after a %s",
    async (readbackOutcome) => {
      let resolveReadback!: (detail: SessionDetail) => void;
      let rejectReadback!: (error: Error) => void;
      vi.mocked(fetchSessionDetailWindow).mockReturnValue(new Promise<SessionDetail>((resolve, reject) => {
        resolveReadback = resolve;
        rejectReadback = reject;
      }));
      const client = mount();
      await act(async () => controls.submit());
      await settle();

      expect(fetchSessionDetailWindow).toHaveBeenCalledTimes(1);
      const submissionId = vi.mocked(submitSessionMessage).mock.calls[0]?.[1].clientSubmissionId;
      expect(submissionId).toBeTruthy();

      // Simulate the authoritative SSE detail arriving while the readback is
      // still pending. Recovery must inspect this newest cache before putting
      // the submitted text back into the composer.
      act(() => client.setQueryData<SessionDetail>(queryKeys.session(sid), {
        id: sid,
        ledgerSeq: 20,
        messages: [{
          id: "canonical-user-message",
          role: "user",
          content: originalDraft,
          timestamp: new Date().toISOString(),
          metadata: { clientSubmissionId: submissionId },
        }],
      } as SessionDetail));

      await act(async () => {
        if (readbackOutcome === "failed readback") {
          rejectReadback(new Error("readback unavailable"));
        } else {
          resolveReadback({ id: sid, ledgerSeq: 19, messages: [] } as SessionDetail);
        }
        await Promise.resolve();
      });
      await settle();
      expect(controls.draft).toBe("");
      expect(controls.error).toBe("");
      expect(client.getQueryData<SessionDetail>(queryKeys.session(sid))).toMatchObject({
        ledgerSeq: 20,
        messages: [expect.objectContaining({ metadata: { clientSubmissionId: submissionId } })],
      });
    },
  );

  it.each(["cache", "readback"] as const)(
    "settles a fast completed canonical turn confirmed by %s after the POST reports an error",
    async (confirmationSource) => {
      let client!: QueryClient;
      let readbackDetail: SessionDetail | undefined;
      vi.mocked(submitSessionMessage).mockImplementation(async (sessionId, payload) => {
        const turnId = "canonical-turn";
        const detail = {
          id: sessionId,
          ledgerSeq: 21,
          messages: [
            {
              id: "canonical-user-message",
              role: "user",
              content: payload.content,
              timestamp: new Date().toISOString(),
              metadata: { clientSubmissionId: payload.clientSubmissionId, turnId },
            },
            {
              id: "canonical-assistant-message",
              role: "assistant",
              turnId,
              status: "completed",
              timestamp: new Date().toISOString(),
              turnItems: [{
                id: "final-answer-1",
                itemId: "final-answer-1",
                version: 3,
                sessionId,
                turnId,
                status: "completed",
                revision: 1,
                sequence: 1,
                terminal: true,
                type: "agent_message",
                phase: "final_answer",
                text: "回答已完成",
              }],
            },
          ],
        } as SessionDetail;
        if (confirmationSource === "cache") {
          client.setQueryData(queryKeys.session(sessionId), detail);
        } else {
          readbackDetail = detail;
        }
        throw new Error("POST response lost after commit");
      });
      if (confirmationSource === "readback") {
        vi.mocked(fetchSessionDetailWindow).mockImplementation(async () => readbackDetail!);
      }
      client = mount();

      await act(async () => controls.submit());
      await settle();

      expect(fetchSessionDetailWindow).toHaveBeenCalledTimes(confirmationSource === "cache" ? 0 : 1);
      expect(controls.draft).toBe("");
      expect(controls.error).toBe("");
      expect(controls.activeTurnLayer).toBeUndefined();
    },
  );

  it("dispatches a recovered stop to session A's exact running turn after session B replaces observer variables", async () => {
    let rejectSessionA!: (error: Error) => void;
    vi.mocked(submitSessionMessage).mockImplementation((sessionId, payload) => {
      if (sessionId === sid) {
        return new Promise((_, reject) => { rejectSessionA = reject; });
      }
      return Promise.resolve({
        accepted: true,
        sessionId,
        turnId: "session-b-turn",
        clientSubmissionId: payload.clientSubmissionId,
        status: "running",
        acceptedAt: new Date().toISOString(),
      });
    });
    const recoveredDetail = {
      id: sid,
      ledgerSeq: 12,
      status: "running",
      currentPhase: "running",
      activeTurnId: "session-a-recovered-turn",
      messages: [{
        id: "session-a-canonical-user",
        role: "user",
        content: originalDraft,
        timestamp: new Date().toISOString(),
        metadata: {
          clientSubmissionId: "submission-session-a",
          turnId: "session-a-recovered-turn",
        },
      }],
    } as SessionDetail;
    vi.mocked(fetchSessionDetailWindow).mockImplementation(async (sessionId) => {
      expect(sessionId).toBe(sid);
      return recoveredDetail;
    });
    const client = mount();
    client.setQueryData<SessionDetail>(queryKeys.session(sid), {
      id: sid,
      status: "ready",
      currentPhase: "ready",
      messages: [],
    } as SessionDetail);

    await act(async () => controls.submit());
    await settle();
    const submissionId = vi.mocked(submitSessionMessage).mock.calls[0]?.[1].clientSubmissionId;
    expect(submissionId).toBeTruthy();
    recoveredDetail.messages[0]!.metadata!.clientSubmissionId = submissionId;

    await act(async () => controls.stop());
    expect(client.getQueryData<SessionDetail>(queryKeys.session(sid))?.stopRequested).toBe(true);
    await act(async () => controls.switchSession(secondSid));
    act(() => controls.change("session B 的新消息"));
    await act(async () => controls.submit());
    await settle();
    expect(submitSessionMessage).toHaveBeenCalledTimes(2);

    await act(async () => {
      rejectSessionA(new Error("POST response lost after commit"));
      await Promise.resolve();
    });
    await settle();

    expect(fetchSessionDetailWindow).toHaveBeenCalledTimes(1);
    expect(stopSessionTurn).toHaveBeenCalledTimes(1);
    expect(stopSessionTurn).toHaveBeenCalledWith(sid, "session-a-recovered-turn");
    expect(stopSessionTurn).not.toHaveBeenCalledWith(secondSid, expect.any(String));
  });

  it.each(["queued", "terminal"] as const)(
    "does not stop an older running turn when the failed POST readback confirms %s submission state",
    async (readbackState) => {
      let rejectSessionA!: (error: Error) => void;
      vi.mocked(submitSessionMessage).mockImplementation(() => new Promise((_, reject) => {
        rejectSessionA = reject;
      }));
      const client = mount();
      client.setQueryData<SessionDetail>(queryKeys.session(sid), {
        id: sid,
        status: "ready",
        currentPhase: "ready",
        messages: [],
      } as SessionDetail);
      await act(async () => controls.submit());
      await settle();
      const submissionId = vi.mocked(submitSessionMessage).mock.calls[0]?.[1].clientSubmissionId;
      expect(submissionId).toBeTruthy();
      await act(async () => controls.stop());

      const readback = readbackState === "queued"
        ? {
          id: sid,
          ledgerSeq: 12,
          status: "running",
          currentPhase: "running",
          activeTurnId: "older-running-turn",
          messages: [],
          queuedTurns: [{
            id: "queued-turn",
            position: 1,
            status: "queued",
            content: originalDraft,
            clientSubmissionId: submissionId,
          }],
        }
        : {
          id: sid,
          ledgerSeq: 12,
          status: "completed",
          currentPhase: "completed",
          activeTurnId: "accepted-terminal-turn",
          messages: [
            {
              id: "terminal-canonical-user",
              role: "user",
              content: originalDraft,
              timestamp: new Date().toISOString(),
              metadata: { clientSubmissionId: submissionId, turnId: "accepted-terminal-turn" },
            },
            {
              id: "terminal-canonical-assistant",
              role: "assistant",
              turnId: "accepted-terminal-turn",
              status: "completed",
              timestamp: new Date().toISOString(),
              turnItems: [{
                id: "terminal-answer-item",
                itemId: "terminal-answer-item",
                version: 1,
                sessionId: sid,
                turnId: "accepted-terminal-turn",
                status: "completed",
                revision: 1,
                sequence: 1,
                terminal: true,
                type: "agent_message",
                phase: "final_answer",
                text: "已完成",
              }],
            },
          ],
        };
      vi.mocked(fetchSessionDetailWindow).mockResolvedValue(readback as SessionDetail);

      await act(async () => {
        rejectSessionA(new Error("POST response lost after commit"));
        await Promise.resolve();
      });
      await settle();

      expect(stopSessionTurn).not.toHaveBeenCalled();
      expect(client.getQueryData<SessionDetail>(queryKeys.session(sid))?.stopRequested).not.toBe(true);
    },
  );

  it.each([false, true])("clears only its own active layer after queue confirmation (newer layer=%s)", async (withNewerLayer) => {
    let rejectReadback!: (error: Error) => void;
    vi.mocked(fetchSessionDetailWindow).mockReturnValue(new Promise<SessionDetail>((_resolve, reject) => {
      rejectReadback = reject;
    }));
    const client = mount();
    client.setQueryData<SessionDetail>(queryKeys.session(sid), { id: sid, messages: [] } as SessionDetail);
    await act(async () => controls.submit());
    await settle();
    const submissionId = vi.mocked(submitSessionMessage).mock.calls[0]?.[1].clientSubmissionId;
    expect(submissionId).toBeTruthy();
    if (withNewerLayer) {
      act(() => controls.setActiveTurnLayer(createOptimisticActiveTurnLayer({
        sessionId: sid,
        turnId: "newer-turn",
        clientSubmissionId: "newer-submission",
        accepted: false,
      })));
    }
    act(() => client.setQueryData<SessionDetail>(queryKeys.session(sid), (current) => ({
      ...current!,
      queuedTurns: [{
        id: "queued-turn",
        position: 1,
        status: "queued",
        content: originalDraft,
        clientSubmissionId: submissionId,
      }],
    })));
    await act(async () => {
      rejectReadback(new Error("readback unavailable"));
      await Promise.resolve();
    });
    await settle();

    if (withNewerLayer) {
      expect(controls.activeTurnLayer?.clientSubmissionId).toBe("newer-submission");
    } else {
      expect(controls.activeTurnLayer).toBeUndefined();
    }
    expect(controls.draft).toBe("");
    expect(controls.error).toBe("");
  });

  it("keeps an intentional empty draft when an older message request fails", async () => {
    let rejectRequest!: (error: Error) => void;
    vi.mocked(submitSessionMessage).mockImplementation(() => new Promise((_, reject) => { rejectRequest = reject; }));
    mount();
    await act(async () => controls.submit());
    await settle();
    act(() => controls.change("后来输入的文字"));
    act(() => controls.change(""));
    await act(async () => rejectRequest(new Error("late failure")));
    await settle();
    flushPendingSessionDraftWrites();
    expect(controls.draft).toBe("");
    expect(readStoredSessionDrafts()[sid] ?? "").toBe("");
  });

  it("removes the persisted draft when the user cancels edit mode", () => {
    mount();
    expect(readStoredSessionDrafts()[sid]).toBe(originalDraft);

    act(() => controls.cancelEdit());
    flushPendingSessionDraftWrites();

    expect(controls.draft).toBe("");
    expect(readStoredSessionDrafts()[sid]).toBeUndefined();
  });

  it("does not resurrect a debounced draft on pagehide after edit cancellation", () => {
    mount();
    act(() => controls.change("尚未落盘的编辑草稿"));
    act(() => controls.cancelEdit());
    act(() => window.dispatchEvent(new Event("pagehide")));

    expect(controls.draft).toBe("");
    expect(readStoredSessionDrafts()[sid]).toBeUndefined();
  });

  it("keeps a flushed draft deleted across composer reload after edit cancellation", async () => {
    mount();
    act(() => controls.change("已经落盘的编辑草稿"));
    flushPendingSessionDraftWrites();
    expect(readStoredSessionDrafts()[sid]).toBe("已经落盘的编辑草稿");

    act(() => controls.cancelEdit());
    expect(readStoredSessionDrafts()[sid]).toBeUndefined();
    await unmountLatest();

    mount([], { initialDraft: readStoredSessionDrafts()[sid] ?? "", persistInitialDraft: false });
    expect(controls.draft).toBe("");
    expect(readStoredSessionDrafts()[sid]).toBeUndefined();
  });

  it("keeps the matching optimistic layer when an accepted receipt omits its turn id", async () => {
    vi.mocked(submitSessionMessage).mockImplementation(async (sessionId, payload) => ({
      accepted: true,
      sessionId,
      clientSubmissionId: payload.clientSubmissionId,
      status: "accepted",
      acceptedAt: "2026-10-12T00:00:00.000Z",
    } as SessionTurnAcceptedResponse));
    mount();

    await act(async () => controls.submit());
    await flushMutationMicrotasks();

    const submissionId = vi.mocked(submitSessionMessage).mock.calls[0]?.[1].clientSubmissionId;
    expect(controls.activeTurnLayer).toMatchObject({
      clientSubmissionId: submissionId,
      status: "pending",
      processStage: "sending",
    });
  });

  it("does not let a late accepted receipt roll a terminal detail or newer layer back", async () => {
    let resolveReceipt!: (receipt: SessionTurnAcceptedResponse) => void;
    vi.mocked(submitSessionMessage).mockImplementation(() => new Promise((resolve) => {
      resolveReceipt = resolve;
    }));
    const client = mount();
    client.setQueryData<SessionDetail>(queryKeys.session(sid), {
      id: sid,
      status: "ready",
      currentPhase: "ready",
      messages: [],
    } as SessionDetail);

    await act(async () => controls.submit());
    await flushMutationMicrotasks();
    const submissionId = vi.mocked(submitSessionMessage).mock.calls[0]?.[1].clientSubmissionId;
    expect(submissionId).toBeTruthy();

    act(() => client.setQueryData(queryKeys.session(sid), terminalDetail(sid, submissionId!, "accepted-turn")));
    act(() => controls.setActiveTurnLayer(createOptimisticActiveTurnLayer({
      sessionId: sid,
      turnId: "newer-turn",
      clientSubmissionId: "newer-submission",
      accepted: false,
    })));
    await act(async () => {
      resolveReceipt(acceptedReceipt(sid, submissionId!, "accepted-turn"));
      await Promise.resolve();
    });
    await flushMutationMicrotasks();

    expect(client.getQueryData<SessionDetail>(queryKeys.session(sid))).toMatchObject({
      id: sid,
      status: "completed",
      currentPhase: "completed",
      activeTurnId: "",
    });
    expect(controls.activeTurnLayer?.clientSubmissionId).toBe("newer-submission");
  });

  it("performs one delayed canonical readback and retires a terminal accepted layer", async () => {
    vi.useFakeTimers();
    vi.mocked(submitSessionMessage).mockImplementation(async (sessionId, payload) => (
      acceptedReceipt(sessionId, payload.clientSubmissionId, "accepted-turn")
    ));
    vi.mocked(fetchSessionDetailWindow).mockImplementation(async (sessionId) => {
      const submissionId = vi.mocked(submitSessionMessage).mock.calls[0]?.[1].clientSubmissionId ?? "";
      return terminalDetail(sessionId, submissionId, "accepted-turn");
    });
    const client = mount();
    client.setQueryData<SessionDetail>(queryKeys.session(sid), { id: sid, messages: [] } as SessionDetail);

    await act(async () => controls.submit());
    await flushMutationMicrotasks();
    expect(controls.activeTurnLayer?.clientSubmissionId).toBeTruthy();
    expect(fetchSessionDetailWindow).not.toHaveBeenCalled();

    await act(async () => { await vi.advanceTimersByTimeAsync(2_999); });
    expect(fetchSessionDetailWindow).not.toHaveBeenCalled();
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    await flushMutationMicrotasks();

    expect(fetchSessionDetailWindow).toHaveBeenCalledExactlyOnceWith(sid, expect.objectContaining({
      includeSecondary: false,
      signal: expect.any(AbortSignal),
    }));
    expect(client.getQueryData<SessionDetail>(queryKeys.session(sid))?.status).toBe("completed");
    expect(controls.activeTurnLayer).toBeUndefined();

    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
    expect(fetchSessionDetailWindow).toHaveBeenCalledTimes(1);
  });

  it.each(["canonical", "terminal", "session switch", "unmount"] as const)(
    "retires the accepted readback task before its timer when %s arrives",
    async (settlement) => {
      vi.useFakeTimers();
      vi.mocked(submitSessionMessage).mockImplementation(async (sessionId, payload) => (
        acceptedReceipt(sessionId, payload.clientSubmissionId, "accepted-turn")
      ));
      const client = mount();
      client.setQueryData<SessionDetail>(queryKeys.session(sid), { id: sid, messages: [] } as SessionDetail);
      await act(async () => controls.submit());
      await flushMutationMicrotasks();
      const submissionId = vi.mocked(submitSessionMessage).mock.calls[0]?.[1].clientSubmissionId;
      expect(submissionId).toBeTruthy();

      if (settlement === "canonical") {
        act(() => client.setQueryData<SessionDetail>(queryKeys.session(sid), {
          id: sid,
          messages: [{
            id: "canonical-user",
            role: "user",
            content: originalDraft,
            timestamp: "2026-10-12T00:00:01.000Z",
            metadata: { clientSubmissionId: submissionId, turnId: "accepted-turn" },
          }],
        } as SessionDetail));
      } else if (settlement === "terminal") {
        const layer = controls.activeTurnLayer;
        expect(layer).toBeTruthy();
        act(() => controls.setActiveTurnLayer({ ...layer!, status: "completed" }));
      } else if (settlement === "session switch") {
        act(() => controls.switchSession(secondSid));
        await flushMutationMicrotasks();
      } else {
        await unmountLatest();
      }

      await act(async () => { await vi.advanceTimersByTimeAsync(3_000); });
      expect(fetchSessionDetailWindow).not.toHaveBeenCalled();
    },
  );

  it("does not register accepted readback after unmount while the POST is pending", async () => {
    vi.useFakeTimers();
    let resolveReceipt!: (receipt: SessionTurnAcceptedResponse) => void;
    vi.mocked(submitSessionMessage).mockImplementation(() => new Promise((resolve) => {
      resolveReceipt = resolve;
    }));
    mount();
    await act(async () => controls.submit());
    await flushMutationMicrotasks();
    expect(submitSessionMessage).toHaveBeenCalledTimes(1);

    await unmountLatest();
    const payload = vi.mocked(submitSessionMessage).mock.calls[0]?.[1];
    expect(payload).toBeTruthy();
    await act(async () => {
      resolveReceipt(acceptedReceipt(sid, payload!.clientSubmissionId, "accepted-after-unmount"));
      await Promise.resolve();
    });
    await flushMutationMicrotasks();
    await act(async () => { await vi.advanceTimersByTimeAsync(3_000); });

    expect(fetchSessionDetailWindow).not.toHaveBeenCalled();
  });

  it("does not let a replayed failure updater overwrite newer persisted input", async () => {
    let rejectRequest!: (error: Error) => void;
    vi.mocked(submitSessionMessage).mockImplementation(() => new Promise((_, reject) => { rejectRequest = reject; }));
    mount();
    await act(async () => controls.submit());
    await settle();

    // Simulate React interrupting and rebasing the queued restore updater. The
    // newer change event saves immediately, then both state updaters replay.
    act(() => controls.deferDraftUpdates());
    await act(async () => {
      rejectRequest(new Error("late failure"));
      await new Promise((resolve) => setTimeout(resolve, 10));
    });
    act(() => controls.change("重放恢复更新时用户输入的新草稿"));
    act(() => controls.replayDeferredDraftUpdates());
    await settle();

    flushPendingSessionDraftWrites();
    expect(controls.draft).toBe("重放恢复更新时用户输入的新草稿");
    expect(readStoredSessionDrafts()[sid]).toBe("重放恢复更新时用户输入的新草稿");
  });
});
