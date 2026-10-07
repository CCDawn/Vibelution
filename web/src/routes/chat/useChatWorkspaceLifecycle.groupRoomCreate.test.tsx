// @vitest-environment happy-dom
/**
 * Group-room optimistic create shell (same skeleton as the session create path):
 * - clicking create enters a temp room shell immediately (no POST wait);
 * - success rebases temp → real id only while the user still views the temp
 *   room (compare-and-swap; cache-only when they already left);
 * - failure rolls the shell back and surfaces the error without closing the
 *   composer drafts.
 */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import type { InfiniteData, MutableRefObject } from "@tanstack/react-query";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createChatSession } from "../../api/chat";
import { queryKeys } from "../../api/queryKeys";
import type {
  ChatRoomDetail,
  ConversationQueryFilters,
  ConversationQueryResponse,
  ConversationSummary,
  SessionDetail,
  SessionSummary,
} from "../../api/types";
import { isSessionCreatePreserved, resetSessionCreatePreservesForTests } from "../sessionCreatePreserve";
import { isSessionDeleteTombstoned, resetSessionDeleteTombstonesForTests } from "../sessionDeleteTombstone";
import type { TranslationKey } from "../../i18n/dictionary";
import { chatRouteSelectionsEqual, type ChatRouteSelection } from "./chatSelectionProjection";
import { lastSessionForAgent, readAgentLastSessionMap, rememberAgentLastSession } from "./chatAgentSessionMemory";
import {
  createTempRoomId,
  isTempRoomId,
} from "../groupRoomOptimisticIds";
import { useChatWorkspaceLifecycle } from "./useChatWorkspaceLifecycle";
import { readSessionCreateRecovery } from "./chatSessionCreateRecovery";

const fetchJsonMock = vi.fn();
vi.mock("../../api/client", () => ({
  fetchJson: (...args: unknown[]) => fetchJsonMock(...args),
  isFetchJsonHttpError: (error: unknown) => error instanceof Error && typeof (error as Error & { status?: unknown }).status === "number",
}));

type TelemetryEvent = {
  name: unknown;
  payload: unknown;
  succeeded: ReturnType<typeof vi.fn>;
  failed: ReturnType<typeof vi.fn>;
  blocked: ReturnType<typeof vi.fn>;
};

const telemetryEvents: TelemetryEvent[] = [];
vi.mock("../../app/userActionTelemetry", () => ({
  startUserAction: (name: unknown, payload: unknown) => {
    const event: TelemetryEvent = {
      name,
      payload,
      succeeded: vi.fn(),
      failed: vi.fn(),
      blocked: vi.fn(),
    };
    telemetryEvents.push(event);
    return event;
  },
}));

type LifecycleResult = ReturnType<typeof useChatWorkspaceLifecycle>;

let root: Root | null = null;
let container: HTMLElement;
let queryClient: QueryClient;
let resultRef: LifecycleResult | null = null;
let hookOptions: ReturnType<typeof buildOptions> | null = null;

function createDeferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  // The mutation consumes the promise; the noop catch only guards the window
  // before react-query attaches its own handlers.
  promise.catch(() => undefined);
  return { promise, resolve, reject };
}

function buildOptions(route: ReturnType<typeof buildRouteStub>) {
  const composerErrors: Record<string, string> = {};
  return {
    route,
    composerErrors,
    options: {
      queryClient,
      chatWorkspaceCache: {
        afterChatRoomChanged: vi.fn(),
        afterSessionDeleted: vi.fn(),
      },
      lang: "zh" as const,
      t: (key: TranslationKey) => key,
      describeError: (error: unknown, fallback: string) =>
        String((error as Error)?.message || fallback),
      syncSessionDetail: vi.fn(),
      syncChatRoomDetail: vi.fn(),
      clearSessionTransientUiState: vi.fn(),
      removeSessionWorkspace: vi.fn(),
      rebaseSessionComposerState: vi.fn(),
      requestSessionComposerFocus: vi.fn(),
      routeSelectionRef: route.ref,
      chatRoute: {
        openSession: route.openSession,
        openRoom: route.openRoom,
        replaceIfStillViewing: route.replaceIfStillViewing,
      },
      setRightIndexPanel: vi.fn(),
      setSelectedAgentId: vi.fn(),
      setSessionFilter: vi.fn(),
      setSessionComposerErrors: vi.fn((update: (current: Record<string, string>) => Record<string, string>) => {
        Object.keys(composerErrors).forEach((key) => delete composerErrors[key]);
        Object.assign(composerErrors, update({ ...composerErrors }));
        return composerErrors;
      }),
      setGroupComposerOpen: vi.fn(),
      setGroupTitleDraft: vi.fn(),
      setGroupModeDraft: vi.fn(),
      setGroupPurposeDraft: vi.fn(),
      setGroupSelectedAgentIds: vi.fn(),
      setGroupTopicDraft: vi.fn(),
      setGroupRoomActionError: vi.fn(),
      setGroupManageTitleDraft: vi.fn(),
      setGroupManageSessionIds: vi.fn(),
      setGroupManageModeDraft: vi.fn(),
      setGroupManagePurposeDraft: vi.fn(),
      setProjectBusDraft: vi.fn(),
      editingSessionIdRef: { current: null } as MutableRefObject<string | null>,
      editingSessionTitleRef: { current: "" } as MutableRefObject<string>,
      setEditingSessionId: vi.fn(),
      setEditingSessionTitle: vi.fn(),
      suppressRenameBlurUntilRef: { current: 0 } as MutableRefObject<number>,
    } as unknown as Parameters<typeof useChatWorkspaceLifecycle>[0],
  };
}

