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
import { submitVirtualHumanConversationMessage } from "../../api/virtualHumanLife";
import {
  createChatWorkspaceCache,
} from "../chatWorkspaceCache";
import type { ComposerImageAttachment } from "./chatComposerSubmitModel";
import {
  useChatComposerSubmitActions,
  useChatComposerTurnMutations,
  type ChatComposerTurnMutations,
  type SubmitTurnVariables,
} from "./useChatComposerSubmit";
import { mergeSessionDetailMessageWindow } from "../chatSessionState";
import { fetchSessionDetailWindow } from "./chatSessionDetailHelpers";
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
vi.mock("../../api/virtualHumanLife", async (importOriginal) => ({
  ...await importOriginal<typeof import("../../api/virtualHumanLife")>(),
  submitVirtualHumanConversationMessage: vi.fn(async () => {
    throw new Error("companion mailbox rejected");
  }),
}));
vi.mock("./chatSessionDetailHelpers", async (importOriginal) => ({
  ...await importOriginal<typeof import("./chatSessionDetailHelpers")>(),
  fetchSessionDetailWindow: vi.fn(),
}));

/** Per-test gate to hold a successful upload in flight (interleave poll commits). */
let uploadGate: ((attachment: ComposerImageAttachment) => Promise<{ artifactId: string }>) | null = null;

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const uploadSessionImageAttachmentMock = vi.mocked(uploadSessionImageAttachment);
const submitSessionMessageMock = vi.mocked(submitSessionMessage);
const submitVirtualHumanConversationMessageMock = vi.mocked(submitVirtualHumanConversationMessage);
const originalCreateObjectURL = Object.getOwnPropertyDescriptor(URL, "createObjectURL");
const originalRevokeObjectURL = Object.getOwnPropertyDescriptor(URL, "revokeObjectURL");
let nextObjectUrlId = 0;
const createObjectURLMock = vi.fn<(file: File) => string>();
const revokeObjectURLMock = vi.fn<(url: string) => void>();

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
  allowSessionSwitch?: boolean;
  companionAgentId?: string;
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
  allowSessionSwitch = false,
  companionAgentId,
  mutations,
  onErrors,
  onDrafts,
}: HarnessProps) {
  const [activeSessionId, setActiveSessionId] = useState(sessionId);
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
  const detail = queryClient.getQueryData<SessionDetail>(queryKeys.session(activeSessionId));
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
    companionAgentId,
    imageUploadInFlightRef,
    activeSessionId,
    activeDraftEffective: sessionDrafts[activeSessionId] ?? "",
    activeImageAttachments: sessionImageAttachments[activeSessionId] ?? [],
    activeReferenceAttachments: sessionReferenceAttachments[activeSessionId] ?? [],
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
      {allowSessionSwitch && <output data-testid="active-session">{activeSessionId}</output>}
      <output data-testid="draft">{sessionDrafts[activeSessionId] ?? ""}</output>
      <output data-testid="tray">{JSON.stringify((sessionImageAttachments[activeSessionId] ?? []).map(({ id, filename, previewUrl, uploadStatus, artifactId }) => ({ id, filename, previewUrl, uploadStatus, artifactId })))}</output>
      <output data-testid="references">{JSON.stringify(sessionReferenceAttachments[activeSessionId] ?? [])}</output>
      <button type="button" data-testid="submit" onClick={() => actions.handleSubmitTurn()}>submit</button>
      <button type="button" data-testid="add-next" onClick={() => actions.handleAddComposerAttachments([new File(["next"], "next.png", { type: "image/png" })])}>add</button>
      <button type="button" data-testid="add-later" onClick={() => actions.handleAddComposerAttachments([new File(["later"], "later.png", { type: "image/png" })])}>add later</button>
      {allowSessionSwitch && <>
        <button type="button" data-testid="write-b" onClick={() => actions.handleComposerChange("B 的消息")}>write B</button>
        <button type="button" data-testid="switch-to-b" onClick={() => setActiveSessionId("session-2")}>switch to B</button>
        <button type="button" data-testid="switch-to-a" onClick={() => setActiveSessionId(sessionId)}>switch to A</button>
      </>}
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
  companionAgentId,
  onSubmitVariables,
  children,
}: {
  queryClient: QueryClient;
  initialReferenceAttachments?: Record<string, SessionReferenceAttachment[]>;
  companionAgentId?: string;
  onSubmitVariables?: (variables: SubmitTurnVariables) => void;
  children: (mutations: ChatComposerTurnMutations) => React.ReactNode;
}) {
  return (
    <QueryClientProvider client={queryClient}>
      <MutationsInner
        queryClient={queryClient}
        initialReferenceAttachments={initialReferenceAttachments}
        companionAgentId={companionAgentId}
        onSubmitVariables={onSubmitVariables}
      >{children}</MutationsInner>
    </QueryClientProvider>
  );
}

