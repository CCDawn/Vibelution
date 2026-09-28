/** @vitest-environment happy-dom */
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import React, { act, useRef, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { queryKeys } from "../../api/queryKeys";
import type {
  SessionDetail,
  SessionReferenceAttachment,
  SessionTurnAcceptedResponse,
} from "../../api/types";
import { submitSessionMessage, uploadSessionImageAttachment } from "../../api/chat";
import {
  createChatWorkspaceCache,
} from "../chatWorkspaceCache";
import type { ComposerImageAttachment } from "./chatComposerSubmitModel";
import {
  useChatComposerSubmitActions,
  useChatComposerTurnMutations,
  type ChatComposerTurnMutations,
} from "./useChatComposerSubmit";
import { mergeSessionDetailMessageWindow } from "../chatSessionState";

/** Mirrors ChatCodingRouteWorkbench.sessionDetailStructuralSharing without importing the workbench. */
function structuralSharing(previous: unknown, next: unknown): SessionDetail {
  return mergeSessionDetailMessageWindow(previous as SessionDetail | undefined, next as SessionDetail);
}

vi.mock("./chatSubmitTelemetry", () => ({
  postSubmitTelemetry: vi.fn(),
}));

vi.mock("../../api/chat", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api/chat")>();
  return {
    ...actual,
    uploadSessionImageAttachment: vi.fn(async (_sessionId: string, attachment: ComposerImageAttachment) => {
      if (attachment.filename.includes("bad")) {
        throw new Error("upload rejected for bad.png");
      }
      if (uploadGate) {
        return await uploadGate(attachment);
      }
      return { artifactId: `artifact-${attachment.filename}` };
    }),
    submitSessionMessage: vi.fn(async (): Promise<SessionTurnAcceptedResponse> => ({
      turnId: "turn-accepted-1",
      acceptedAt: "2026-09-28T00:00:00.000Z",
    })),
  };
});

/** Per-test gate to hold a successful upload in flight (interleave poll commits). */
let uploadGate: ((attachment: ComposerImageAttachment) => Promise<{ artifactId: string }>) | null = null;

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const uploadSessionImageAttachmentMock = vi.mocked(uploadSessionImageAttachment);
const submitSessionMessageMock = vi.mocked(submitSessionMessage);

function makeAttachment(filename: string): ComposerImageAttachment {
  return {
    id: `chip-${filename}`,
    file: new File(["bytes"], filename, { type: "image/png" }),
    filename,
    previewUrl: `blob:${filename}`,
    sizeBytes: 4,
    contentType: "image/png",
    kind: "image",
  };
}

function seedSessionDetail(queryClient: QueryClient, sessionId: string): void {
  const detail: SessionDetail = {
    id: sessionId,
    status: "ready",
    currentPhase: "ready",
    messages: [
      {
        id: `${sessionId}-message-1`,
        role: "user",
        content: "已有的历史消息",
        timestamp: "2026-09-28T00:00:00.000Z",
        metadata: { clientSubmissionId: "submission-history-1" },
      },
    ],
    messageWindow: {
      totalMessages: 1,
      returnedMessages: 1,
      oldestMessageIndex: 1,
      newestMessageIndex: 1,
      hasEarlier: false,
      hasLater: false,
      nextBeforeMessageIndex: null,
    },
  } as unknown as SessionDetail;
  queryClient.setQueryData(queryKeys.session(sessionId), detail);
}

function optimisticRows(queryClient: QueryClient, sessionId: string) {
  const detail = queryClient.getQueryData<SessionDetail>(queryKeys.session(sessionId));
  return (detail?.messages ?? []).filter(
    (message) => message.role === "user" && message.metadata?.optimisticUserMessage === true,
  );
}

type HarnessProps = {
  queryClient: QueryClient;
  sessionId?: string;
  draft?: string;
  attachments: ComposerImageAttachment[];
  mutations: ChatComposerTurnMutations;
  onErrors?: (errors: Record<string, string>) => void;
  onDrafts?: (drafts: Record<string, string>) => void;
};