function buildRouteStub(initial: ChatRouteSelection) {
  const ref: { current: ChatRouteSelection } = { current: initial };
  return {
    ref,
    openSession: vi.fn((sessionId: string) => {
      ref.current = { kind: "session", sessionId };
    }),
    openRoom: vi.fn((roomId: string) => {
      ref.current = { kind: "room", roomId };
    }),
    replaceIfStillViewing: vi.fn((expected: ChatRouteSelection, next: ChatRouteSelection) => {
      if (chatRouteSelectionsEqual(ref.current, expected)) {
        ref.current = next;
        return true;
      }
      return false;
    }),
  };
}

function Host() {
  if (hookOptions) {
    resultRef = useChatWorkspaceLifecycle(hookOptions.options);
  }
  return null;
}

function mount() {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  act(() => {
    root!.render(
      React.createElement(
        QueryClientProvider,
        { client: queryClient },
        React.createElement(Host),
      ),
    );
  });
}

async function flushMutationQueue() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

function seedConversationCatalog(items: ConversationSummary[]): void {
  const filters: ConversationQueryFilters = {
    q: "",
    agentId: "",
    teamId: "",
    type: "group_room",
    sort: "updatedAt_desc",
    limit: 100,
    cursor: "",
  };
  queryClient.setQueryData<InfiniteData<ConversationQueryResponse, string>>(
    queryKeys.conversationsCatalogQuery(),
    {
      pages: [{ items, nextCursor: "", totalEstimate: items.length, filters }],
      pageParams: [""],
    },
  );
}

function existingRoomSummary(): ConversationSummary {
  return {
    conversationId: "room-existing",
    type: "group_room",
    title: "已有群聊",
    roomId: "room-existing",
    status: "ready",
    summary: "",
    updatedAt: "2026-01-01T00:00:00.000Z",
    workspacePath: "",
    participantCount: 2,
    mode: "round_robin",
  };
}

function serverRoomFor(roomId: string): ChatRoomDetail {
  return {
    roomId,
    title: "策略组",
    mode: "round_robin",
    purpose: "discussion",
    config: {},
    participants: [
      {
        participantId: "participant-1",
        kind: "session_agent",
        agentId: "agent-a",
        sessionId: "session-a",
        title: "Agent A",
        enabled: true,
        status: "ready",
      },
      {
        participantId: "participant-2",
        kind: "session_agent",
        agentId: "agent-b",
        sessionId: "session-b",
        title: "Agent B",
        enabled: true,
        status: "ready",
      },
    ],
    rounds: [],
    status: "ready",
    activeRoundId: "",
    createdAt: "2026-01-01T00:00:00.000Z",
    updatedAt: "2026-01-01T00:00:00.000Z",
    availableModes: [],
    availablePurposes: [],
  };
}

function mutateGroupCreate(): void {
  act(() => {
    resultRef!.createGroupRoomMutation.mutate({
      title: "策略组",
      agentIds: ["agent-a", "agent-b"],
      mode: "round_robin",
      purpose: "discussion",
    });
  });
}

function mutateSessionCreate(agentId: string): void {
  act(() => {
    resultRef!.createSessionMutation.mutate({ agentId });
  });
}

function sessionCreateRequests(): RequestInit[] {
  return fetchJsonMock.mock.calls
    .filter(
      ([input, init]) =>
        input === "/api/sessions"
        && (init as RequestInit | undefined)?.method === "POST",
    )
    .map(([, init]) => init as RequestInit);
}

