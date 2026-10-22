// @vitest-environment happy-dom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { act, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { SessionDetail, SessionSummary } from "../../api/types";
import { queryKeys } from "../../api/queryKeys";
import { WorkbenchStartupReadyContext, useReportWorkbenchStartupReady } from "../../app/workbenchStartupReady";
import { resolveChatLiveQueryPolicy, type ChatLiveQueryPolicyInput } from "../chatLiveQueryPolicy";
import { buildSessionDetailShellFromSummary } from "./chatSessionDetailHelpers";
import { shouldWaitForChatStartupRestore, useChatSessionDetailQueries, type UseChatSessionDetailQueriesInput } from "./useChatSessionDetailQueries";
import { useChatWorkbenchCatalogQueries, type ChatWorkbenchCatalogQueriesInput } from "./useChatWorkbenchCatalogQueries";

const reads = vi.hoisted(() => ({ detail: vi.fn(), telemetry: vi.fn(), teams: vi.fn(async () => []) }));
vi.mock("./chatSessionDetailHelpers", async (importOriginal) => ({
  ...await importOriginal<typeof import("./chatSessionDetailHelpers")>(),
  fetchSessionDetailWindow: reads.detail,
}));
vi.mock("../../app/browserTelemetry", () => ({ postBrowserTelemetry: reads.telemetry }));
vi.mock("../../api/teams", () => ({ listTeams: reads.teams }));
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
afterEach(() => vi.resetAllMocks());

const summary = { id: "current", agentId: "agent" } as SessionSummary;
const fullDetail = { ...buildSessionDetailShellFromSummary(summary)!, provisionalTranscript: false };
const policyInput: ChatLiveQueryPolicyInput = {
  chatPollingVisible: false, chatStartupWarmupActive: false,
  directSessionBackgroundSyncActive: false, groupBackgroundSyncActive: false,
  directSessionPanelActive: true, standardGroupRoomActive: false,
  sessionStreamAvailable: false, sessionStreamShouldConnect: false, sessionStreamConnected: false,
  groupStreamShouldConnect: false, groupStreamConnected: false,
  activeSessionId: "", activeRootSessionId: "",
};