function Harness({
  queryClient,
  sessionId = "session-1",
  draft = "带图提问",
  attachments,
  mutations,
  onErrors,
  onDrafts,
}: HarnessProps) {
  const [sessionDrafts, setSessionDrafts] = useState<Record<string, string>>({
    [sessionId]: draft,
  });
  const [sessionImageAttachments, setSessionImageAttachments] = useState<Record<string, ComposerImageAttachment[]>>({
    [sessionId]: attachments,
  });
  const imageUploadInFlightRef = useRef<Record<string, boolean>>({});
  const detail = queryClient.getQueryData<SessionDetail>(queryKeys.session(sessionId));
  const actions = useChatComposerSubmitActions({
    queryClient,
    lang: "zh",
    describeError: (error, fallback) => (error instanceof Error ? error.message : fallback),
    submitTurnMutation: mutations.submitTurnMutation,
    editResubmitMutation: mutations.editResubmitMutation,
    regenerateMutation: mutations.regenerateMutation,
    stopTurnMutation: mutations.stopTurnMutation,
    sessionGuidanceMutation: mutations.sessionGuidanceMutation,
    setSessionDrafts: (value) => {
      setSessionDrafts(value);
      if (typeof value === "function") {
        onDrafts?.(value(sessionDrafts));
      } else {
        onDrafts?.(value);
      }
    },
    sessionFollowupQueues: {},
    setSessionComposerErrors: (value) => {
      if (typeof value === "function") {
        onErrors?.(value({}));
      } else {
        onErrors?.(value);
      }
    },
    setSessionImageAttachments,
    setSessionReferenceAttachments: () => undefined,
    setSessionImageUploadPending: () => undefined,
    setSessionEditTargets: () => undefined,
    imageUploadInFlightRef,
    activeSessionId: sessionId,
    activeDraftEffective: sessionDrafts[sessionId] ?? "",
    activeImageAttachments: sessionImageAttachments[sessionId] ?? [],
    activeReferenceAttachments: [],
    mentalModelEnabledForNextTurn: false,
    runtimeStatusEnabledForNextTurn: false,
    resolvedEditTarget: null,
    activeEditTarget: null,
    composerDisabled: false,
    sessionBusy: false,
    sessionStopping: false,
    activePhase: "ready",
    activeAgentImageInputUnsupported: false,
    activeImageInputModelId: "model-1",
    latestUserMessageId: "user-1",
    activeTurnId: undefined,
    detail,
    setMentalModelEnabledForNextTurn: () => undefined,
    setRuntimeStatusEnabledForNextTurn: () => undefined,
  });
  return (
    <div>
      <output data-testid="draft">{sessionDrafts[sessionId] ?? ""}</output>
      <button type="button" data-testid="submit" onClick={() => actions.handleSubmitTurn()}>submit</button>
    </div>
  );
}

function MutationsWire({
  queryClient,
  children,
}: {
  queryClient: QueryClient;
  children: (mutations: ChatComposerTurnMutations) => React.ReactNode;
}) {
  return (
    <QueryClientProvider client={queryClient}>
      <MutationsInner queryClient={queryClient}>{children}</MutationsInner>
    </QueryClientProvider>
  );
}

function MutationsInner({
  queryClient,
  children,
}: {
  queryClient: QueryClient;
  children: (mutations: ChatComposerTurnMutations) => React.ReactNode;
}) {
  const [layers, setLayers] = useState<Record<string, unknown>>({});
  const mutations = useChatComposerTurnMutations({
    queryClient,
    chatWorkspaceCache: createChatWorkspaceCache(queryClient),
    t: ((key: string) => key) as never,
    describeError: (error, fallback) => (error instanceof Error ? error.message : fallback),
    syncSessionDetail: () => undefined,
    setActiveTurnLayersBySession: setLayers as never,
    setSessionDrafts: () => undefined,
    setSessionComposerErrors: () => undefined,
    setSessionImageAttachments: () => undefined,
    setSessionReferenceAttachments: () => undefined,
    setSessionEditTargets: () => undefined,
  });
  return <>{children(mutations)}</>;
}

