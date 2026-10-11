/** @vitest-environment happy-dom */
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import React, { act, createContext, useContext, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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
import { conversationMessageToAgentMessage } from "../../agent-thread/adapters";
import { agentMessageContextSections } from "../../components/conversation/agentMessageSections";
import { AgentContextSectionsView } from "../../components/conversation/AgentContextSectionsView";

/** Mirrors ChatCodingRouteWorkbench.sessionDetailStructuralSharing without importing the workbench. */
function structuralSharing(previous: unknown, next: unknown): SessionDetail {
  return mergeSessionDetailMessageWindow(previous as SessionDetail | undefined, next as SessionDetail);
}

vi.mock("./chatSubmitTelemetry", () => ({
  postSubmitTelemetry: vi.fn(),
}));
vi.mock("../../app/userActionTelemetry", () => ({
  startUserAction: () => ({ succeeded: vi.fn(), failed: vi.fn(), blocked: vi.fn() }),
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
  nextReference?: SessionReferenceAttachment;
  mutations: ChatComposerTurnMutations;
  onErrors?: (errors: Record<string, string>) => void;
  onDrafts?: (drafts: Record<string, string>) => void;
};

type SessionReferenceState = {
  references: Record<string, SessionReferenceAttachment[]>;
  setReferences: Dispatch<SetStateAction<Record<string, SessionReferenceAttachment[]>>>;
};

const SessionReferenceStateContext = createContext<SessionReferenceState | null>(null);

function Harness({
  queryClient,
  sessionId = "session-1",
  draft = "带图提问",
  attachments,
  nextReference,
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
  const referenceState = useContext(SessionReferenceStateContext);
  if (!referenceState) throw new Error("Harness requires the session reference state provider.");
  const { references: sessionReferenceAttachments, setReferences: setSessionReferenceAttachments } = referenceState;
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
    setSessionReferenceAttachments,
    setSessionImageUploadPending: () => undefined,
    setSessionEditTargets: () => undefined,
    imageUploadInFlightRef,
    activeSessionId: sessionId,
    activeDraftEffective: sessionDrafts[sessionId] ?? "",
    activeImageAttachments: sessionImageAttachments[sessionId] ?? [],
    activeReferenceAttachments: sessionReferenceAttachments[sessionId] ?? [],
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
      <output data-testid="tray">{JSON.stringify((sessionImageAttachments[sessionId] ?? []).map(({ filename, uploadStatus, artifactId }) => ({ filename, uploadStatus, artifactId })))}</output>
      <output data-testid="references">{JSON.stringify(sessionReferenceAttachments[sessionId] ?? [])}</output>
      <button type="button" data-testid="submit" onClick={() => actions.handleSubmitTurn()}>submit</button>
      <button type="button" data-testid="add-next" onClick={() => actions.handleAddComposerAttachments([new File(["next"], "next.png", { type: "image/png" })])}>add</button>
      <button type="button" data-testid="add-reference" onClick={() => {
        if (nextReference) actions.handleAddComposerReference(nextReference);
      }}>add reference</button>
      <button type="button" data-testid="replace-reference" onClick={() => {
        actions.handleRemoveComposerReference("message:source-1");
        if (nextReference) actions.handleAddComposerReference(nextReference);
      }}>replace reference</button>
    </div>
  );
}

function MutationsWire({
  queryClient,
  initialReferenceAttachments = {},
  children,
}: {
  queryClient: QueryClient;
  initialReferenceAttachments?: Record<string, SessionReferenceAttachment[]>;
  children: (mutations: ChatComposerTurnMutations) => React.ReactNode;
}) {
  return (
    <QueryClientProvider client={queryClient}>
      <MutationsInner queryClient={queryClient} initialReferenceAttachments={initialReferenceAttachments}>{children}</MutationsInner>
    </QueryClientProvider>
  );
}

function MutationsInner({
  queryClient,
  initialReferenceAttachments = {},
  children,
}: {
  queryClient: QueryClient;
  initialReferenceAttachments?: Record<string, SessionReferenceAttachment[]>;
  children: (mutations: ChatComposerTurnMutations) => React.ReactNode;
}) {
  const [layers, setLayers] = useState<Record<string, unknown>>({});
  const [references, setReferences] = useState(initialReferenceAttachments);
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
    setSessionReferenceAttachments: setReferences,
    setSessionEditTargets: () => undefined,
  });
  return (
    <SessionReferenceStateContext.Provider value={{ references, setReferences }}>
      {children(mutations)}
    </SessionReferenceStateContext.Provider>
  );
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

beforeEach(() => {
  uploadGate = null;
  submitSessionMessageMock.mockResolvedValue({ turnId: "turn-accepted-1", acceptedAt: "2026-09-28T00:00:00.000Z" });
});

afterEach(() => {
  for (const root of roots.splice(0)) {
    act(() => {
      root.unmount();
    });
  }
  document.body.innerHTML = "";
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

describe("useChatComposerSubmit blocked upload batch", () => {
  it("moves an image-only submission into the conversation before upload resolves", async () => {
    const client = new QueryClient();
    seedSessionDetail(client, "session-1");
    let finish!: (result: { artifactId: string }) => void;
    uploadGate = () => new Promise((resolve) => { finish = resolve; });
    const mounted = mount(<MutationsWire queryClient={client}>{(mutations) =>
      <Harness queryClient={client} draft="" attachments={[makeAttachment("good.png")]} mutations={mutations} />
    }</MutationsWire>);
    act(() => (mounted.querySelector('[data-testid="submit"]') as HTMLButtonElement).click());
    const row = optimisticRows(client, "session-1")[0];
    expect(row?.content).toBe("");
    expect(row?.attachments?.[0]).toMatchObject({ filename: "good.png", kind: "user_image", imageUrl: expect.stringMatching(/^blob:/) });
    const html = renderToStaticMarkup(<AgentContextSectionsView sections={agentMessageContextSections(conversationMessageToAgentMessage(row))} lang="zh" />);
    expect(html).toContain('alt="good.png"');
    expect(html).toContain(row.attachments![0].imageUrl);
    expect(mounted.querySelector('[data-testid="tray"]')?.textContent).toBe("[]");
    expect(submitSessionMessageMock).not.toHaveBeenCalled();
    await act(async () => { finish({ artifactId: "uploaded-1" }); await new Promise((resolve) => setTimeout(resolve, 0)); });
    expect(submitSessionMessageMock).toHaveBeenCalledWith("session-1", expect.objectContaining({ attachmentIds: ["uploaded-1"] }));
    client.clear();
  });

  it("keeps message previews until canonical reconciliation and preserves newly added draft images", async () => {
    const client = new QueryClient();
    seedSessionDetail(client, "session-1");
    const revoke = vi.spyOn(URL, "revokeObjectURL");
    let accept!: (result: SessionTurnAcceptedResponse) => void;
    submitSessionMessageMock.mockImplementationOnce(() => new Promise((resolve) => { accept = resolve; }));
    const mounted = mount(<MutationsWire queryClient={client}>{(mutations) =>
      <Harness queryClient={client} attachments={[makeAttachment("good.png")]} mutations={mutations} />
    }</MutationsWire>);
    await act(async () => { (mounted.querySelector('[data-testid="submit"]') as HTMLButtonElement).click(); await new Promise((resolve) => setTimeout(resolve, 0)); });
    const pending = optimisticRows(client, "session-1")[0];
    const preview = pending.attachments![0].imageUrl;
    expect(pending.metadata?.pending).toBe(true);
    act(() => (mounted.querySelector('[data-testid="add-next"]') as HTMLButtonElement).click());
    await act(async () => { accept({ turnId: "accepted", acceptedAt: new Date().toISOString() }); await new Promise((resolve) => setTimeout(resolve, 0)); });
    expect(optimisticRows(client, "session-1")[0].metadata?.pending).toBe(false);
    expect(revoke).not.toHaveBeenCalledWith(preview);
    expect(mounted.querySelector('[data-testid="tray"]')?.textContent).toContain("next.png");
    const current = client.getQueryData<SessionDetail>(queryKeys.session("session-1"))!;
    const canonical = { ...pending, id: "canonical-user", metadata: { clientSubmissionId: pending.metadata?.clientSubmissionId }, attachments: [{ ...pending.attachments![0], artifactId: "stored", imageUrl: "/stored.png", url: "/stored.png" }] };
    act(() => client.setQueryData(queryKeys.session("session-1"), mergeSessionDetailMessageWindow(current, { ...current, messages: [canonical] })));
    expect(optimisticRows(client, "session-1")).toHaveLength(0);
    expect(revoke).toHaveBeenCalledWith(preview);
    expect(client.getQueryData<SessionDetail>(queryKeys.session("session-1"))?.messages.filter((message) => message.metadata?.clientSubmissionId === pending.metadata?.clientSubmissionId)).toHaveLength(1);
    client.clear();
  });

  it.each([
    ["same message with a new quote", "requoted"],
    ["a different reference", "different"],
  ] as const)("clears only the submitted snapshot when %s is added during send", async (_description, mode) => {
    const client = new QueryClient();
    seedSessionDetail(client, "session-1");
    const submittedReference: SessionReferenceAttachment = {
      referenceId: "message:source-1",
      kind: "message",
      sourceSessionId: "source-session",
      sourceMessageId: "source-1",
      quote: "the quote included in this send",
      title: "the quote included in this send",
    };
    const newlyAddedReference: SessionReferenceAttachment = mode === "requoted"
      ? {
          ...submittedReference,
          quote: "a newer quote added while sending",
          title: "a newer quote added while sending",
        }
      : {
          referenceId: "file:artifact-2",
          kind: "file",
          artifactId: "artifact-2",
          title: "new file reference",
        };
    let accept!: (result: SessionTurnAcceptedResponse) => void;
    submitSessionMessageMock.mockImplementationOnce(async (_sessionId, payload) => {
      expect(payload.references).toEqual([submittedReference]);
      return await new Promise((resolve) => { accept = resolve; });
    });
    const mounted = mount(<MutationsWire queryClient={client} initialReferenceAttachments={{ "session-1": [submittedReference] }}>{(mutations) =>
      <Harness
        queryClient={client}
        attachments={[]}
        nextReference={newlyAddedReference}
        mutations={mutations}
      />
    }</MutationsWire>);

    await act(async () => {
      (mounted.querySelector('[data-testid="submit"]') as HTMLButtonElement).click();
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(submitSessionMessageMock).toHaveBeenCalledTimes(1);
    act(() => (mounted.querySelector(`[data-testid="${mode === "requoted" ? "replace-reference" : "add-reference"}"]`) as HTMLButtonElement).click());
    expect(JSON.parse(mounted.querySelector('[data-testid="references"]')?.textContent ?? "[]"))
      .toEqual(mode === "requoted" ? [newlyAddedReference] : [submittedReference, newlyAddedReference]);

    await act(async () => {
      accept({ turnId: "accepted", acceptedAt: new Date().toISOString() });
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(JSON.parse(mounted.querySelector('[data-testid="references"]')?.textContent ?? "[]"))
      .toEqual([newlyAddedReference]);
    client.clear();
  });

  it("restores uploaded artifacts after a message POST failure and reuses them on retry", async () => {
    const client = new QueryClient();
    seedSessionDetail(client, "session-1");
    submitSessionMessageMock.mockRejectedValueOnce(new Error("network disconnected"));
    const mounted = mount(<MutationsWire queryClient={client}>{(mutations) =>
      <Harness queryClient={client} attachments={[makeAttachment("good.png")]} mutations={mutations} />
    }</MutationsWire>);
    const send = mounted.querySelector('[data-testid="submit"]') as HTMLButtonElement;
    await act(async () => { send.click(); await new Promise((resolve) => setTimeout(resolve, 0)); });
    expect(optimisticRows(client, "session-1")).toHaveLength(0);
    expect(mounted.querySelector('[data-testid="tray"]')?.textContent).toContain('"uploadStatus":"uploaded"');
    await act(async () => { send.click(); await new Promise((resolve) => setTimeout(resolve, 0)); });
    expect(uploadSessionImageAttachmentMock).toHaveBeenCalledTimes(1);
    expect(submitSessionMessageMock).toHaveBeenCalledTimes(2);
    client.clear();
  });

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
    const tray = document.querySelector('[data-testid="tray"]')?.textContent ?? "";
    expect(tray).toContain('"uploadStatus":"uploaded"');
    expect(tray).toContain('"uploadStatus":"failed"');

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
