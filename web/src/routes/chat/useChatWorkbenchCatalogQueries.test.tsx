// @vitest-environment happy-dom
import { QueryClient, QueryClientProvider, type InfiniteData } from "@tanstack/react-query";
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useChatWorkbenchCatalogQueries, type ChatWorkbenchCatalogQueriesInput } from "./useChatWorkbenchCatalogQueries";
import { queryKeys } from "../../api/queryKeys";
import type { SessionQueryResponse, SessionSummary } from "../../api/types";
import { pinSessionCreatePreserve, resetSessionCreatePreservesForTests } from "../sessionCreatePreserve";
import { markSessionDeleteTombstone, resetSessionDeleteTombstonesForTests } from "../sessionDeleteTombstone";

const reads = vi.hoisted(() => ({ signals: new Map<string, AbortSignal>() }));
const bootstrapControl = vi.hoisted(() => ({
  payload: new Promise<Record<string, unknown>>(() => {}),
  requestCount: 0,
}));
const sessionIndexGate = vi.hoisted(() => ({ enabledFlags: [] as boolean[] }));
const directoryReads = vi.hoisted(() => ({
  sessions: vi.fn(async (_filters: unknown, _options?: unknown): Promise<SessionQueryResponse> => ({ items: [], nextCursor: "" })),
  conversations: vi.fn(async () => ({ items: [], nextCursor: "" })),
  teams: vi.fn(async () => []),
  archived: vi.fn(async () => ({ items: [] })),
}));
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
function pendingRead(name: string, signal?: AbortSignal): Promise<never> {
  if (signal) reads.signals.set(name, signal);
  return new Promise((_, reject) => {
    signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
  });
}
vi.mock("../../api/config", () => ({ fetchConfigBootstrap: ({ signal }: { signal?: AbortSignal } = {}) => pendingRead("config", signal) }));
vi.mock("../../api/chat", () => ({
  fetchChatWorkbenchBootstrap: ({ signal }: { signal: AbortSignal }) => {
    reads.signals.set("bootstrap", signal);
    bootstrapControl.requestCount += 1;
    return bootstrapControl.payload;
  },
  fetchChatRoomDetail: (_id: string, { signal }: { signal?: AbortSignal } = {}) => pendingRead("room", signal),
  listChatRoomModes: async () => [],
  listChatRoomPurposes: async () => [],
  queryConversations: directoryReads.conversations,
  querySessions: directoryReads.sessions,
}));
vi.mock("../../api/agents", () => ({ listAgentSummaries: async () => [] }));
vi.mock("../../api/teams", () => ({ listTeams: directoryReads.teams }));
vi.mock("../../api/sessionArchive", () => ({ listArchivedChatSessions: directoryReads.archived }));
vi.mock("../../api/runtime", () => ({ fetchRuntimeSummary: async () => ({}) }));
vi.mock("../../api/skills", () => ({ fetchSkillLibrary: async () => ({ skills: [] }) }));
vi.mock("../chatSessionIndexQuery", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../chatSessionIndexQuery")>();
  return {
    ...actual,
    useSessionIndexQuery: (options: Parameters<typeof actual.useSessionIndexQuery>[0]) => {
      sessionIndexGate.enabledFlags.push(options.enabled);
      return actual.useSessionIndexQuery(options);
    },
  };
});
vi.mock("./chatSessionDetailHelpers", () => ({
  fetchSessionDetailWindow: (_id: string, { signal }: { signal?: AbortSignal } = {}) => pendingRead("expanded", signal),
}));

afterEach(() => {
  reads.signals.clear();
  sessionIndexGate.enabledFlags.length = 0;
  bootstrapControl.payload = new Promise<Record<string, unknown>>(() => {});
  bootstrapControl.requestCount = 0;
  resetSessionCreatePreservesForTests();
  resetSessionDeleteTombstonesForTests();
  directoryReads.sessions.mockReset();
  directoryReads.sessions.mockResolvedValue({ items: [], nextCursor: "" });
  vi.clearAllMocks();
});

/**
 * Deterministic propagation wait: react-query notifies observers through its
 * batched notifyManager, so a resolved refetch can commit one macrotask after
 * the await resumes. Yield microtasks plus that batch inside act and re-check
 * until `check` holds or the bounded attempts run out — no fixed sleeps.
 */