const roots: Root[] = [];
function mount(ui: React.ReactElement): HTMLElement {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  roots.push(root);
  act(() => {
    root.render(ui);
  });
  return container;
}

afterEach(() => {
  for (const root of roots.splice(0)) {
    act(() => {
      root.unmount();
    });
  }
  document.body.innerHTML = "";
  vi.clearAllMocks();
});

describe("useChatComposerSubmit blocked upload batch", () => {
  it("removes the optimistic user row when a batch upload failure blocks the submit", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    seedSessionDetail(queryClient, "session-1");
    let latestErrors: Record<string, string> = {};
    let mutationsRef: ChatComposerTurnMutations | undefined;

    mount(
      <MutationsWire queryClient={queryClient}>
        {(mutations) => {
          mutationsRef = mutations;
          return (
            <Harness
              queryClient={queryClient}
              attachments={[makeAttachment("good.png"), makeAttachment("bad.png")]}
              mutations={mutations}
              onErrors={(errors) => {
                latestErrors = errors;
              }}
            />
          );
        }}
      </MutationsWire>,
    );

    const submitButton = document.querySelector('[data-testid="submit"]') as HTMLButtonElement;
    await act(async () => {
      submitButton.click();
      await Promise.resolve();
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    // allSettled 闸门：批次被拦，不得创建 turn。
    expect(submitSessionMessageMock).not.toHaveBeenCalled();
    // 被拦批次必须同步移除乐观用户行。
    expect(optimisticRows(queryClient, "session-1")).toHaveLength(0);
    // 失败提示出现。
    expect(Object.values(latestErrors).some((value) => value.includes("bad.png"))).toBe(true);

    void mutationsRef;
  });

  it("keeps the optimistic row pending-replaced when the send succeeds", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    seedSessionDetail(queryClient, "session-1");

    mount(
      <MutationsWire queryClient={queryClient}>
        {(mutations) => (
          <Harness
            queryClient={queryClient}
            attachments={[makeAttachment("good.png")]}
            mutations={mutations}
          />
        )}
      </MutationsWire>,
    );

    const submitButton = document.querySelector('[data-testid="submit"]') as HTMLButtonElement;
    await act(async () => {
      submitButton.click();
      await Promise.resolve();
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    expect(submitSessionMessageMock).toHaveBeenCalledTimes(1);
    const detail = queryClient.getQueryData<SessionDetail>(queryKeys.session("session-1"));
    const submittedRow = (detail?.messages ?? []).find(
      (message) => message.metadata?.clientSubmissionId && message.metadata.clientSubmissionId !== "submission-history-1",
    );
    expect(submittedRow).toBeDefined();
    expect(submittedRow?.metadata?.pending).toBe(false);
    expect(submittedRow?.metadata?.turnId).toBe("turn-accepted-1");
  });

  it("removes the blocked optimistic row even when a poll refetch lands mid-upload and after removal", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    seedSessionDetail(queryClient, "session-1");
    // Server truth: same committed history, never the optimistic row.
    const serverDetail = {
      id: "session-1",
      status: "idle",
      currentPhase: "ready",
      messages: [
        {
          id: "session-1-message-1",
          role: "user",
          content: "已有的历史消息",
          timestamp: "2026-09-28T00:00:00.000Z",
          metadata: { clientSubmissionId: "submission-history-1" },
        },
      ],
      messageWindow: {
        totalMessages: 1,
        returnedMessages: 1,
        oldestMessageIndex: 1,
        newestMessageIndex: 1,
        hasEarlier: false,
        hasLater: false,
        nextBeforeMessageIndex: null,
      },
    } as unknown as SessionDetail;
    let resolveGoodUpload: ((value: { artifactId: string }) => void) | undefined;
    uploadGate = () => new Promise((resolve) => {
      resolveGoodUpload = resolve;
    });
    let refetchFn: (() => Promise<unknown>) | undefined;

    function QueryProbe() {
      const query = useQuery({
        queryKey: queryKeys.session("session-1"),
        queryFn: async () => serverDetail,
        structuralSharing,
        staleTime: 0,
        refetchInterval: false,
      });
      refetchFn = query.refetch;
      return null;
    }

    mount(
      <QueryClientProvider client={queryClient}>
        <QueryProbe />
        <MutationsInner queryClient={queryClient}>
          {(mutations) => (
            <Harness
              queryClient={queryClient}
              attachments={[makeAttachment("good.png"), makeAttachment("bad.png")]}
              mutations={mutations}
            />
          )}
        </MutationsInner>
      </QueryClientProvider>,
    );

    const submitButton = document.querySelector('[data-testid="submit"]') as HTMLButtonElement;
    await act(async () => {
      submitButton.click();
      await Promise.resolve();
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    // Poll commit lands while the upload batch is still in flight.
    await act(async () => {
      await refetchFn?.();
    });
    expect(optimisticRows(queryClient, "session-1")).toHaveLength(1);

    // Batch settles (good resolves, bad already rejected) -> blocked path runs.
    await act(async () => {
      resolveGoodUpload?.({ artifactId: "artifact-good.png" });
      await Promise.resolve();
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(submitSessionMessageMock).not.toHaveBeenCalled();
    expect(optimisticRows(queryClient, "session-1")).toHaveLength(0);

    // A post-failure poll commit must not resurrect the removed row.
    await act(async () => {
      await refetchFn?.();
    });
    expect(optimisticRows(queryClient, "session-1")).toHaveLength(0);

    uploadGate = null;
  });

  it("removes the optimistic row when the real send fails under the merge-based structural sharing", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    seedSessionDetail(queryClient, "session-1");
    submitSessionMessageMock.mockRejectedValueOnce(new Error("backend rejected"));
    const serverDetail = {
      id: "session-1",
      status: "idle",
      currentPhase: "ready",
      messages: [
        {
          id: "session-1-message-1",
          role: "user",
          content: "已有的历史消息",
          timestamp: "2026-09-28T00:00:00.000Z",
          metadata: { clientSubmissionId: "submission-history-1" },
        },
      ],
      messageWindow: {
        totalMessages: 1,
        returnedMessages: 1,
        oldestMessageIndex: 1,
        newestMessageIndex: 1,
        hasEarlier: false,
        hasLater: false,
        nextBeforeMessageIndex: null,
      },
    } as unknown as SessionDetail;
    let refetchFn: (() => Promise<unknown>) | undefined;

    function QueryProbe() {
      const query = useQuery({
        queryKey: queryKeys.session("session-1"),
        queryFn: async () => serverDetail,
        structuralSharing,
        staleTime: 0,
        refetchInterval: false,
      });
      refetchFn = query.refetch;
      return null;
    }

    mount(
      <QueryClientProvider client={queryClient}>
        <QueryProbe />
        <MutationsInner queryClient={queryClient}>
          {(mutations) => (
            <Harness
              queryClient={queryClient}
              attachments={[makeAttachment("good.png")]}
              mutations={mutations}
            />
          )}
        </MutationsInner>
      </QueryClientProvider>,
    );

    const submitButton = document.querySelector('[data-testid="submit"]') as HTMLButtonElement;
    await act(async () => {
      submitButton.click();
      await Promise.resolve();
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    // Upload succeeded, the send itself failed: the rollback must survive the
    // workbench's union merge (same resurrection channel as the blocked path).
    expect(submitSessionMessageMock).toHaveBeenCalledTimes(1);
    expect(optimisticRows(queryClient, "session-1")).toHaveLength(0);

    // A post-failure poll commit must not resurrect the removed row.
    await act(async () => {
      await refetchFn?.();
    });
    expect(optimisticRows(queryClient, "session-1")).toHaveLength(0);
  });
});

void uploadSessionImageAttachmentMock;
type UnusedReferences = SessionReferenceAttachment;
void (0 as unknown as UnusedReferences | undefined);