function sessionCreateIdempotencyKey(init: RequestInit): string | undefined {
  return (init.headers as Record<string, string> | undefined)?.["Idempotency-Key"];
}

function serverSessionFor(id: string, agentId: string): SessionDetail {
  const now = "2026-01-01T00:00:00.000Z";
  return {
    id,
    title: "新会话",
    agentId,
    status: "idle",
    currentPhase: "ready",
    taskSummary: "",
    lastActive: now,
    updatedAt: now,
    createdAt: now,
    messages: [],
    defaultFileContext: "",
    previewTabs: [],
    activePreviewPath: "",
    changedFiles: [],
    readFiles: [],
    stopRequested: false,
    stopRequestedAt: "",
    stopReason: "",
    messageWindow: {
      mode: "window",
      totalMessages: 0,
      returnedMessages: 0,
      oldestMessageIndex: 0,
      newestMessageIndex: 0,
      hasEarlier: false,
      hasLater: false,
      transcriptScope: "window",
    },
  };
}

function groupCreateTelemetry(): TelemetryEvent {
  const event = telemetryEvents.find((item) => item.name === "group_room_create");
  expect(event, "group_room_create telemetry should start with the mutation").toBeTruthy();
  return event!;
}

beforeEach(() => {
  sessionStorage.clear();
  fetchJsonMock.mockReset();
  telemetryEvents.length = 0;
  queryClient = new QueryClient();
  resultRef = null;
});

afterEach(() => {
  act(() => {
    root?.unmount();
  });
  root = null;
  container?.remove();
  resultRef = null;
  hookOptions = null;
});