async function actUntil(check: () => boolean, attempts = 100): Promise<boolean> {
  for (let attempt = 0; attempt < attempts; attempt++) {
    if (check()) {
      return true;
    }
    await act(async () => {
      await Promise.resolve();
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  }
  return check();
}

function catalogInput(client: QueryClient, overrides: Partial<ChatWorkbenchCatalogQueriesInput> = {}) {
  return {
    queryClient: client, secondaryChatDataEnabled: false,
    chatSecondaryPollPolicy: {}, chatLiveQueryPolicy: {}, sessionQueryText: "",
    activeSessionId: "", requestedSessionId: "", requestedRoomId: "",
    activeGroupRoomId: "", expandedGroupAgentSessionIds: [], groupComposerOpen: false,
    standardGroupRoomActive: false, projectBusActive: false, chatPollingVisible: true,
    chatStartupWarmupActive: false, groupBackgroundSyncActive: false, groupStreamConnected: true,
    showArchivedSessions: false,
    ...overrides,
  } as ChatWorkbenchCatalogQueriesInput;
}

function bootstrapPayload(items: SessionSummary[] = []) {
  return {
    activeSessionId: "", sessionPage: { items, nextCursor: "" },
    agents: [], conversations: [], directoryReady: true,
  };
}

describe("Chat bootstrap session cache reuse", () => {
  it.each(["", "updatedAt_desc", " updatedAt_desc "])("uses the bootstrap page without an index request for sort %j", async (sort) => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const serverSession = { id: "bootstrap-session" } as SessionSummary;
    bootstrapControl.payload = Promise.resolve(bootstrapPayload([serverSession]));
    const input = catalogInput(client, { sessionListSort: sort });
    let result: ReturnType<typeof useChatWorkbenchCatalogQueries>;
    function Page() { result = useChatWorkbenchCatalogQueries(input); return null; }
    const container = document.createElement("div");
    const root = createRoot(container);
    try {
      await act(async () => root.render(<QueryClientProvider client={client}><Page /></QueryClientProvider>));
      expect(await actUntil(() => result.sessionIndexQueryEnabled && result.rawSessionsQuery.data?.[0]?.id === serverSession.id)).toBe(true);
      expect(directoryReads.sessions).not.toHaveBeenCalled();
      for (const defaultSort of ["", "updatedAt_desc"]) {
        expect(client.getQueryData(queryKeys.sessionQuery("", 50, "", defaultSort))).toMatchObject({
          pages: [{ items: [serverSession] }], pageParams: [""],
        });
      }
    } finally {
      await act(async () => root.unmount());
      client.clear();
      container.remove();
    }
  });

  it.each([
    { sort: "createdAt_desc", q: "" },
    { sort: "updatedAt_desc", q: "needle" },
  ])("requests an authoritative index for sort $sort and search $q", async ({ sort, q }) => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    bootstrapControl.payload = Promise.resolve(bootstrapPayload([{ id: "bootstrap-session" } as SessionSummary]));
    let resolveIndex!: (page: SessionQueryResponse) => void;
    directoryReads.sessions.mockReturnValueOnce(new Promise((resolve) => { resolveIndex = resolve; }));
    const input = catalogInput(client, { sessionListSort: sort, sessionQueryText: q });
    let result: ReturnType<typeof useChatWorkbenchCatalogQueries>;
    function Page() { result = useChatWorkbenchCatalogQueries(input); return null; }
    const container = document.createElement("div");
    const root = createRoot(container);
    try {
      await act(async () => root.render(<QueryClientProvider client={client}><Page /></QueryClientProvider>));
      expect(await actUntil(() => directoryReads.sessions.mock.calls.length === 1)).toBe(true);
      expect(directoryReads.sessions).toHaveBeenCalledWith(
        { limit: 50, cursor: "", q, sort }, { signal: expect.any(AbortSignal) },
      );
      expect(client.getQueryData(queryKeys.sessionQuery(q, 50, "", sort))).toBeUndefined();
      expect(result!.rawSessionsQuery.data).toBeUndefined();
      const authoritativeSession = { id: "index-session" } as SessionSummary;
      await act(async () => resolveIndex({ items: [authoritativeSession], nextCursor: "" }));
      expect(await actUntil(() => result.rawSessionsQuery.data?.[0]?.id === authoritativeSession.id)).toBe(true);
      expect(directoryReads.sessions).toHaveBeenCalledTimes(1);
    } finally {
      await act(async () => root.unmount());
      client.clear();
      container.remove();
    }
  });

  it("preserves optimistic rows from both default keys, pins and the current-session cache while removing tombstones", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const tempDefault = { id: "temp-session-default" } as SessionSummary;
    const tempExplicit = { id: "temp-session-explicit" } as SessionSummary;
    const tempCurrent = { id: "temp-session-current" } as SessionSummary;
    const pinned = { id: "pinned-session" } as SessionSummary;
    const deleted = { id: "deleted-session" } as SessionSummary;
    const serverSession = { id: "server-session" } as SessionSummary;
    client.setQueryData(queryKeys.sessionQuery("", 50), { pages: [{ items: [tempDefault] }], pageParams: [""] });
    client.setQueryData(queryKeys.sessionQuery("", 50, "", "updatedAt_desc"), { pages: [{ items: [tempExplicit] }], pageParams: [""] });
    client.setQueryData(queryKeys.sessions(), [tempCurrent, deleted]);
    pinSessionCreatePreserve(pinned);
    markSessionDeleteTombstone(deleted.id);
    bootstrapControl.payload = Promise.resolve(bootstrapPayload([serverSession, deleted]));
    const input = catalogInput(client, { sessionListSort: "updatedAt_desc" });
    function Page() { useChatWorkbenchCatalogQueries(input); return null; }
    const container = document.createElement("div");
    const root = createRoot(container);
    try {
      await act(async () => root.render(<QueryClientProvider client={client}><Page /></QueryClientProvider>));
      expect(await actUntil(() => client.getQueryState(["sessions", "active-bootstrap"])?.status === "success")).toBe(true);
      for (const sort of ["", "updatedAt_desc"]) {
        const data = client.getQueryData<{ pages: SessionQueryResponse[] }>(queryKeys.sessionQuery("", 50, "", sort));
        expect(data?.pages[0].items.map((session) => session.id)).toEqual([pinned.id, tempDefault.id, tempExplicit.id, serverSession.id]);
      }
      expect(client.getQueryData<SessionSummary[]>(queryKeys.sessions())?.map((session) => session.id)).toEqual([
        tempCurrent.id, pinned.id, tempDefault.id, tempExplicit.id, serverSession.id,
      ]);
      expect(directoryReads.sessions).not.toHaveBeenCalled();
    } finally {
      await act(async () => root.unmount());
      client.clear();
      container.remove();
    }
  });

  it.each(["", "updatedAt_desc"])("keeps loaded pages and newer index responses when bootstrap finishes late for sort %j", async (sort) => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const key = queryKeys.sessionQuery("", 50, "", sort);
    const oldFirst = { id: "first-session", title: "Before index refresh" } as SessionSummary;
    const oldSecond = { id: "second-session", title: "Before index refresh" } as SessionSummary;
    const newFirst = { ...oldFirst, title: "New first page" };
    const newSecond = { ...oldSecond, title: "New second page" };
    const pages = {
      pages: [
        { items: [oldFirst], nextCursor: "page-2" },
        { items: [oldSecond], nextCursor: "" },
      ],
      pageParams: ["", "page-2"],
    };
    client.setQueryData(key, pages);
    client.setQueryData(queryKeys.sessions(), [oldFirst, oldSecond]);
    let resolveBootstrap!: (payload: Record<string, unknown>) => void;
    bootstrapControl.payload = new Promise((resolve) => { resolveBootstrap = resolve; });
    directoryReads.sessions
      .mockResolvedValueOnce({ items: [newFirst], nextCursor: "page-2" })
      .mockResolvedValueOnce({ items: [newSecond], nextCursor: "" });
    const input = catalogInput(client, { sessionListSort: sort, activeSessionId: oldFirst.id });
    let result: ReturnType<typeof useChatWorkbenchCatalogQueries>;
    function Page() { result = useChatWorkbenchCatalogQueries(input); return null; }
    const container = document.createElement("div");
    const root = createRoot(container);
    try {
      await act(async () => root.render(<QueryClientProvider client={client}><Page /></QueryClientProvider>));
      expect(bootstrapControl.requestCount).toBe(1);
      await act(async () => { await result.rawSessionsQuery.refetch(); });
      const refreshed = client.getQueryData<InfiniteData<SessionQueryResponse, string>>(key);
      expect(refreshed?.pages.map((page) => page.items[0].title)).toEqual([newFirst.title, newSecond.title]);
      expect(directoryReads.sessions).toHaveBeenCalledTimes(2);
      await act(async () => {
        resolveBootstrap(bootstrapPayload([oldFirst]));
        await bootstrapControl.payload;
      });
      expect(await actUntil(() => client.getQueryState(["sessions", "active-bootstrap"])?.status === "success")).toBe(true);
      expect(client.getQueryData(key)).toBe(refreshed);
      expect(refreshed?.pageParams).toEqual(["", "page-2"]);
      expect(client.getQueryData<SessionSummary[]>(queryKeys.sessions())).toEqual([newFirst, newSecond]);
      expect(directoryReads.sessions).toHaveBeenCalledTimes(2);
    } finally {
      await act(async () => root.unmount());
      client.clear();
      container.remove();
    }
  });

  it("keeps an existing empty index authoritative over a late bootstrap page", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const key = queryKeys.sessionQuery("", 50, "", "updatedAt_desc");
    const emptyIndex = { pages: [{ items: [], nextCursor: "" }], pageParams: [""] };
    client.setQueryData(key, emptyIndex);
    client.setQueryData(queryKeys.sessions(), []);
    bootstrapControl.payload = Promise.resolve(bootstrapPayload([{ id: "stale-session" } as SessionSummary]));
    const input = catalogInput(client, { sessionListSort: "updatedAt_desc" });
    function Page() { useChatWorkbenchCatalogQueries(input); return null; }
    const container = document.createElement("div");
    const root = createRoot(container);
    try {
      await act(async () => root.render(<QueryClientProvider client={client}><Page /></QueryClientProvider>));
      expect(await actUntil(() => client.getQueryState(["sessions", "active-bootstrap"])?.status === "success")).toBe(true);
      expect(client.getQueryData(key)).toEqual(emptyIndex);
      expect(client.getQueryData(queryKeys.sessions())).toEqual([]);
      expect(directoryReads.sessions).not.toHaveBeenCalled();
    } finally {
      await act(async () => root.unmount());
      client.clear();
      container.remove();
    }
  });

  it("does not seed session caches when bootstrap resolves after page exit", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    let resolveBootstrap!: (payload: Record<string, unknown>) => void;
    bootstrapControl.payload = new Promise((resolve) => { resolveBootstrap = resolve; });
    const input = catalogInput(client, { sessionListSort: "updatedAt_desc" });
    function Page() { useChatWorkbenchCatalogQueries(input); return null; }
    const container = document.createElement("div");
    const root = createRoot(container);
    try {
      await act(async () => root.render(<QueryClientProvider client={client}><Page /></QueryClientProvider>));
      const signal = reads.signals.get("bootstrap");
      expect(signal?.aborted).toBe(false);
      await act(async () => root.unmount());
      expect(signal?.aborted).toBe(true);
      await act(async () => {
        resolveBootstrap(bootstrapPayload([{ id: "obsolete-session" } as SessionSummary]));
        await bootstrapControl.payload;
      });
      expect(client.getQueryData(queryKeys.sessionQuery("", 50))).toBeUndefined();
      expect(client.getQueryData(queryKeys.sessionQuery("", 50, "", "updatedAt_desc"))).toBeUndefined();
      expect(client.getQueryData(queryKeys.sessions())).toBeUndefined();
    } finally {
      client.clear();
      container.remove();
    }
  });
});

