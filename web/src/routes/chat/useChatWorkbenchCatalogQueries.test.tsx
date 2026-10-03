// @vitest-environment happy-dom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useChatWorkbenchCatalogQueries, type ChatWorkbenchCatalogQueriesInput } from "./useChatWorkbenchCatalogQueries";
import { queryKeys } from "../../api/queryKeys";

const reads = vi.hoisted(() => ({ signals: new Map<string, AbortSignal>() }));
const bootstrapControl = vi.hoisted(() => ({
  payload: new Promise<Record<string, unknown>>(() => {}),
}));
const sessionIndexGate = vi.hoisted(() => ({ enabledFlags: [] as boolean[] }));
const directoryReads = vi.hoisted(() => ({
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
vi.mock("../../api/config", () => ({ fetchPublicConfig: ({ signal }: { signal?: AbortSignal } = {}) => pendingRead("config", signal) }));
vi.mock("../../api/chat", () => ({
  fetchChatWorkbenchBootstrap: () => bootstrapControl.payload,
  fetchChatRoomDetail: (_id: string, { signal }: { signal?: AbortSignal } = {}) => pendingRead("room", signal),
  listChatRoomModes: async () => [],
  listChatRoomPurposes: async () => [],
  queryConversations: directoryReads.conversations,
}));
vi.mock("../../api/agents", () => ({ listAgentSummaries: async () => [] }));
vi.mock("../../api/teams", () => ({ listTeams: directoryReads.teams }));
vi.mock("../../api/sessionArchive", () => ({ listArchivedChatSessions: directoryReads.archived }));
vi.mock("../../api/runtime", () => ({ fetchRuntimeSummary: async () => ({}) }));
vi.mock("../../api/skills", () => ({ fetchSkillLibrary: async () => ({ skills: [] }) }));
vi.mock("../chatSessionIndexQuery", () => ({
  useSessionIndexQuery: (options: { enabled: boolean }) => {
    sessionIndexGate.enabledFlags.push(options.enabled);
    return { data: [] };
  },
}));
vi.mock("./chatSessionDetailHelpers", () => ({
  fetchSessionDetailWindow: (_id: string, { signal }: { signal?: AbortSignal } = {}) => pendingRead("expanded", signal),
}));

afterEach(() => {
  reads.signals.clear();
  sessionIndexGate.enabledFlags.length = 0;
  bootstrapControl.payload = new Promise<Record<string, unknown>>(() => {});
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
      expect(await actUntil(() => client.getQueryState(["sessions", "active-bootstrap"])?.status === "success")).toBe(true);
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
      expect([...reads.signals.keys()].sort()).toEqual(["config", "expanded", "room"]);
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