describe("useChatWorkspaceLifecycle group room optimistic create", () => {
  it("enters a temp room shell immediately without waiting for the POST", async () => {
    const deferred = createDeferred<ChatRoomDetail>();
    fetchJsonMock.mockReturnValue(deferred.promise);
    const route = buildRouteStub({ kind: "bare" });
    hookOptions = buildOptions(route);
    mount();
    seedConversationCatalog([existingRoomSummary()]);

    mutateGroupCreate();
    // Let the mutation observer settle while the POST stays pending.
    await flushMutationQueue();

    const openRoomCalls = route.openRoom.mock.calls.map((call) => String(call[0]));
    expect(openRoomCalls).toHaveLength(1);
    const tempRoomId = openRoomCalls[0];
    expect(isTempRoomId(tempRoomId)).toBe(true);
    expect(route.ref.current).toEqual({ kind: "room", roomId: tempRoomId });

    // Detail seed: form fields are live, server-only fields stay placeholders.
    const shell = queryClient.getQueryData<ChatRoomDetail>(queryKeys.chatRoom(tempRoomId));
    expect(shell?.title).toBe("策略组");
    expect(shell?.mode).toBe("round_robin");
    expect(shell?.purpose).toBe("discussion");
    expect(shell?.status).toBe("ready");
    expect(shell?.rounds).toEqual([]);
    expect(shell?.participants.map((participant) => participant.agentId)).toEqual(["agent-a", "agent-b"]);
    expect(shell?.participants.every((participant) => participant.sessionId === "")).toBe(true);

    // Catalog entry: the rail paints the temp room ahead of the server list.
    const catalog = queryClient.getQueryData<InfiniteData<ConversationQueryResponse, string>>(
      queryKeys.conversationsCatalogQuery(),
    );
    expect(catalog?.pages[0]?.items[0]?.conversationId).toBe(tempRoomId);
    expect(catalog?.pages[0]?.items[0]?.type).toBe("group_room");
    expect(catalog?.pages[0]?.totalEstimate).toBe(2);

    // POST is still in flight — no waiting on the network.
    expect(resultRef!.createGroupRoomMutation.isPending).toBe(true);
    expect(fetchJsonMock).toHaveBeenCalledTimes(1);
    expect(queryClient.getQueryData(queryKeys.chatRoom("room-real"))).toBeUndefined();

    const telemetry = groupCreateTelemetry();
    expect(telemetry.payload).toEqual({ agentCount: 2, mode: "round_robin" });
    expect(telemetry.succeeded).not.toHaveBeenCalled();
    expect(telemetry.failed).not.toHaveBeenCalled();
  });

  it("rebases temp → real id with compare-and-swap on success", async () => {
    const deferred = createDeferred<ChatRoomDetail>();
    fetchJsonMock.mockReturnValue(deferred.promise);
    const route = buildRouteStub({ kind: "bare" });
    hookOptions = buildOptions(route);
    mount();
    seedConversationCatalog([existingRoomSummary()]);
    mutateGroupCreate();
    const tempRoomId = String(route.openRoom.mock.calls[0]?.[0]);
    expect(createTempRoomId()).not.toEqual(tempRoomId);

    await act(async () => {
      deferred.resolve(serverRoomFor("room-real"));
    });
    await flushMutationQueue();

    expect(route.replaceIfStillViewing).toHaveBeenCalledWith(
      { kind: "room", roomId: tempRoomId },
      { kind: "room", roomId: "room-real" },
    );
    expect(route.ref.current).toEqual({ kind: "room", roomId: "room-real" });
    expect(
      queryClient.getQueryData<ChatRoomDetail>(queryKeys.chatRoom("room-real"))?.participants.length,
    ).toBe(2);
    // Temp shell dropped after the real id is cached.
    expect(queryClient.getQueryData(queryKeys.chatRoom(tempRoomId))).toBeUndefined();
    const catalogItems = queryClient.getQueryData<InfiniteData<ConversationQueryResponse, string>>(
      queryKeys.conversationsCatalogQuery(),
    )?.pages.flatMap((page) => page.items) ?? [];
    expect(catalogItems.some((item) => isTempRoomId(item.conversationId))).toBe(false);
    expect(catalogItems.some((item) => item.roomId === "room-existing")).toBe(true);

    expect(hookOptions!.options.setGroupComposerOpen).toHaveBeenCalledWith(false);
    expect(hookOptions!.options.setGroupTitleDraft).toHaveBeenCalledWith("");
    expect(hookOptions!.route.replaceIfStillViewing).toHaveBeenCalledTimes(1);
    expect(hookOptions!.options.chatWorkspaceCache.afterChatRoomChanged).toHaveBeenCalledWith("room-real");
    const telemetry = groupCreateTelemetry();
    expect(telemetry.succeeded).toHaveBeenCalledWith(expect.objectContaining({
      roomId: "room-real",
      tempRoomId,
      routeReplacedFromTemp: true,
    }));
  });

  it("writes cache only without grabbing the route when the user already left", async () => {
    const deferred = createDeferred<ChatRoomDetail>();
    fetchJsonMock.mockReturnValue(deferred.promise);
    const route = buildRouteStub({ kind: "bare" });
    hookOptions = buildOptions(route);
    mount();
    seedConversationCatalog([existingRoomSummary()]);
    mutateGroupCreate();
    const tempRoomId = String(route.openRoom.mock.calls[0]?.[0]);
    // User switches to another tab while the POST is in flight.
    route.ref.current = { kind: "session", sessionId: "elsewhere" };

    await act(async () => {
      deferred.resolve(serverRoomFor("room-real"));
    });
    await flushMutationQueue();

    expect(route.openRoom).toHaveBeenCalledTimes(1);
    expect(route.ref.current).toEqual({ kind: "session", sessionId: "elsewhere" });
    // Real id is still cached for when the user opens the room again.
    expect(queryClient.getQueryData(queryKeys.chatRoom("room-real"))).toBeTruthy();
    expect(queryClient.getQueryData(queryKeys.chatRoom(tempRoomId))).toBeUndefined();
    const telemetry = groupCreateTelemetry();
    expect(telemetry.succeeded).toHaveBeenCalledWith(expect.objectContaining({
      routeReplacedFromTemp: false,
    }));
  });

  it("rolls the shell back and surfaces the error without closing the composer", async () => {
    const deferred = createDeferred<ChatRoomDetail>();
    fetchJsonMock.mockReturnValue(deferred.promise);
    const route = buildRouteStub({ kind: "bare" });
    hookOptions = buildOptions(route);
    mount();
    seedConversationCatalog([existingRoomSummary()]);
    mutateGroupCreate();
    const tempRoomId = String(route.openRoom.mock.calls[0]?.[0]);
    expect(hookOptions!.options.setGroupComposerOpen).not.toHaveBeenCalled();

    await act(async () => {
      deferred.reject(new Error("network down"));
    });
    await flushMutationQueue();

    // Compare-and-swap return to the pre-create route.
    expect(route.replaceIfStillViewing).toHaveBeenCalledWith(
      { kind: "room", roomId: tempRoomId },
      { kind: "bare" },
    );
    expect(route.ref.current).toEqual({ kind: "bare" });
    expect(queryClient.getQueryData(queryKeys.chatRoom(tempRoomId))).toBeUndefined();
    const catalogItems = queryClient.getQueryData<InfiniteData<ConversationQueryResponse, string>>(
      queryKeys.conversationsCatalogQuery(),
    )?.pages.flatMap((page) => page.items) ?? [];
    expect(catalogItems.some((item) => isTempRoomId(item.conversationId))).toBe(false);
    expect(catalogItems.some((item) => item.roomId === "room-existing")).toBe(true);
    // Drafts survive the failure for retry; error uses the existing chain.
    expect(hookOptions!.options.setGroupComposerOpen).not.toHaveBeenCalled();
    expect(hookOptions!.options.setGroupTitleDraft).not.toHaveBeenCalled();
    expect(hookOptions!.composerErrors.__sessions__).toBe("network down");
    const telemetry = groupCreateTelemetry();
    expect(telemetry.failed).toHaveBeenCalledWith(expect.objectContaining({
      message: "network down",
    }));
    expect(telemetry.succeeded).not.toHaveBeenCalled();
  });
});

