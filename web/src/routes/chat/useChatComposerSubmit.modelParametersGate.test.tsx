/** @vitest-environment happy-dom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { act, useRef, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { queryKeys } from "../../api/queryKeys";
import { updateSessionQueuedTurn } from "../../api/chat";
import type { ConversationMessage, SessionDetail } from "../../api/types";
import type { ChatEditTarget } from "../chatComposerState";
import { useChatComposerSubmitActions, type ChatComposerTurnMutations, type UseChatComposerSubmitActionsResult } from "./useChatComposerSubmit";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

vi.mock("../../api/chat", async (importOriginal) => ({
  ...await importOriginal<typeof import("../../api/chat")>(),
  updateSessionQueuedTurn: vi.fn().mockResolvedValue([]),
}));

const sessionId = "session-model-gate";
const userMessage = { id: "user-1", role: "user", content: "原始请求", metadata: { turnId: "turn-1" } } as ConversationMessage;
const assistantMessage = { id: "assistant-1", role: "assistant", content: "失败的回复", metadata: { turnId: "turn-1" } } as ConversationMessage;
const sessionDetail = {
  id: sessionId,
  title: "Session",
  status: "running",
  currentPhase: "running",
  activeTurnId: "turn-1",
  stopRequested: false,
  messages: [userMessage, assistantMessage],
  queuedTurns: [],
} as SessionDetail;

function mutation() {
  return {
    mutate: vi.fn(),
    mutateAsync: vi.fn().mockResolvedValue(sessionDetail),
    isPending: false,
    isSuccess: false,
    variables: undefined,
    data: undefined,
    error: null,
  };
}

function makeMutations(): ChatComposerTurnMutations {
  return {
    submitTurnMutation: mutation(),
    editResubmitMutation: mutation(),
    regenerateMutation: mutation(),
    switchHeadMutation: mutation(),
    stopTurnMutation: mutation(),
    sessionGuidanceMutation: mutation(),
  } as unknown as ChatComposerTurnMutations;
}

function Harness({
  queryClient,
  mutations,
  savePendingRef,
  actionsRef,
  detail = sessionDetail,
}: {
  queryClient: QueryClient;
  mutations: ChatComposerTurnMutations;
  savePendingRef: { current: boolean };
  actionsRef: { current: UseChatComposerSubmitActionsResult | null };
  detail?: SessionDetail;
}) {
  const [busy, setBusy] = useState(false);
  const [editTarget, setEditTarget] = useState<ChatEditTarget | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({ [sessionId]: "新消息" });
  const actions = useChatComposerSubmitActions({
    ...mutations,
    queryClient,
    lang: "zh",
    describeError: (_error, fallback) => fallback,
    setSessionDrafts: setDrafts,
    sessionFollowupQueues: { [sessionId]: [{ id: "queued-1", text: "排队消息", canSteer: true }] },
    setSessionComposerErrors: () => undefined,
    setSessionImageAttachments: () => undefined,
    setSessionReferenceAttachments: () => undefined,
    setSessionImageUploadPending: () => undefined,
    setSessionEditTargets: () => undefined,
    imageUploadInFlightRef: useRef({}),
    activeSessionId: sessionId,
    activeDraftEffective: drafts[sessionId] ?? "",
    activeImageAttachments: [],
    activeReferenceAttachments: [],
    mentalModelEnabledForNextTurn: false,
    runtimeStatusEnabledForNextTurn: false,
    turnModelSelection: null,
    resolvedEditTarget: editTarget,
    activeEditTarget: editTarget,
    composerDisabled: false,
    sessionBusy: busy,
    sessionStopping: false,
    activePhase: busy ? "running" : "ready",
    activeAgentImageInputUnsupported: false,
    activeImageInputModelId: "model-1",
    latestUserMessageId: userMessage.id,
    activeTurnId: "turn-1",
    detail,
    setMentalModelEnabledForNextTurn: () => undefined,
    setRuntimeStatusEnabledForNextTurn: () => undefined,
    isModelParametersSavePending: () => savePendingRef.current,
  });
  actionsRef.current = actions;
  return (
    <>
      <button type="button" data-testid="busy" onClick={() => setBusy(true)}>busy</button>
      <button type="button" data-testid="idle" onClick={() => setBusy(false)}>idle</button>
      <button type="button" data-testid="edit" onClick={() => setEditTarget({ messageId: userMessage.id, original: userMessage.content })}>edit</button>
    </>
  );
}

describe("useChatComposerSubmit Agent model parameter save gate", () => {
  let root: Root | undefined;
  let host: HTMLDivElement | undefined;
  let queryClient: QueryClient | undefined;

  afterEach(async () => {
    if (root) await act(async () => root?.unmount());
    host?.remove();
    queryClient?.clear();
    root = undefined;
    host = undefined;
    queryClient = undefined;
    vi.clearAllMocks();
  });

  it.each(["retry", "regenerate"])("%s repeats the original request instead of an inserted guidance note", async (action) => {
    queryClient = new QueryClient();
    const detail = { ...sessionDetail, messages: [userMessage, { id: "guidance-1", role: "user", content: "插入的指导", metadata: { kind: "user_guidance", turnId: "turn-1" } }, assistantMessage] } as SessionDetail;
    queryClient.setQueryData(queryKeys.session(sessionId), detail);
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);
    const mutations = makeMutations();
    const actionsRef: { current: UseChatComposerSubmitActionsResult | null } = { current: null };
    await act(async () => root?.render(
      <QueryClientProvider client={queryClient!}>
        <Harness queryClient={queryClient!} mutations={mutations} savePendingRef={{ current: false }} actionsRef={actionsRef} detail={detail} />
      </QueryClientProvider>,
    ));
    await act(async () => action === "retry" ? actionsRef.current?.handleRetryFailedTurn() : actionsRef.current?.handleRegenerateAssistantMessage(assistantMessage));
    expect(mutations.regenerateMutation.mutate).toHaveBeenCalledWith(expect.objectContaining({ messageId: "user-1", content: "原始请求" }));
  });

  it("blocks same-frame new submissions while keeping stop available", async () => {
    queryClient = new QueryClient({ defaultOptions: { mutations: { retry: false }, queries: { retry: false } } });
    queryClient.setQueryData(queryKeys.session(sessionId), sessionDetail);
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);
    const mutations = makeMutations();
    const savePendingRef = { current: false };
    const actionsRef: { current: UseChatComposerSubmitActionsResult | null } = { current: null };

    await act(async () => {
      root?.render(
        <QueryClientProvider client={queryClient!}>
          <Harness queryClient={queryClient!} mutations={mutations} savePendingRef={savePendingRef} actionsRef={actionsRef} />
        </QueryClientProvider>,
      );
    });

    // Model settings save and send share this event turn. The mutable gate is
    // visible before React commits the pending mutation state.
    await act(async () => {
      savePendingRef.current = true;
      actionsRef.current?.handleSubmitTurn();
    });
    expect(mutations.submitTurnMutation.mutate).not.toHaveBeenCalled();

    await act(async () => host?.querySelector<HTMLButtonElement>('[data-testid="busy"]')?.click());
    await act(async () => {
      actionsRef.current?.handleSubmitTurn();
      actionsRef.current?.handleSubmitGuidance("safe");
      actionsRef.current?.handleFollowupQueueSteer("queued-1");
      actionsRef.current?.handleStopTurn();
    });
    expect(mutations.submitTurnMutation.mutate).not.toHaveBeenCalled();
    expect(mutations.sessionGuidanceMutation.mutate).not.toHaveBeenCalled();
    expect(mutations.sessionGuidanceMutation.mutateAsync).not.toHaveBeenCalled();
    expect(mutations.stopTurnMutation.mutate).toHaveBeenCalledTimes(1);

    await act(async () => host?.querySelector<HTMLButtonElement>('[data-testid="idle"]')?.click());
    await act(async () => {
      actionsRef.current?.handleRegenerateAssistantMessage(assistantMessage);
      actionsRef.current?.handleRetryFailedTurn();
    });
    await act(async () => host?.querySelector<HTMLButtonElement>('[data-testid="edit"]')?.click());
    await act(async () => actionsRef.current?.handleSubmitTurn());

    expect(mutations.regenerateMutation.mutate).not.toHaveBeenCalled();
    expect(mutations.editResubmitMutation.mutate).not.toHaveBeenCalled();
    expect(mutations.stopTurnMutation.mutate).toHaveBeenCalledTimes(1);
  });

  it("waits for parameter saving before an edited failed queue item can retry", async () => {
    queryClient = new QueryClient();
    queryClient.setQueryData(queryKeys.session(sessionId), {
      ...sessionDetail,
      queuedTurns: [{ id: "failed-queue", content: "原消息", status: "blocked", attachments: [] }],
    });
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);
    const savePendingRef = { current: false };
    const actionsRef: { current: UseChatComposerSubmitActionsResult | null } = { current: null };
    await act(async () => {
      root?.render(
        <QueryClientProvider client={queryClient!}>
          <Harness queryClient={queryClient!} mutations={makeMutations()} savePendingRef={savePendingRef} actionsRef={actionsRef} />
        </QueryClientProvider>,
      );
    });
    await act(async () => {
      savePendingRef.current = true;
      actionsRef.current?.handleFollowupQueueUpdate("failed-queue", "重试消息");
    });
    expect(updateSessionQueuedTurn).not.toHaveBeenCalled();
    expect(queryClient.getQueryData<SessionDetail>(queryKeys.session(sessionId))?.queuedTurns?.[0]?.content).toBe("原消息");
    await act(async () => {
      savePendingRef.current = false;
      actionsRef.current?.handleFollowupQueueUpdate("failed-queue", "重试消息");
    });
    expect(updateSessionQueuedTurn).toHaveBeenCalledWith(sessionId, "failed-queue", { content: "重试消息" });
  });
});
