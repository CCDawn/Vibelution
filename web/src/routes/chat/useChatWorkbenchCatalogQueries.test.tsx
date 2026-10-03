// @vitest-environment happy-dom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useChatWorkbenchCatalogQueries, type ChatWorkbenchCatalogQueriesInput } from "./useChatWorkbenchCatalogQueries";

const reads = vi.hoisted(() => ({ signals: new Map<string, AbortSignal>() }));
const bootstrapControl = vi.hoisted(() => ({
  payload: new Promise<Record<string, unknown>>(() => {}),
}));
const sessionIndexGate = vi.hoisted(() => ({ enabledFlags: [] as boolean[] }));
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
  queryConversations: async () => ({ items: [], nextCursor: "" }),
}));
vi.mock("../../api/agents", () => ({ listAgentSummaries: async () => [] }));
vi.mock("../../api/teams", () => ({ listTeams: async () => [] }));
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
});

describe("Chat catalog request lifecycle", () => {
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
      await act(async () => {});
      // The directory store is mid-startup: the index query must stay held even
      // though the bootstrap itself has settled.
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
      expect(sessionIndexGate.enabledFlags.at(-1)).toBe(true);
    } finally {
      await act(async () => root.unmount());
      client.clear();
      container.remove();
    }
  });
});
