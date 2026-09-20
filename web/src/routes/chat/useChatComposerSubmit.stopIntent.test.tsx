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
  overrides: Record<string, unknown> = {},
) {
  return {
    mutate,
    mutateAsync: async (variables: TVariables) => {
      mutate(variables);
      return {};
    },
    isPending: false,
    ...overrides,
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

  it("keeps a deferred stop scoped across a session switch until its late acceptance arrives", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const stopMutate = vi.fn();
    const sessionOnePending = baseOptions(queryClient, stopMutate, {
      activeSessionId: "session-1",
      activeTurnId: "optimistic-submit-1",
      detail: runningDetail(),
      submitTurnMutation: mutationStub(vi.fn(), {
        isPending: true,
        variables: { sessionId: "session-1", clientSubmissionId: "submission-1" },
      }),
    });

    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(<Host options={sessionOnePending} />);
    });
    await act(async () => {
      container?.querySelector<HTMLButtonElement>('[data-testid="stop"]')?.click();
    });

    await act(async () => {
      root?.render(<Host options={baseOptions(queryClient, stopMutate, {
        activeSessionId: "session-2",
        activeTurnId: "turn-new-session",
        detail: runningDetail({ id: "session-2", activeTurnId: "turn-new-session" }),
        submitTurnMutation: mutationStub(vi.fn()),
      })} />);
    });
    expect(stopMutate).not.toHaveBeenCalled();

    await act(async () => {
      root?.render(<Host options={baseOptions(queryClient, stopMutate, {
        activeSessionId: "session-1",
        activeTurnId: "turn-accepted-late",
        detail: runningDetail({ activeTurnId: "turn-accepted-late" }),
        submitTurnMutation: mutationStub(vi.fn(), {
          data: {
            accepted: true,
            sessionId: "session-1",
            turnId: "turn-accepted-late",
            clientSubmissionId: "submission-1",
          },
          variables: { sessionId: "session-1", clientSubmissionId: "submission-1" },
        }),
      })} />);
    });

    expect(stopMutate).toHaveBeenCalledTimes(1);
    expect(stopMutate).toHaveBeenCalledWith(expect.objectContaining({
      sessionId: "session-1",
      turnId: "turn-accepted-late",
    }));
  });

  it("handles A's late acceptance after B submitted, even when the mutation observer only exposes B", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const stopMutate = vi.fn();
    const sessionOnePending = baseOptions(queryClient, stopMutate, {
      activeSessionId: "session-1",
      activeTurnId: "optimistic-submit-1",
      detail: runningDetail(),
      submitTurnMutation: mutationStub(vi.fn(), {
        isPending: true,
        variables: { sessionId: "session-1", clientSubmissionId: "submission-a" },
      }),
    });

    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(<Host options={sessionOnePending} />);
    });
    await act(async () => {
      container?.querySelector<HTMLButtonElement>('[data-testid="stop"]')?.click();
    });

    // B is now the active observer result. A's result is deliberately absent
    // from the observer-shaped props below; the cache still retains both
    // mutation instances and reports each completion independently.
    await act(async () => {
      root?.render(<Host options={baseOptions(queryClient, stopMutate, {
        activeSessionId: "session-2",
        activeTurnId: "turn-b",
        detail: runningDetail({ id: "session-2", activeTurnId: "turn-b" }),
        submitTurnMutation: mutationStub(vi.fn(), {
          data: {
            accepted: true,
            sessionId: "session-2",
            turnId: "turn-b",
            clientSubmissionId: "submission-b",
          },
          variables: { sessionId: "session-2", clientSubmissionId: "submission-b" },
        }),
      })} />);
    });

    const executeAccepted = (variables: { sessionId: string; clientSubmissionId: string }, turnId: string) =>
      queryClient.getMutationCache().build(queryClient, {
        mutationFn: async () => ({
          accepted: true,
          sessionId: variables.sessionId,
          turnId,
          clientSubmissionId: variables.clientSubmissionId,
        }),
      }).execute(variables);

    await act(async () => {
      await executeAccepted({ sessionId: "session-2", clientSubmissionId: "submission-b" }, "turn-b");
      await executeAccepted({ sessionId: "session-1", clientSubmissionId: "submission-a" }, "turn-a");
    });

    expect(stopMutate).toHaveBeenCalledTimes(1);
    expect(stopMutate).toHaveBeenCalledWith(expect.objectContaining({
      sessionId: "session-1",
      turnId: "turn-a",
    }));
  });

  it("drops a deferred stop when its submit fails, so a later turn is not stopped", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const stopMutate = vi.fn();
    const submitError = new Error("submit failed");
    const pendingSubmit = mutationStub(vi.fn(), {
      isPending: true,
      variables: { sessionId: "session-1", clientSubmissionId: "submission-failed" },
    });
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(<Host options={baseOptions(queryClient, stopMutate, {
        submitTurnMutation: pendingSubmit,
        activeTurnId: "optimistic-submit-1",
        detail: runningDetail(),
      })} />);
    });
    await act(async () => {
      container?.querySelector<HTMLButtonElement>('[data-testid="stop"]')?.click();
    });
    await act(async () => {
      root?.render(<Host options={baseOptions(queryClient, stopMutate, {
        activeSessionId: "session-2",
        activeTurnId: "turn-2",
        detail: runningDetail({ id: "session-2", activeTurnId: "turn-2" }),
        submitTurnMutation: mutationStub(vi.fn()),
      })} />);
    });
    await act(async () => {
      root?.render(<Host options={baseOptions(queryClient, stopMutate, {
        activeSessionId: "session-2",
        activeTurnId: "turn-2",
        detail: runningDetail({ id: "session-2", activeTurnId: "turn-2" }),
        submitTurnMutation: mutationStub(vi.fn(), {
          error: submitError,
          variables: { sessionId: "session-1", clientSubmissionId: "submission-failed" },
        }),
      })} />);
    });
    await act(async () => {
      root?.render(<Host options={baseOptions(queryClient, stopMutate, {
        activeSessionId: "session-2",
        activeTurnId: "turn-2",
        detail: runningDetail({ id: "session-2", activeTurnId: "turn-2" }),
        submitTurnMutation: mutationStub(vi.fn(), {
          data: {
            accepted: true,
            sessionId: "session-1",
            turnId: "late-old-turn",
            clientSubmissionId: "submission-failed",
          },
          variables: { sessionId: "session-1", clientSubmissionId: "submission-failed" },
        }),
      })} />);
    });
    expect(stopMutate).not.toHaveBeenCalled();
  });
});
