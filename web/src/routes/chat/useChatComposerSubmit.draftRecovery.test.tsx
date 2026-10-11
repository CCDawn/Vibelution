// @vitest-environment happy-dom
import React, { act, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { onlineManager, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { queryKeys } from "../../api/queryKeys";
import type { SessionDetail } from "../../api/types";
import { stopSessionTurn, submitSessionMessage, uploadSessionImageAttachment } from "../../api/chat";
import { createOptimisticActiveTurnLayer, type ActiveTurnLayerState } from "../chatActiveTurnLayer";
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
const originalDraft = "发送失败后仍需要保留的文字";
let controls: {
  change: (value: string) => void;
  submit: () => void;
  stop: () => void;
  switchSession: (sessionId: string) => void;
  draft: string;
  error: string;
  activeTurnLayer?: ActiveTurnLayerState;
  setActiveTurnLayer: (layer: ActiveTurnLayerState | undefined) => void;
  deferDraftUpdates: () => void;
  replayDeferredDraftUpdates: () => void;
};
const roots: Root[] = [];
const clients: QueryClient[] = [];

function Harness({ client, attachments }: { client: QueryClient; attachments: ComposerImageAttachment[] }) {
  const [activeSessionId, setActiveSessionId] = useState(sid);
  const [drafts, setDraftsState] = useState<Record<string, string>>({ [sid]: originalDraft, [secondSid]: "" });
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
  const [activeTurnLayers, setActiveTurnLayers] = useState<Record<string, ActiveTurnLayerState>>({});
  const uploadInFlight = useRef<Record<string, boolean>>({});
  const activeDetail = client.getQueryData<SessionDetail>(queryKeys.session(activeSessionId));
  const mutations = useChatComposerTurnMutations({
    queryClient: client,
    chatWorkspaceCache: createChatWorkspaceCache(client),
    t: ((key: string) => key) as never,
    describeError: (error, fallback) => error instanceof Error ? error.message : fallback,
    syncSessionDetail: () => undefined,
    setActiveTurnLayersBySession: setActiveTurnLayers,
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
    latestUserMessageId: "", activeTurnId: activeTurnLayers[activeSessionId]?.turnId, detail: activeDetail,
    setMentalModelEnabledForNextTurn: () => undefined, setRuntimeStatusEnabledForNextTurn: () => undefined,
  });
  controls = {
    change: actions.handleComposerChange,
    submit: actions.handleSubmitTurn,
    stop: actions.handleStopTurn,
    switchSession: setActiveSessionId,
    draft: drafts[activeSessionId] ?? "",
    error: errors[activeSessionId] ?? "",
    activeTurnLayer: activeTurnLayers[activeSessionId],
    setActiveTurnLayer: (layer) => setActiveTurnLayers((current) => {
      if (!layer) {
        const { [activeSessionId]: _removed, ...remaining } = current;
        return remaining;
      }
      return { ...current, [activeSessionId]: layer };
    }),
    deferDraftUpdates: () => { deferredDraftUpdatesRef.current = []; },
    replayDeferredDraftUpdates: () => {
      const updates = deferredDraftUpdatesRef.current ?? [];
      deferredDraftUpdatesRef.current = null;
      setDraftsState((current) => updates.reduce((next, update) => update(next), current));
    },
  };
  return null;
}

function mount(attachments: ComposerImageAttachment[] = []) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  clients.push(client);
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  roots.push(root);
  act(() => root.render(<QueryClientProvider client={client}><Harness client={client} attachments={attachments} /></QueryClientProvider>));
  act(() => controls.change(originalDraft));
  flushPendingSessionDraftWrites();
  expect(readStoredSessionDrafts()[sid]).toBe(originalDraft);
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
