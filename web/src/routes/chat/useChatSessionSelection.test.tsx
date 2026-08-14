// @vitest-environment happy-dom
/**
 * Committed-route preference sync behavior (Task 3 acceptance):
 * - A committed session route drives exactly one debounced /select POST;
 * - rapid A→B→A route thrash collapses to one POST for A;
 * - a late /select response for A while the user already views B only updates
 *   A's cache and never chases the pointer back.
 */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { queryKeys } from "../../api/queryKeys";
import type { SessionDetail } from "../../api/types";
import { useChatSessionSelection } from "./useChatSessionSelection";

const fetchJsonMock = vi.fn();
vi.mock("../../api/client", () => ({
  fetchJson: (...args: unknown[]) => fetchJsonMock(...args),
}));

type ChatWorkspaceCacheLike = {
  afterSessionSelected: () => void;
  refreshSessionRuntime: (sessionId: string) => void;
};

function detailFor(sessionId: string): SessionDetail {
  return {
    id: sessionId,
    title: sessionId,
    agentId: "agent-1",
    agentDisplayName: "Agent",
    status: "idle",
    currentPhase: "ready",
    taskSummary: "",
    lastActive: "",
    updatedAt: "",
    createdAt: "",
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

let root: Root | null = null;
let container: HTMLElement;
let queryClient: QueryClient;
let syncSessionDetail: ReturnType<typeof vi.fn>;
let setSessionComposerErrors: ReturnType<typeof vi.fn>;
let cacheLike: ChatWorkspaceCacheLike;
let pendingPromises: Array<{ sessionId: string; resolve: () => void }>;
let resultRef: ReturnType<typeof useChatSessionSelection> | null = null;

function Host({ routeSessionId }: { routeSessionId: string }) {
  const latestRef = React.useRef("");
  const latestAtRef = React.useRef(0);
  const generationRef = React.useRef(0);
  resultRef = useChatSessionSelection({
    queryClient,
    chatWorkspaceCache: cacheLike as never,
    lang: "zh",
    describeError: (error) => String((error as Error)?.message ?? "error"),
    syncSessionDetail,
    setSessionComposerErrors,
    routeSessionId,
    directSessionSelectionGenerationRef: generationRef,
    latestDirectSessionSelectionRef: latestRef,
    latestDirectSessionSelectionAtRef: latestAtRef,
  });
  return null;
}

function mount(routeSessionId: string) {
  queryClient = new QueryClient();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  act(() => {
    root!.render(
      React.createElement(
        QueryClientProvider,
        { client: queryClient },
        React.createElement(Host, { routeSessionId }),
      ),
    );
  });
}

function rerender(routeSessionId: string) {
  act(() => {
    root!.render(
      React.createElement(
        QueryClientProvider,
        { client: queryClient },
        React.createElement(Host, { routeSessionId }),
      ),
    );
  });
}

async function flushDebounce(ms = 120) {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, ms));
  });
}

beforeEach(() => {
  fetchJsonMock.mockReset();
  syncSessionDetail = vi.fn();
  setSessionComposerErrors = vi.fn();
  pendingPromises = [];
  cacheLike = {
    afterSessionSelected: vi.fn(),
    refreshSessionRuntime: vi.fn(),
  };
});

afterEach(() => {
  act(() => {
    root?.unmount();
  });
  root = null;
  container?.remove();
  resultRef = null;
});

describe("useChatSessionSelection committed-route preference sync", () => {
  it("does not send /select for temp session routes", async () => {
    mount("temp-session-local-1");
    await flushDebounce();
    expect(fetchJsonMock).not.toHaveBeenCalled();
  });

  it("drives one debounced /select POST for the committed session route", async () => {
    fetchJsonMock.mockImplementation((url: string) => {
      expect(url).toContain("/api/sessions/session-a/select");
      return Promise.resolve(detailFor("session-a"));
    });
    mount("session-a");
    await flushDebounce();
    expect(fetchJsonMock).toHaveBeenCalledTimes(1);
    expect(syncSessionDetail).toHaveBeenCalledWith(expect.objectContaining({ id: "session-a" }));
  });

  it("collapses rapid A→B→A route thrash into one POST for the final target", async () => {
    fetchJsonMock.mockImplementation((url: string) => {
      const match = url.match(/\/api\/sessions\/([^/]+)\/select/);
      const sessionId = match?.[1] ?? "";
      return Promise.resolve(detailFor(sessionId));
    });
    mount("session-a");
    rerender("session-b");
    rerender("session-a");
    await flushDebounce();
    expect(fetchJsonMock).toHaveBeenCalledTimes(1);
    expect(fetchJsonMock.mock.calls[0][0]).toContain("/api/sessions/session-a/select");
    expect(syncSessionDetail).toHaveBeenCalledWith(expect.objectContaining({ id: "session-a" }));
  });

  it("drops a late /select response for A while the user already views B", async () => {
    let resolveA: (value: SessionDetail) => void = () => undefined;
    let resolveB: (value: SessionDetail) => void = () => undefined;
    fetchJsonMock.mockImplementation((url: string) => {
      const match = url.match(/\/api\/sessions\/([^/]+)\/select/);
      const sessionId = match?.[1] ?? "";
      return new Promise<SessionDetail>((resolve) => {
        if (sessionId === "session-a") {
          resolveA = resolve;
        } else {
          resolveB = resolve;
        }
      });
    });

    mount("session-a");
    await flushDebounce();
    // User clicks B before A's /select returns.
    rerender("session-b");
    await flushDebounce();
    // B's response arrives; then A's stale response arrives last.
    await act(async () => {
      resolveB(detailFor("session-b"));
      await Promise.resolve();
    });
    await act(async () => {
      resolveA(detailFor("session-a"));
      await Promise.resolve();
    });

    // A's late response must never repaint A or chase the pointer: generation
    // dedup drops it entirely; only B's cache is seeded.
    const calls = fetchJsonMock.mock.calls.map((args) => String(args[0]));
    expect(calls).toHaveLength(2);
    expect(syncSessionDetail).toHaveBeenCalledTimes(1);
    expect(syncSessionDetail).toHaveBeenCalledWith(expect.objectContaining({ id: "session-b" }));
    expect(syncSessionDetail).not.toHaveBeenCalledWith(expect.objectContaining({ id: "session-a" }));
    expect(queryClient.getQueryData(queryKeys.session("session-a"))).toBeUndefined();
  });

  it("keeps the last-viewed pointer write passive even when /select fails", async () => {
    fetchJsonMock.mockRejectedValue(new Error("select failed"));
    mount("session-a");
    await flushDebounce();
    expect(setSessionComposerErrors).toHaveBeenCalled();
    expect(cacheLike.refreshSessionRuntime).toHaveBeenCalledWith("session-a");
  });
});
