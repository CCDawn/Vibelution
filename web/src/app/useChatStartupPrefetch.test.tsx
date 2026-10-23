// @vitest-environment happy-dom
import React, { act, lazy, Suspense } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider, QueryObserver, useQuery } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

import { queryKeys } from "../api/queryKeys";
import { fetchChatWorkbenchBootstrap, querySessions } from "../api/chat";
import { chatWorkbenchBootstrapQueryOptions } from "../routes/chat/chatWorkbenchBootstrapQuery";
import { fetchSessionDetailWindow } from "../routes/chat/chatSessionDetailHelpers";
import { readCurrentChatSelectionPreference } from "../routes/chat/useChatSelectionPersistence";
import { markSessionDeleteTombstone, resetSessionDeleteTombstonesForTests } from "../routes/sessionDeleteTombstone";
import { useChatStartupPrefetch } from "./useChatStartupPrefetch";

vi.mock("../api/chat", () => ({
  fetchChatWorkbenchBootstrap: vi.fn(), querySessions: vi.fn(async () => ({ items: [], nextCursor: "" })),
  queryConversations: vi.fn(async () => ({ items: [], nextCursor: "" })),
  fetchChatRoomDetail: vi.fn(), listChatRoomModes: vi.fn(), listChatRoomPurposes: vi.fn(),
}));
vi.mock("../api/config", () => ({ fetchConfigBootstrap: vi.fn(() => new Promise(() => {})) }));
vi.mock("../api/agents", () => ({ listAgentSummaries: vi.fn(async () => []) }));
vi.mock("../routes/chat/chatSessionDetailHelpers", () => ({ fetchSessionDetailWindow: vi.fn(), SESSION_DETAIL_PREFETCH_STALE_MS: 30_000 }));
vi.mock("../routes/chat/useChatSelectionPersistence", () => ({ readCurrentChatSelectionPreference: vi.fn() }));
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
afterEach(() => { vi.clearAllMocks(); resetSessionDeleteTombstonesForTests(); });

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
}
const payload = () => ({ activeSessionId: "", sessionPage: { items: [], nextCursor: "" }, agents: [], conversations: [], directoryReady: true });

async function mount(initial = { pathname: "/chat", search: "" }, route?: React.ReactNode, client = new QueryClient({ defaultOptions: { queries: { retry: false } } })) {
  const root = createRoot(document.createElement("div"));
  function Shell({ pathname, search }: typeof initial) {
    useChatStartupPrefetch({ queryClient: client, pathname, search });
    return <Suspense fallback={null}>{route}</Suspense>;
  }
  const render = (location = initial) => act(async () => root.render(<QueryClientProvider client={client}><Shell {...location} /></QueryClientProvider>));
  await render();
  return { client, render, unmount: () => act(async () => root.unmount()), close: async () => { await act(async () => root.unmount()); client.clear(); } };
}

function pendingReads() {
  vi.mocked(readCurrentChatSelectionPreference).mockReturnValue({ sessionId: "remembered" });
  const bootstrap = deferred<Awaited<ReturnType<typeof fetchChatWorkbenchBootstrap>>>();
  vi.mocked(fetchChatWorkbenchBootstrap).mockReturnValue(bootstrap.promise);
  vi.mocked(fetchSessionDetailWindow).mockReturnValue(new Promise(() => {}));
  return bootstrap;
}