function MutationsInner({
  queryClient,
  initialReferenceAttachments = {},
  companionAgentId,
  onSubmitVariables,
  children,
}: {
  queryClient: QueryClient;
  initialReferenceAttachments?: Record<string, SessionReferenceAttachment[]>;
  companionAgentId?: string;
  onSubmitVariables?: (variables: SubmitTurnVariables) => void;
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
    companionAgentId,
  });
  const wiredMutations: ChatComposerTurnMutations = {
    ...mutations,
    submitTurnMutation: {
      ...mutations.submitTurnMutation,
      mutate: (...args: Parameters<typeof mutations.submitTurnMutation.mutate>) => {
        onSubmitVariables?.(args[0]);
        mutations.submitTurnMutation.mutate(...args);
      },
    },
  };
  return (
    <SessionReferenceStateContext.Provider value={{ references, setReferences }}>
      {children(wiredMutations)}
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
  nextObjectUrlId = 0;
  createObjectURLMock.mockReset().mockImplementation((file) => `blob:test-${file.name}-${++nextObjectUrlId}`);
  revokeObjectURLMock.mockReset();
  Object.defineProperty(URL, "createObjectURL", { configurable: true, value: createObjectURLMock });
  Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: revokeObjectURLMock });
  submitSessionMessageMock.mockResolvedValue({ turnId: "turn-accepted-1", acceptedAt: "2026-09-28T00:00:00.000Z" });
  submitVirtualHumanConversationMessageMock.mockRejectedValue(new Error("companion mailbox rejected"));
  vi.mocked(fetchSessionDetailWindow).mockReset().mockRejectedValue(new Error("readback unavailable"));
});