describe("Chat catalog request lifecycle", () => {
  it("skips hidden Finance directory reads and cached catalog auto-pagination", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(queryKeys.conversationsCatalogQuery(100), {
      pages: [{ items: [], nextCursor: "page-2" }], pageParams: [""],
    });
    bootstrapControl.payload = Promise.resolve({
      activeSessionId: "finance-session", sessionPage: { items: [], nextCursor: "" },
      agents: [], conversations: [], directoryReady: true,
    });
    const input = {
      queryClient: client, secondaryChatDataEnabled: true, sessionDirectoryEnabled: false,
      chatSecondaryPollPolicy: {}, chatLiveQueryPolicy: {}, sessionQueryText: "",
      activeSessionId: "finance-session", requestedSessionId: "finance-session", requestedRoomId: "",
      activeGroupRoomId: "", expandedGroupAgentSessionIds: [], groupComposerOpen: false,
      standardGroupRoomActive: false, projectBusActive: false, chatPollingVisible: true,
      chatStartupWarmupActive: false, groupBackgroundSyncActive: false, groupStreamConnected: true,
      showArchivedSessions: true,
    } as ChatWorkbenchCatalogQueriesInput;
    function Page() { useChatWorkbenchCatalogQueries(input); return null; }
    const container = document.createElement("div");
    const root = createRoot(container);
    try {
      await act(async () => root.render(<QueryClientProvider client={client}><Page /></QueryClientProvider>));
      expect(await actUntil(() => client.getQueryState(queryKeys.agents())?.status === "success")).toBe(true);
      expect(bootstrapControl.requestCount).toBe(0);
      expect(sessionIndexGate.enabledFlags.every((enabled) => !enabled)).toBe(true);
      expect(directoryReads.conversations).not.toHaveBeenCalled();
      expect(directoryReads.teams).not.toHaveBeenCalled();
      expect(directoryReads.archived).not.toHaveBeenCalled();
    } finally {
      await act(async () => root.unmount());
      client.clear();
      container.remove();
    }
  });

  it("releases obsolete config, group and expanded-session requests on page exit", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const input = {
      queryClient: client,
      secondaryChatDataEnabled: false,
      chatSecondaryPollPolicy: {},
      chatLiveQueryPolicy: {},
      sessionQueryText: "",
      activeSessionId: "",
      activeGroupRoomId: "room-1",
      expandedGroupAgentSessionIds: ["child-1"],
      groupComposerOpen: false,
      standardGroupRoomActive: true,
      projectBusActive: false,
      chatPollingVisible: true,
      chatStartupWarmupActive: false,
      groupBackgroundSyncActive: false,
      groupStreamConnected: true,
      requestedSessionId: "",
      requestedRoomId: "room-1",
      showArchivedSessions: false,
    } as ChatWorkbenchCatalogQueriesInput;
    function Page() {
      useChatWorkbenchCatalogQueries(input);
      return null;
    }
    const container = document.createElement("div");
    const root = createRoot(container);
    try {
      await act(async () => root.render(<QueryClientProvider client={client}><Page /></QueryClientProvider>));
      expect([...reads.signals.keys()].sort()).toEqual(["bootstrap", "config", "expanded", "room"]);
      expect([...reads.signals.values()].every((signal) => !signal.aborted)).toBe(true);
      await act(async () => root.unmount());
      expect([...reads.signals.values()].every((signal) => signal.aborted)).toBe(true);
    } finally {
      client.clear();
      container.remove();
    }
  });

  it("gates the session index on the bootstrap directoryReady bit and releases it", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const input = {
      queryClient: client,
      secondaryChatDataEnabled: false,
      chatSecondaryPollPolicy: {},
      chatLiveQueryPolicy: {},
      sessionQueryText: "",
      activeSessionId: "",
      activeGroupRoomId: "",
      expandedGroupAgentSessionIds: [],
      groupComposerOpen: false,
      standardGroupRoomActive: false,
      projectBusActive: false,
      chatPollingVisible: true,
      chatStartupWarmupActive: false,
      groupBackgroundSyncActive: false,
      groupStreamConnected: true,
      requestedSessionId: "",
      requestedRoomId: "",
      showArchivedSessions: false,
    } as ChatWorkbenchCatalogQueriesInput;
    function Page() {
      useChatWorkbenchCatalogQueries(input);
      return null;
    }
    const container = document.createElement("div");
    const root = createRoot(container);
    try {
      bootstrapControl.payload = Promise.resolve({
        activeSessionId: "",
        sessionPage: { items: [], nextCursor: "" },
        agents: [],
        conversations: [],
        directoryReady: false,
      });
      await act(async () => root.render(<QueryClientProvider client={client}><Page /></QueryClientProvider>));
      const bootstrapState = () =>
        client.getQueryState(["sessions", "active-bootstrap"])?.data as
          | { directoryReady?: boolean }
          | undefined;
      // The directory store is mid-startup: the bootstrap must settle with the
      // bit false and the index query must stay held even though the bootstrap
      // itself has settled.
      expect(await actUntil(() => bootstrapState()?.directoryReady === false)).toBe(true);
      expect(sessionIndexGate.enabledFlags.length > 0).toBe(true);
      expect(sessionIndexGate.enabledFlags.at(-1)).toBe(false);

      bootstrapControl.payload = Promise.resolve({
        activeSessionId: "",
        sessionPage: { items: [], nextCursor: "" },
        agents: [],
        conversations: [],
        directoryReady: true,
      });
      await act(async () => {
        await client.refetchQueries({ queryKey: ["sessions", "active-bootstrap"] });
      });
      // A resolved refetch can commit one notifyManager batch later; wait for
      // the flip deterministically instead of asserting on a single flush.
      expect(await actUntil(() => sessionIndexGate.enabledFlags.at(-1) === true)).toBe(true);
    } finally {
      await act(async () => root.unmount());
      client.clear();
      container.remove();
    }
  });
});