async function flush() {
  await act(async () => {
    await Promise.resolve();
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

function StartupCatalog({ client, enabled }: { client: QueryClient; enabled: boolean }) {
  useChatWorkbenchCatalogQueries({
    queryClient: client, secondaryChatDataEnabled: enabled,
    chatSecondaryPollPolicy: {}, chatLiveQueryPolicy: {}, sessionQueryText: "",
    activeSessionId: summary.id, requestedSessionId: summary.id, requestedRoomId: "",
    activeGroupRoomId: "", expandedGroupAgentSessionIds: [], groupComposerOpen: false,
    standardGroupRoomActive: false, projectBusActive: false, chatPollingVisible: false,
    chatStartupWarmupActive: false, groupBackgroundSyncActive: false, groupStreamConnected: false,
    showArchivedSessions: false,
  } as ChatWorkbenchCatalogQueriesInput);
  return null;
}

async function mount(overrides: Partial<UseChatSessionDetailQueriesInput> = {}, cached?: SessionDetail, withCatalog = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  if (cached) client.setQueryData(queryKeys.session(cached.id), cached);
  if (withCatalog) {
    const sessionPage = { items: [summary], nextCursor: "" };
    client.setQueryData(["sessions", "active-bootstrap"], {
      activeSessionId: summary.id, sessionPage, directoryReady: true, agents: [], conversations: [],
    });
    client.setQueryData(queryKeys.sessionQuery("", 50), { pages: [sessionPage], pageParams: [""] });
    client.setQueryData(queryKeys.agents(), []);
    client.setQueryData(queryKeys.configPublic(), {});
    client.setQueryData(queryKeys.runtimeSummary(), {});
    client.setQueryData(queryKeys.skills(), { skills: [] });
    client.setQueryData(queryKeys.conversationsCatalogQuery(100), { pages: [{ items: [], nextCursor: "" }], pageParams: [""] });
  }
  const reportReady = vi.fn();
  let result!: ReturnType<typeof useChatSessionDetailQueries>;
  let ready = false;
  let renderCount = 0;
  function Page({ input }: { input: Partial<UseChatSessionDetailQueriesInput> }) {
    if (++renderCount > 100) throw new Error("Startup detail exceeded the bounded render budget");
    const [startupReady, setStartupReady] = useState(false);
    const [settledId, setSettledId] = useState("");
    const startedAt = useRef(Date.now());
    const logged = useRef(false);
    const snapshot = useRef({ shouldConnect: false } as UseChatSessionDetailQueriesInput["sessionStreamDecisionSnapshotRef"]["current"]);
    result = useChatSessionDetailQueries({
      activeSessionId: null, bareRouteRestorePending: false,
      queryClient: client, sessions: [], directSessionActiveSummary: undefined,
      chatLiveQueryPolicy: resolveChatLiveQueryPolicy(policyInput), chatLiveQueryPolicyInput: policyInput,
      secondaryChatDataEnabled: false, directSessionPanelActive: true,
      standardGroupRoomActive: false, activeGroupRoom: undefined, financeSurface: false,
      runtime: undefined, conversations: undefined, teams: undefined, pageVisible: false,
      chatStartupDataReady: startupReady, setChatStartupDataReady: setStartupReady,
      startupDetailSettledSessionId: settledId, setStartupDetailSettledSessionId: setSettledId,
      setDirectSessionBackgroundSyncActive: () => undefined,
      chatRouteMountStartedAtRef: startedAt, chatRouteStartupReadyLoggedRef: logged,
      sessionStreamDecisionSnapshotRef: snapshot,
      ...input,
    });
    ready = startupReady;
    useReportWorkbenchStartupReady(startupReady, [result.sessionDetailQuery]);
    return withCatalog ? <StartupCatalog client={client} enabled={startupReady && settledId === input.activeSessionId} /> : null;
  }
  const root = createRoot(document.createElement("div"));
  async function render(input = overrides) {
    await act(async () => root.render(
      <QueryClientProvider client={client}><WorkbenchStartupReadyContext.Provider value={reportReady}>
        <Page input={input} />
      </WorkbenchStartupReadyContext.Provider></QueryClientProvider>,
    ));
    await flush();
  }
  await render();
  return {
    client, reportReady, render,
    get result() { return result; },
    get ready() { return ready; },
    async dispose() { await act(async () => root.unmount()); client.clear(); },
  };
}

describe("Chat startup detail priority", () => {
  it("waits when the session index wins the race with the Agent directory", async () => {
    const pending = (routeVisibleSessions: SessionSummary[] | undefined, agentDirectoryFailed = false) => shouldWaitForChatStartupRestore({
      bareRoute: true, routeVisibleSessions, agentDirectoryFailed,
    });
    const page = await mount({ sessions: [summary], bareRouteRestorePending: pending(undefined) });
    try {
      expect(page.ready).toBe(false);
      await page.render({ sessions: [summary], bareRouteRestorePending: pending([summary]) });
      expect(page.ready).toBe(false);
      // A failed directory cannot keep startup waiting for a target forever.
      await page.render({ sessions: [summary], bareRouteRestorePending: pending(undefined, true) });
      expect(page.ready).toBe(true);
      expect(shouldWaitForChatStartupRestore({ bareRoute: false, routeVisibleSessions: undefined, agentDirectoryFailed: false })).toBe(false);
      expect(pending([])).toBe(false);
    } finally { await page.dispose(); }
  });

  it("keeps secondary work gated across bare-route restoration and summary placeholders", async () => {
    let resolveDetail!: (detail: SessionDetail) => void;
    reads.detail.mockReturnValue(new Promise((resolve) => { resolveDetail = resolve; }));
    const page = await mount({ sessions: [summary], bareRouteRestorePending: true });
    try {
      expect(page.ready).toBe(false);
      expect(page.reportReady).not.toHaveBeenCalled();
      await page.render({ sessions: [summary], activeSessionId: summary.id });
      expect(page.result.sessionDetailQuery.isPlaceholderData).toBe(true);
      expect(page.ready).toBe(false);
      expect(page.reportReady).not.toHaveBeenCalled();
      await act(async () => resolveDetail(fullDetail));
      await flush();
      expect(page.ready).toBe(true);
      expect(page.reportReady).toHaveBeenCalledOnce();
    } finally { await page.dispose(); }
  });

  it("does not treat a provisional cache row as restored transcript", async () => {
    reads.detail.mockReturnValue(new Promise(() => {}));
    const page = await mount({ sessions: [summary], activeSessionId: summary.id }, buildSessionDetailShellFromSummary(summary));
    try {
      expect(page.ready).toBe(false);
      expect(page.reportReady).not.toHaveBeenCalled();
    } finally { await page.dispose(); }
  });

  it.each([
    { name: "empty directory", input: {} },
    { name: "directory with no restore candidate", input: { sessions: [{ ...summary, hiddenFromIndex: true }] } },
    { name: "local temporary session", input: { activeSessionId: "temp-session-local", sessions: [{ ...summary, id: "temp-session-local" }] }, cached: { ...fullDetail, id: "temp-session-local" } },
    { name: "cached transcript", input: { activeSessionId: summary.id, sessions: [summary] }, cached: fullDetail },
    { name: "Finance surface", input: { financeSurface: true } },
  ])("releases startup for $name", async ({ input, cached }) => {
    reads.detail.mockReturnValue(new Promise(() => {}));
    const page = await mount(input, cached);
    try {
      expect(page.ready).toBe(true);
      expect(page.reportReady).toHaveBeenCalledOnce();
      if (input.activeSessionId === "temp-session-local") expect(reads.detail).not.toHaveBeenCalled();
    } finally { await page.dispose(); }
  });

  it("waits for the selected group room", async () => {
    const page = await mount({ standardGroupRoomActive: true });
    try {
      expect(page.ready).toBe(false);
      await page.render({ standardGroupRoomActive: true, activeGroupRoom: { id: "room" } as UseChatSessionDetailQueriesInput["activeGroupRoom"] });
      expect(page.ready).toBe(true);
    } finally { await page.dispose(); }
  });

  it("releases the shell and teams on detail failure without reporting a loaded transcript", async () => {
    reads.detail.mockRejectedValue(new Error("detail unavailable"));
    const page = await mount({ activeSessionId: summary.id, sessions: [summary] }, undefined, true);
    try {
      await flush();
      expect(page.result.sessionDetailQuery.isError).toBe(true);
      expect(page.ready).toBe(true);
      expect(page.reportReady).toHaveBeenCalledOnce();
      await flush();
      expect(reads.teams).toHaveBeenCalledOnce();
      expect(reads.telemetry).toHaveBeenCalledWith(expect.objectContaining({ eventCode: "browser.chat_route.startup_data_failed" }));
      expect(reads.telemetry).not.toHaveBeenCalledWith(expect.objectContaining({ eventCode: "browser.chat_route.startup_data_ready" }));
    } finally { await page.dispose(); }
  });
});