describe("shell Chat startup prefetch", () => {
  it.each([false, true])("starts both reads before the lazy route loads and shares its %s settled bootstrap", async settled => {
    const bootstrap = pendingReads();
    const chunk = deferred<void>();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const loadRoute = vi.fn(async () => {
      await chunk.promise;
      const { useChatWorkbenchCatalogQueries } = await import("../routes/chat/useChatWorkbenchCatalogQueries");
      return { default: function Route() {
        useChatWorkbenchCatalogQueries({
          queryClient: client, secondaryChatDataEnabled: false, chatSecondaryPollPolicy: {} as never,
          chatLiveQueryPolicy: {} as never, sessionQueryText: "", activeSessionId: "remembered",
          requestedSessionId: "", requestedRoomId: "", activeGroupRoomId: "", expandedGroupAgentSessionIds: [],
          groupComposerOpen: false, standardGroupRoomActive: false, projectBusActive: false, chatPollingVisible: true,
          chatStartupWarmupActive: false, groupBackgroundSyncActive: false, groupStreamConnected: true, showArchivedSessions: false,
        });
        useQuery({ queryKey: queryKeys.session("remembered"), queryFn: () => fetchSessionDetailWindow("remembered"), staleTime: 30_000 });
        return null;
      } };
    });
    const Route = lazy(loadRoute);
    const page = await mount(undefined, <Route />, client);
    try {
      expect(loadRoute).toHaveBeenCalledOnce();
      expect(fetchChatWorkbenchBootstrap).toHaveBeenCalledOnce();
      expect(fetchSessionDetailWindow).toHaveBeenCalledOnce();
      expect(querySessions).not.toHaveBeenCalled();
      if (settled) await act(async () => bootstrap.resolve(payload()));
      await act(async () => { chunk.resolve(); await loadRoute.mock.results[0].value; });
      if (!settled) await act(async () => bootstrap.resolve(payload()));
      expect(fetchChatWorkbenchBootstrap).toHaveBeenCalledOnce();
      expect(fetchSessionDetailWindow).toHaveBeenCalledOnce();
      expect(querySessions).not.toHaveBeenCalled();
    } finally { await page.close(); }
  });

  it.each([
    { pathname: "/agents", search: "" }, { pathname: "/chat/", search: "" },
    { pathname: "/finance", search: "" }, { pathname: "/chat", search: "?room=group" },
    { pathname: "/chat", search: "?room=__project_agent_bus__" },
    { pathname: "/chat", search: "?room=group&session=remembered" },
  ])("skips non-native or explicit room targets %j", async location => {
    pendingReads();
    const page = await mount(location);
    try {
      expect(fetchChatWorkbenchBootstrap).not.toHaveBeenCalled();
      expect(fetchSessionDetailWindow).not.toHaveBeenCalled();
    } finally { await page.close(); }
  });

  it.each(["foreign", "temp", "deleted"])("keeps the existing body guard for %s sessions", async mode => {
    pendingReads();
    if (mode === "temp") vi.mocked(readCurrentChatSelectionPreference).mockReturnValue({ sessionId: "temp-session-new" });
    if (mode === "deleted") markSessionDeleteTombstone("remembered");
    const page = await mount({ pathname: "/chat", search: mode === "foreign" ? "?session=other" : "" });
    try {
      expect(fetchChatWorkbenchBootstrap).toHaveBeenCalledOnce();
      expect(fetchSessionDetailWindow).not.toHaveBeenCalled();
    } finally { await page.close(); }
  });

  it("navigation cancels only its own orphan reads and an aborted bootstrap cannot seed late", async () => {
    const bootstrap = pendingReads();
    const page = await mount();
    const bootstrapSignal = vi.mocked(fetchChatWorkbenchBootstrap).mock.calls[0][0]?.signal;
    const bodySignal = vi.mocked(fetchSessionDetailWindow).mock.calls[0][1]?.signal;
    try {
      await page.render({ pathname: "/agents", search: "" });
      expect(bootstrapSignal?.aborted).toBe(true);
      expect(bodySignal?.aborted).toBe(true);
      await act(async () => bootstrap.resolve(payload()));
      expect(page.client.getQueryData(queryKeys.sessions())).toBeUndefined();
      expect(page.client.getQueryData(queryKeys.agents())).toBeUndefined();
    } finally { await page.close(); }
  });

  it("keeps reads adopted by real consumers alive on navigation", async () => {
    pendingReads();
    const page = await mount();
    const bootstrapSignal = vi.mocked(fetchChatWorkbenchBootstrap).mock.calls[0][0]?.signal;
    const bodySignal = vi.mocked(fetchSessionDetailWindow).mock.calls[0][1]?.signal;
    const bootstrapObserver = new QueryObserver(page.client, chatWorkbenchBootstrapQueryOptions(page.client));
    const bodyObserver = new QueryObserver(page.client, { queryKey: queryKeys.session("remembered"), queryFn: () => fetchSessionDetailWindow("remembered") });
    const unsubscribers = [bootstrapObserver.subscribe(() => {}), bodyObserver.subscribe(() => {})];
    try {
      await page.render({ pathname: "/agents", search: "" });
      expect(bootstrapSignal?.aborted).toBe(false);
      expect(bodySignal?.aborted).toBe(false);
      expect(fetchChatWorkbenchBootstrap).toHaveBeenCalledOnce();
      expect(fetchSessionDetailWindow).toHaveBeenCalledOnce();
    } finally { unsubscribers.forEach(unsubscribe => unsubscribe()); await page.close(); }
  });

  it("does not cancel pre-existing unobserved reads that the shell did not start", async () => {
    pendingReads();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    void client.prefetchQuery(chatWorkbenchBootstrapQueryOptions(client));
    void client.prefetchQuery({ queryKey: queryKeys.session("remembered"), queryFn: ({ signal }) => fetchSessionDetailWindow("remembered", { signal }) });
    const page = await mount(undefined, undefined, client);
    const bootstrapSignal = vi.mocked(fetchChatWorkbenchBootstrap).mock.calls[0][0]?.signal;
    const bodySignal = vi.mocked(fetchSessionDetailWindow).mock.calls[0][1]?.signal;
    try {
      await page.render({ pathname: "/agents", search: "" });
      expect(bootstrapSignal?.aborted).toBe(false);
      expect(bodySignal?.aborted).toBe(false);
    } finally { await page.close(); }
  });
});
