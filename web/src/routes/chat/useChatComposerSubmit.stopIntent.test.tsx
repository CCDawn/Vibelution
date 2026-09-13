/** @vitest-environment happy-dom */
import { QueryClient } from "@tanstack/react-query";
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { queryKeys } from "../../api/queryKeys";
import type { SessionDetail } from "../../api/types";
import {
  useChatComposerSubmitActions,
  type ChatComposerTurnMutations,
  type UseChatComposerSubmitActionsOptions,
} from "./useChatComposerSubmit";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function mutationStub<TVariables>(
  mutate: (variables: TVariables) => void,
) {
  return {
    mutate,
    mutateAsync: async (variables: TVariables) => {
      mutate(variables);
      return {};
    },
    isPending: false,
  } as ChatComposerTurnMutations[keyof ChatComposerTurnMutations];
}

function runningDetail(overrides: Partial<SessionDetail> = {}): SessionDetail {
  return {
    id: "session-1",
    title: "Session",
    status: "running",
    taskSummary: "",
    lastActive: "",
    updatedAt: "",
    currentPhase: "running",
    defaultFileContext: "",
    previewTabs: [],
    activePreviewPath: "",
    changedFiles: [],
    readFiles: [],
    messages: [],
    stopRequested: false,
    stopRequestedAt: "",
    stopReason: "",
    ...overrides,
  };
}

function Host({ options }: { options: UseChatComposerSubmitActionsOptions }) {
  const actions = useChatComposerSubmitActions(options);
  return (
    <button type="button" data-testid="stop" onClick={() => actions.handleStopTurn()}>
      stop
    </button>
  );
}

describe("useChatComposerSubmitActions stop intent", () => {
  let root: Root | null = null;
  let container: HTMLDivElement | null = null;

  afterEach(async () => {
    if (root) {
      await act(async () => {
        root?.unmount();
      });
    }
    container?.remove();
    root = null;
    container = null;
  });

  function baseOptions(
    queryClient: QueryClient,
    stopMutate: ReturnType<typeof vi.fn>,
    overrides: Partial<UseChatComposerSubmitActionsOptions> = {},
  ): UseChatComposerSubmitActionsOptions {
    return {
      queryClient,
      lang: "zh",
      describeError: (_error, fallback) => fallback,
      submitTurnMutation: mutationStub(vi.fn()),
      editResubmitMutation: mutationStub(vi.fn()),
      regenerateMutation: mutationStub(vi.fn()),
      switchHeadMutation: mutationStub(vi.fn()),
      stopTurnMutation: mutationStub(stopMutate),
      sessionGuidanceMutation: mutationStub(vi.fn()),
      setSessionDrafts: vi.fn(),
      sessionFollowupQueues: {},
      setSessionFollowupQueues: vi.fn(),
      setSessionComposerErrors: vi.fn(),
      setSessionImageAttachments: vi.fn(),
      setSessionReferenceAttachments: vi.fn(),
      setSessionImageUploadPending: vi.fn(),
      setSessionEditTargets: vi.fn(),
      imageUploadInFlightRef: { current: {} },
      activeSessionId: "session-1",
      activeDraftEffective: "",
      activeImageAttachments: [],
      activeReferenceAttachments: [],
      mentalModelEnabledForNextTurn: false,
      runtimeStatusEnabledForNextTurn: false,
      resolvedEditTarget: null,
      activeEditTarget: null,
      composerDisabled: false,
      sessionBusy: true,
      sessionStopping: false,
      activePhase: "running",
      activeAgentImageInputUnsupported: false,
      activeImageInputModelId: "model-1",
      latestUserMessageId: "user-1",
      activeTurnId: undefined,
      detail: undefined,
      setMentalModelEnabledForNextTurn: vi.fn(),
      setRuntimeStatusEnabledForNextTurn: vi.fn(),
      ...overrides,
    };
  }

  it("enters stopping immediately for an optimistic turn and fires the stop once the turn is accepted", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const running = runningDetail();
    queryClient.setQueryData(queryKeys.session("session-1"), running);
    const stopMutate = vi.fn();
    const optimisticOptions = baseOptions(queryClient, stopMutate, {
      activeTurnId: "optimistic-submit-1",
      detail: running,
    });

    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(<Host options={optimisticOptions} />);
    });

    await act(async () => {
      container?.querySelector<HTMLButtonElement>('[data-testid="stop"]')?.click();
    });

    const patched = queryClient.getQueryData<SessionDetail>(queryKeys.session("session-1"));
    expect(patched?.currentPhase).toBe("stopping");
    expect(patched?.stopRequested).toBe(true);
    expect(patched?.stopRequestedAt).toBeTruthy();
    expect(stopMutate).not.toHaveBeenCalled();

    const accepted = runningDetail({ activeTurnId: "turn-2" });
    await act(async () => {
      root?.render(<Host options={baseOptions(queryClient, stopMutate, {
        activeTurnId: "turn-2",
        detail: accepted,
      })} />);
    });

    expect(stopMutate).toHaveBeenCalledTimes(1);
    expect(stopMutate).toHaveBeenCalledWith(expect.objectContaining({
      sessionId: "session-1",
      turnId: "turn-2",
      deferredStop: expect.objectContaining({
        previousDetail: expect.objectContaining({ currentPhase: "running" }),
        stoppingAt: patched?.stopRequestedAt,
      }),
    }));
  });

  it("sends the stop directly when the accepted turn id is already known", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const running = runningDetail({ activeTurnId: "turn-2" });
    queryClient.setQueryData(queryKeys.session("session-1"), running);
    const stopMutate = vi.fn();
    const options = baseOptions(queryClient, stopMutate, {
      activeTurnId: "turn-2",
      detail: running,
    });

    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(<Host options={options} />);
    });

    await act(async () => {
      container?.querySelector<HTMLButtonElement>('[data-testid="stop"]')?.click();
    });

    expect(stopMutate).toHaveBeenCalledTimes(1);
    expect(stopMutate).toHaveBeenCalledWith({
      sessionId: "session-1",
      turnId: "turn-2",
    });
  });
});
