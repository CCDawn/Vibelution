/** @vitest-environment happy-dom */
import { QueryClient } from "@tanstack/react-query";
import React, { act, useRef, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ConversationMessage, SessionDetail } from "../../api/types";
import {
  useChatComposerSubmitActions,
  type ChatComposerTurnMutations,
} from "./useChatComposerSubmit";

vi.mock("./chatSubmitTelemetry", () => ({
  postSubmitTelemetry: vi.fn(),
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function mutationStub<TVariables>(mutate: (variables: TVariables) => void) {
  return {
    mutate,
    mutateAsync: async (variables: TVariables) => {
      mutate(variables);
      return {};
    },
    isPending: false,
  } as ChatComposerTurnMutations[keyof ChatComposerTurnMutations];
}

function userMessage(): ConversationMessage {
  return {
    id: "user-1",
    role: "user",
    timestamp: "2026-09-13T01:00:00Z",
    turnId: "turn-1",
    status: "completed",
    content: "请修复登录失败的问题。",
    nodeId: "node-user-1",
  } as ConversationMessage;
}

function Harness({
  busy = false,
  messages,
  regenerate,
}: {
  busy?: boolean;
  messages: ConversationMessage[];
  regenerate: (variables: unknown) => void;
}) {
  const queryClient = useRef(new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })).current;
  const [sessionDrafts, setSessionDrafts] = useState<Record<string, string>>({});
  const [sessionFollowupQueues, setSessionFollowupQueues] = useState<Record<string, never[]>>({});
  const imageUploadInFlightRef = useRef<Record<string, boolean>>({});
  const actions = useChatComposerSubmitActions({
    queryClient,
    lang: "zh",
    describeError: (error, fallback) => (error instanceof Error ? error.message : fallback),
    submitTurnMutation: mutationStub(vi.fn()),
    editResubmitMutation: mutationStub(vi.fn()),
    regenerateMutation: mutationStub(regenerate),
    stopTurnMutation: mutationStub(vi.fn()),
    sessionGuidanceMutation: mutationStub(vi.fn()),
    setSessionDrafts,
    sessionFollowupQueues,
    setSessionFollowupQueues,
    setSessionComposerErrors: () => undefined,
    setSessionImageAttachments: () => undefined,
    setSessionReferenceAttachments: () => undefined,
    setSessionImageUploadPending: () => undefined,
    setSessionEditTargets: () => undefined,
    imageUploadInFlightRef,
    activeSessionId: "session-1",
    activeDraftEffective: "",
    activeImageAttachments: [],
    activeReferenceAttachments: [],
    mentalModelEnabledForNextTurn: true,
    runtimeStatusEnabledForNextTurn: false,
    resolvedEditTarget: null,
    activeEditTarget: null,
    composerDisabled: false,
    sessionBusy: busy,
    sessionStopping: false,
    activePhase: busy ? "running" : "ready",
    activeAgentImageInputUnsupported: false,
    activeImageInputModelId: "model-1",
    latestUserMessageId: "user-1",
    activeTurnId: "turn-1",
    detail: { id: "session-1", activeTurnId: "turn-1", messages } as SessionDetail,
    setMentalModelEnabledForNextTurn: () => undefined,
    setRuntimeStatusEnabledForNextTurn: () => undefined,
  });

  return (
    <button type="button" data-testid="retry" onClick={() => actions.handleRetryFailedTurn()}>
      retry
    </button>
  );
}

describe("useChatComposerSubmitActions failed-turn retry", () => {
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

  async function mount(props: { busy?: boolean; messages: ConversationMessage[]; regenerate: (variables: unknown) => void }) {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(<Harness {...props} />);
    });
  }

  async function clickRetry() {
    await act(async () => {
      container?.querySelector<HTMLButtonElement>('[data-testid="retry"]')?.click();
    });
  }

  it("retries the latest user message through the regenerate pipeline", async () => {
    const regenerate = vi.fn();
    await mount({ messages: [userMessage()], regenerate });

    await clickRetry();

    expect(regenerate).toHaveBeenCalledTimes(1);
    expect(regenerate).toHaveBeenCalledWith(expect.objectContaining({
      sessionId: "session-1",
      messageId: "user-1",
      baseMessageId: "node-user-1",
      content: "请修复登录失败的问题。",
      mentalModelEnabled: true,
      runtimeStatusEnabled: false,
    }));
    expect(typeof (regenerate.mock.calls[0]?.[0] as { clientSubmissionId?: unknown }).clientSubmissionId).toBe("string");
  });

  it("does not retry while the session is busy", async () => {
    const regenerate = vi.fn();
    await mount({ busy: true, messages: [userMessage()], regenerate });

    await clickRetry();

    expect(regenerate).not.toHaveBeenCalled();
  });

  it("does not retry when the transcript has no user message", async () => {
    const regenerate = vi.fn();
    await mount({ messages: [], regenerate });

    await clickRetry();

    expect(regenerate).not.toHaveBeenCalled();
  });
});