afterEach(() => {
  for (const root of roots.splice(0)) {
    act(() => {
      root.unmount();
    });
  }
  if (originalCreateObjectURL) {
    Object.defineProperty(URL, "createObjectURL", originalCreateObjectURL);
  } else {
    Reflect.deleteProperty(URL, "createObjectURL");
  }
  if (originalRevokeObjectURL) {
    Object.defineProperty(URL, "revokeObjectURL", originalRevokeObjectURL);
  } else {
    Reflect.deleteProperty(URL, "revokeObjectURL");
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

  it("keeps Companion mailbox failures off the native Session acceptance readback path", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    seedSessionDetail(client, "session-1");
    const mounted = mount(<MutationsWire queryClient={client} companionAgentId="agent-companion">{(mutations) =>
      <Harness
        queryClient={client}
        draft="Companion 消息"
        attachments={[]}
        companionAgentId="agent-companion"
        mutations={mutations}
      />
    }</MutationsWire>);

    await act(async () => {
      (mounted.querySelector('[data-testid="submit"]') as HTMLButtonElement).click();
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    expect(submitVirtualHumanConversationMessageMock).toHaveBeenCalledWith(
      "agent-companion",
      "session-1",
      expect.objectContaining({ content: "Companion 消息" }),
    );
    expect(submitSessionMessageMock).not.toHaveBeenCalled();
    expect(fetchSessionDetailWindow).not.toHaveBeenCalled();
    expect(optimisticRows(client, "session-1")).toHaveLength(0);
    client.clear();
  });

  it("releases each concurrent submit's own image owners and preserves a later draft image", async () => {
    const client = new QueryClient();
    seedSessionDetail(client, "session-1");
    seedSessionDetail(client, "session-2");
    let acceptSessionA!: (result: SessionTurnAcceptedResponse) => void;
    let acceptSessionB!: (result: SessionTurnAcceptedResponse) => void;
    submitSessionMessageMock.mockImplementation((sessionId) => new Promise((resolve) => {
      if (sessionId === "session-1") {
        acceptSessionA = resolve;
      } else {
        acceptSessionB = resolve;
      }
    }));
    const releaseCallbacksBySession = new Map<string, ReturnType<typeof vi.fn>>();
    const submittedVariablesBySession = new Map<string, SubmitTurnVariables>();
    const mounted = mount(<MutationsWire
      queryClient={client}
      onSubmitVariables={(variables) => {
        submittedVariablesBySession.set(variables.sessionId, variables);
        const release = variables.releaseComposerAttachmentOwners;
        if (release) {
          const releaseSpy = vi.fn(release);
          variables.releaseComposerAttachmentOwners = releaseSpy;
          releaseCallbacksBySession.set(variables.sessionId, releaseSpy);
        }
      }}
    >{(mutations) =>
      <Harness
        queryClient={client}
        attachments={[makeAttachment("A.png")]}
        allowSessionSwitch
        mutations={mutations}
      />
    }</MutationsWire>);

    await act(async () => {
      (mounted.querySelector('[data-testid="submit"]') as HTMLButtonElement).click();
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(submitSessionMessageMock).toHaveBeenCalledWith("session-1", expect.objectContaining({ attachmentIds: ["artifact-A.png"] }));

    act(() => (mounted.querySelector('[data-testid="switch-to-b"]') as HTMLButtonElement).click());
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
    act(() => (mounted.querySelector('[data-testid="write-b"]') as HTMLButtonElement).click());
    const bImageCreateStart = createObjectURLMock.mock.calls.length;
    act(() => (mounted.querySelector('[data-testid="add-next"]') as HTMLButtonElement).click());
    const bSubmittedFile = createObjectURLMock.mock.calls.slice(bImageCreateStart).find(([file]) => file.name === "next.png")?.[0];
    expect(bSubmittedFile).toBeInstanceOf(File);
    const bSubmittedRows = JSON.parse(mounted.querySelector('[data-testid="tray"]')?.textContent ?? "[]") as Array<{ previewUrl: string }>;
    const bSubmittedPreview = bSubmittedRows[0]?.previewUrl;
    expect(bSubmittedPreview).toMatch(/^blob:/);
    await act(async () => {
      (mounted.querySelector('[data-testid="submit"]') as HTMLButtonElement).click();
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(submitSessionMessageMock).toHaveBeenCalledWith("session-2", expect.objectContaining({
      content: "B 的消息",
      attachmentIds: ["artifact-next.png"],
    }));
    const variablesA = submittedVariablesBySession.get("session-1");
    const variablesB = submittedVariablesBySession.get("session-2");
    const releaseA = releaseCallbacksBySession.get("session-1");
    const releaseB = releaseCallbacksBySession.get("session-2");
    expect(variablesA?.releaseComposerAttachmentOwners).toBe(releaseA);
    expect(variablesB?.releaseComposerAttachmentOwners).toBe(releaseB);
    expect(releaseA).toEqual(expect.any(Function));
    expect(releaseB).toEqual(expect.any(Function));
    expect(releaseA).not.toBe(releaseB);
    expect(acceptSessionA).toEqual(expect.any(Function));
    expect(acceptSessionB).toEqual(expect.any(Function));
    const aPreviewReleaseCountBeforeAcceptance = revokeObjectURLMock.mock.calls.filter(([url]) => url === "blob:A.png").length;

    // B resolves first. Its mutation may release B's submitted owner once, but
    // it must leave A's still-pending submission untouched.
    await act(async () => {
      acceptSessionB({ turnId: "turn-b", acceptedAt: new Date().toISOString() });
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(releaseB).toHaveBeenCalledTimes(1);
    expect(releaseA).not.toHaveBeenCalled();
    expect(revokeObjectURLMock.mock.calls.filter(([url]) => url === bSubmittedPreview)).toHaveLength(1);
    expect(revokeObjectURLMock.mock.calls.filter(([url]) => url === "blob:A.png")).toHaveLength(aPreviewReleaseCountBeforeAcceptance);

    const createCallsBeforeLaterImage = createObjectURLMock.mock.calls.length;
    act(() => (mounted.querySelector('[data-testid="add-later"]') as HTMLButtonElement).click());
    const bLaterFile = createObjectURLMock.mock.calls.slice(createCallsBeforeLaterImage).find(([file]) => file.name === "later.png")?.[0];
    expect(bLaterFile).toBeInstanceOf(File);
    const beforeAcceptRows = JSON.parse(mounted.querySelector('[data-testid="tray"]')?.textContent ?? "[]") as Array<{ previewUrl: string }>;
    const bLaterPreview = beforeAcceptRows[0]?.previewUrl;
    expect(bLaterPreview).toMatch(/^blob:/);

    // A completes after B. The callback captured by A's actual mutation must
    // release A and must not release B's newly added draft owner again.
    await act(async () => {
      acceptSessionA({ turnId: "turn-a", acceptedAt: new Date().toISOString() });
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(releaseA).toHaveBeenCalledTimes(1);
    expect(releaseB).toHaveBeenCalledTimes(1);
    expect(revokeObjectURLMock.mock.calls.filter(([url]) => url === "blob:A.png")).toHaveLength(aPreviewReleaseCountBeforeAcceptance);
    expect(revokeObjectURLMock.mock.calls.filter(([url]) => url === bSubmittedPreview)).toHaveLength(1);
    expect(revokeObjectURLMock).not.toHaveBeenCalledWith(bLaterPreview);
    expect(mounted.querySelector('[data-testid="active-session"]')?.textContent).toBe("session-2");
    expect(mounted.querySelector('[data-testid="tray"]')?.textContent).toContain("later.png");

    act(() => (mounted.querySelector('[data-testid="switch-to-a"]') as HTMLButtonElement).click());
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
    act(() => (mounted.querySelector('[data-testid="switch-to-b"]') as HTMLButtonElement).click());
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });

    expect(createObjectURLMock).toHaveBeenCalledWith(bLaterFile);
    const restoredRows = JSON.parse(mounted.querySelector('[data-testid="tray"]')?.textContent ?? "[]") as Array<{ previewUrl: string }>;
    expect(restoredRows[0]?.previewUrl).toMatch(/^blob:/);
    expect(restoredRows[0]?.previewUrl).not.toBe(bLaterPreview);
    expect(revokeObjectURLMock.mock.calls.filter(([url]) => url === bLaterPreview)).toHaveLength(1);
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