describe("useChatWorkspaceLifecycle session create idempotency", () => {
  it.each([false, true])("recovers a discarded create's failed server cleanup (persistent failure: %s)", async (persistentFailure) => {
    resetSessionCreatePreservesForTests();
    resetSessionDeleteTombstonesForTests();
    const deferred = createDeferred<SessionDetail>();
    let realDeletes = 0;
    fetchJsonMock.mockImplementation((input: unknown, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/sessions" && init?.method === "POST") return deferred.promise;
      if (path === "/api/sessions/session-cleanup-real" && init?.method === "DELETE") {
        realDeletes++;
        if (persistentFailure || realDeletes === 1) return Promise.reject(Object.assign(new Error("cleanup unavailable"), { status: 503 }));
      }
      return Promise.resolve({ deleted: true, deletedSessionId: path.split("/").at(-1), nextActiveSessionId: "" });
    });
    hookOptions = buildOptions(buildRouteStub({ kind: "bare" }));
    mount();
    mutateSessionCreate("agent-a");
    await flushMutationQueue();
    const tempId = hookOptions.route.ref.current.kind === "session" ? hookOptions.route.ref.current.sessionId : "";
    act(() => resultRef!.deleteSessionMutation.mutate({ sessionId: tempId }));
    await flushMutationQueue();
    deferred.resolve(serverSessionFor("session-cleanup-real", "agent-a"));
    await flushMutationQueue();
    await new Promise((resolve) => setTimeout(resolve, 1200));
    await flushMutationQueue();
    expect(realDeletes).toBe(persistentFailure ? 3 : 2);
    expect(hookOptions.route.ref.current).not.toEqual({ kind: "session", sessionId: "session-cleanup-real" });
    if (persistentFailure) {
      expect(isSessionDeleteTombstoned("session-cleanup-real")).toBe(false);
      expect(queryClient.getQueryData<SessionDetail>(queryKeys.session("session-cleanup-real"))?.id).toBe("session-cleanup-real");
      expect(hookOptions.composerErrors.__sessions__).toContain("cleanup unavailable");
    } else {
      expect(isSessionDeleteTombstoned("session-cleanup-real")).toBe(true);
      expect(queryClient.getQueryData(queryKeys.session("session-cleanup-real"))).toBeUndefined();
    }
    resetSessionCreatePreservesForTests();
    resetSessionDeleteTombstonesForTests();
  });

  it.each([true, false])("recovers the same create key after remount (document caches cleared: %s)", async (clearDocumentCache) => {
    sessionStorage.clear();
    fetchJsonMock.mockRejectedValue(new TypeError("response lost"));
    hookOptions = buildOptions(buildRouteStub({ kind: "bare" }));
    mount();
    mutateSessionCreate("agent-a");
    await flushMutationQueue();
    const tempId = hookOptions.route.ref.current.kind === "session" ? hookOptions.route.ref.current.sessionId : "";
    const firstKey = sessionCreateIdempotencyKey(sessionCreateRequests()[0]);
    act(() => root?.unmount());
    root = null;
    container.remove();
    if (clearDocumentCache) queryClient = new QueryClient();
    hookOptions = buildOptions(buildRouteStub({ kind: "session", sessionId: tempId }));
    mount();
    await flushMutationQueue();
    expect(queryClient.getQueryData<SessionDetail>(queryKeys.session(tempId))?.agentId).toBe("agent-a");
    mutateSessionCreate("agent-a");
    await flushMutationQueue();
    expect(sessionCreateIdempotencyKey(sessionCreateRequests()[1])).toBe(firstKey);
    expect(hookOptions.route.ref.current).toEqual({ kind: "session", sessionId: tempId });
    sessionStorage.clear();
  });

  it.each([false, true])("cleans only the closed temp pointer with no catalog owner (later selection: %s)", async (laterSelection) => {
    localStorage.clear();
    const deferred = createDeferred<SessionDetail>();
    fetchJsonMock.mockImplementation((input: unknown, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/sessions" && init?.method === "POST") return deferred.promise;
      return Promise.resolve({ deleted: true, deletedSessionId: path.split("/").at(-1), nextActiveSessionId: "" });
    });
    hookOptions = buildOptions(buildRouteStub({ kind: "bare" }));
    mount();
    mutateSessionCreate("agent-a");
    await flushMutationQueue();
    const tempId = hookOptions.route.ref.current.kind === "session" ? hookOptions.route.ref.current.sessionId : "";
    queryClient.removeQueries({ queryKey: queryKeys.sessions(), exact: true });
    if (laterSelection) rememberAgentLastSession("agent-a", "later-session-a", localStorage);
    rememberAgentLastSession("agent-b", "later-session-b", localStorage);
    act(() => resultRef!.deleteSessionMutation.mutate({ sessionId: tempId }));
    await flushMutationQueue();
    expect(lastSessionForAgent("agent-a", readAgentLastSessionMap(localStorage))).toBe(laterSelection ? "later-session-a" : "");
    expect(lastSessionForAgent("agent-b", readAgentLastSessionMap(localStorage))).toBe("later-session-b");
    deferred.reject(new Error("closed create failed"));
    await flushMutationQueue();
  });

  it("does not surface a late create failure after its temp session was closed", async () => {
    resetSessionCreatePreservesForTests();
    resetSessionDeleteTombstonesForTests();
    const deferred = createDeferred<SessionDetail>();
    fetchJsonMock.mockImplementation((input: unknown, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/sessions" && init?.method === "POST") return deferred.promise;
      return Promise.resolve({ deleted: true, deletedSessionId: path.split("/").at(-1), nextActiveSessionId: "" });
    });
    hookOptions = buildOptions(buildRouteStub({ kind: "bare" }));
    mount();
    mutateSessionCreate("agent-a");
    await flushMutationQueue();
    const tempId = hookOptions.route.ref.current.kind === "session" ? hookOptions.route.ref.current.sessionId : "";
    act(() => resultRef!.deleteSessionMutation.mutate({ sessionId: tempId }));
    await flushMutationQueue();
    expect(isSessionDeleteTombstoned(tempId)).toBe(true);
    hookOptions.route.ref.current = { kind: "session", sessionId: "later-session" };
    vi.mocked(hookOptions.options.setSessionComposerErrors).mockClear();
    deferred.reject(new Error("late create failure"));
    await flushMutationQueue();
    expect(hookOptions.options.setSessionComposerErrors).not.toHaveBeenCalled();
    expect(hookOptions.route.ref.current).toEqual({ kind: "session", sessionId: "later-session" });
    expect(telemetryEvents.find((event) => event.name === "session_create")?.failed).toHaveBeenCalled();
    resetSessionCreatePreservesForTests();
    resetSessionDeleteTombstonesForTests();
  });

  it.each(["stay", "other-agent", "later-same-agent"])("rebases composer state and remembered identity without taking a later selection (%s)", async (destination) => {
    localStorage.clear();
    const left = destination !== "stay";
    const deferred = createDeferred<SessionDetail>();
    fetchJsonMock.mockImplementation((input: unknown, init?: RequestInit) =>
      String(input) === "/api/sessions" && init?.method === "POST"
        ? deferred.promise : Promise.resolve(serverSessionFor("session-real", "agent-a")));
    hookOptions = buildOptions(buildRouteStub({ kind: "bare" }));
    mount();
    mutateSessionCreate("agent-a");
    await flushMutationQueue();
    const tempId = hookOptions.route.ref.current.kind === "session" ? hookOptions.route.ref.current.sessionId : "";
    expect(tempId).toMatch(/^temp-session-/);
    vi.mocked(hookOptions.options.setSelectedAgentId).mockClear();
    if (left) hookOptions.route.ref.current = { kind: "session", sessionId: "session-b" };
    if (destination === "later-same-agent") rememberAgentLastSession("agent-a", "session-b", localStorage);
    deferred.resolve(serverSessionFor("session-real", "agent-a"));
    await flushMutationQueue();
    expect(hookOptions.options.rebaseSessionComposerState).toHaveBeenCalledExactlyOnceWith(tempId, "session-real");
    expect(hookOptions.route.ref.current).toEqual({ kind: "session", sessionId: left ? "session-b" : "session-real" });
    if (left) expect(hookOptions.options.setSelectedAgentId).not.toHaveBeenCalled();
    else expect(hookOptions.options.setSelectedAgentId).toHaveBeenCalledWith("agent-a");
    expect(lastSessionForAgent("agent-a", readAgentLastSessionMap(localStorage))).toBe(destination === "later-same-agent" ? "session-b" : "session-real");
  });

  it("reuses the key after an ambiguous failure and changes it when the Agent intent changes", async () => {
    fetchJsonMock
      .mockRejectedValueOnce(new TypeError("network timeout"))
      .mockRejectedValueOnce(new TypeError("network timeout"))
      .mockRejectedValueOnce(new TypeError("network timeout"));
    hookOptions = buildOptions(buildRouteStub({ kind: "bare" }));
    mount();

    mutateSessionCreate("agent-a");
    await flushMutationQueue();
    const failedTempSessionId = hookOptions!.route.ref.current.kind === "session"
      ? hookOptions!.route.ref.current.sessionId
      : "";
    mutateSessionCreate("agent-a");
    await flushMutationQueue();
    expect(hookOptions!.route.ref.current).toEqual({ kind: "session", sessionId: failedTempSessionId });
    mutateSessionCreate("agent-b");
    await flushMutationQueue();

    const requests = sessionCreateRequests();
    expect(requests).toHaveLength(3);
    const firstKey = sessionCreateIdempotencyKey(requests[0]);
    expect(firstKey).toBeTruthy();
    expect(sessionCreateIdempotencyKey(requests[1])).toBe(firstKey);
    expect(sessionCreateIdempotencyKey(requests[2])).toBeTruthy();
    expect(sessionCreateIdempotencyKey(requests[2])).not.toBe(firstKey);
  });

  it("starts a new same-Agent intent after leaving the failed temp session", async () => {
    fetchJsonMock
      .mockRejectedValueOnce(new TypeError("network timeout"))
      .mockRejectedValueOnce(new TypeError("network timeout"));
    hookOptions = buildOptions(buildRouteStub({ kind: "bare" }));
    mount();

    mutateSessionCreate("agent-a");
    await flushMutationQueue();
    const failedTempSessionId = hookOptions.route.ref.current.kind === "session"
      ? hookOptions.route.ref.current.sessionId
      : "";
    expect(failedTempSessionId).toBeTruthy();
    hookOptions.route.ref.current = { kind: "bare" };

    mutateSessionCreate("agent-a");
    await flushMutationQueue();
    const newTempSessionId = hookOptions.route.ref.current.kind === "session"
      ? hookOptions.route.ref.current.sessionId
      : "";
    expect(newTempSessionId).toBeTruthy();
    expect(newTempSessionId).not.toBe(failedTempSessionId);
    const requests = sessionCreateRequests();
    expect(requests).toHaveLength(2);
    expect(sessionCreateIdempotencyKey(requests[1])).not.toBe(sessionCreateIdempotencyKey(requests[0]));
  });

  it.each([409, 410])("rotates the key after a definitive HTTP %i response", async (status) => {
    fetchJsonMock
      .mockRejectedValueOnce(Object.assign(new Error("session create rejected"), { status }))
      .mockResolvedValueOnce(serverSessionFor("session-after-conflict", "agent-a"));
    hookOptions = buildOptions(buildRouteStub({ kind: "bare" }));
    mount();

    mutateSessionCreate("agent-a");
    await flushMutationQueue();
    const rejectedTempSessionId = hookOptions.route.ref.current.kind === "session"
      ? hookOptions.route.ref.current.sessionId
      : "";
    const rejectedKey = sessionCreateIdempotencyKey(sessionCreateRequests()[0]);
    const rotatedKey = readSessionCreateRecovery(rejectedTempSessionId)?.idempotencyKey;
    expect(rotatedKey).toBeTruthy();
    expect(rotatedKey).not.toBe(rejectedKey);
    mutateSessionCreate("agent-a");
    await flushMutationQueue();
    expect(hookOptions.route.ref.current).toEqual({ kind: "session", sessionId: "session-after-conflict" });
    const sessionIds = (queryClient.getQueryData<SessionSummary[]>(queryKeys.sessions()) ?? []).map((item) => item.id);
    expect(sessionIds.filter((id) => id.startsWith("temp-session-"))).toEqual([]);
    expect(sessionIds).toContain("session-after-conflict");

    const requests = sessionCreateRequests();
    expect(requests).toHaveLength(2);
    expect(sessionCreateIdempotencyKey(requests[0])).toBe(rejectedKey);
    expect(sessionCreateIdempotencyKey(requests[1])).toBe(rotatedKey);
  });

  it("rotates the key after success and preserves compatibility for callers without a key", async () => {
    fetchJsonMock
      .mockResolvedValueOnce(serverSessionFor("session-first", "agent-a"))
      .mockResolvedValueOnce(serverSessionFor("session-detail-first", "agent-a"))
      .mockResolvedValueOnce(serverSessionFor("session-second", "agent-a"));
    hookOptions = buildOptions(buildRouteStub({ kind: "bare" }));
    mount();

    mutateSessionCreate("agent-a");
    await flushMutationQueue();
    mutateSessionCreate("agent-a");
    await flushMutationQueue();

    const requests = sessionCreateRequests();
    expect(requests).toHaveLength(2);
    expect(sessionCreateIdempotencyKey(requests[0])).toBeTruthy();
    expect(sessionCreateIdempotencyKey(requests[1])).toBeTruthy();
    expect(sessionCreateIdempotencyKey(requests[1])).not.toBe(sessionCreateIdempotencyKey(requests[0]));

    fetchJsonMock.mockClear();
    fetchJsonMock.mockResolvedValueOnce(serverSessionFor("session-legacy", "agent-a"));
    await createChatSession({ agentId: "agent-a" });
    const legacyInit = fetchJsonMock.mock.calls[0]?.[1] as RequestInit;
    expect(legacyInit.headers).not.toHaveProperty("Idempotency-Key");
  });

  it("does not put the real session back when the temp tab was deleted first", async () => {
    resetSessionCreatePreservesForTests();
    resetSessionDeleteTombstonesForTests();
    const deferred = createDeferred<SessionDetail>();
    fetchJsonMock.mockImplementation((input: unknown, init?: RequestInit) => {
      const path = String(input || "");
      const method = String(init?.method || "GET").toUpperCase();
      if (path === "/api/sessions" && method === "POST") {
        return deferred.promise;
      }
      if (method === "DELETE" && path.startsWith("/api/sessions/")) {
        return Promise.resolve({
          deleted: true,
          deletedSessionId: decodeURIComponent(path.slice("/api/sessions/".length)),
          nextActiveSessionId: "",
        });
      }
      return Promise.resolve({});
    });
    hookOptions = buildOptions(buildRouteStub({ kind: "bare" }));
    mount();

    mutateSessionCreate("agent-a");
    await flushMutationQueue();
    const tempSessionId = hookOptions.route.ref.current.kind === "session"
      ? hookOptions.route.ref.current.sessionId
      : "";
    expect(tempSessionId.startsWith("temp-session-")).toBe(true);

    act(() => {
      resultRef!.deleteSessionMutation.mutate({ sessionId: tempSessionId });
    });
    await flushMutationQueue();
    expect(isSessionDeleteTombstoned(tempSessionId)).toBe(true);
    expect(isSessionCreatePreserved(tempSessionId)).toBe(false);
    expect(readSessionCreateRecovery(tempSessionId)).toBeUndefined();

    deferred.resolve(serverSessionFor("session-real", "agent-a"));
    await flushMutationQueue();
    await flushMutationQueue();

    const sessions = queryClient.getQueryData<SessionSummary[]>(queryKeys.sessions()) ?? [];
    expect(sessions.map((item) => item.id)).not.toContain("session-real");
    expect(sessions.map((item) => item.id)).not.toContain(tempSessionId);
    expect(isSessionCreatePreserved("session-real")).toBe(false);
    expect(isSessionDeleteTombstoned("session-real")).toBe(true);
    expect(queryClient.getQueryData(queryKeys.session("session-real"))).toBeUndefined();
    expect(hookOptions.options.rebaseSessionComposerState).not.toHaveBeenCalled();
    const deleteCalls = fetchJsonMock.mock.calls.filter(
      ([input, init]) =>
        String(input) === "/api/sessions/session-real"
        && String((init as RequestInit | undefined)?.method || "").toUpperCase() === "DELETE",
    );
    expect(deleteCalls.length).toBeGreaterThan(0);
    expect(hookOptions.route.ref.current).not.toEqual({ kind: "session", sessionId: "session-real" });

    resetSessionCreatePreservesForTests();
    resetSessionDeleteTombstonesForTests();
  });
});
