/** @vitest-environment happy-dom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { SessionQueryResponse } from "../api/types";
import { useSessionSearchQuery } from "./useSessionSearchQuery";

vi.mock("../api/chat", () => ({
  querySessions: vi.fn(),
}));

import { querySessions } from "../api/chat";
const querySessionsMock = vi.mocked(querySessions);

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function page(items: Array<{ id: string }>, nextCursor: string, totalEstimate: number): SessionQueryResponse {
  return {
    items: items.map((entry) => ({ id: entry.id })) as SessionQueryResponse["items"],
    nextCursor,
    totalEstimate,
    filters: { q: "", agentId: "", sessionKind: "", state: "", sort: "updatedAt_desc", limit: 50, cursor: "" },
  };
}

let container: HTMLDivElement;
let root: Root;

type Probe = {
  sessions: Array<{ id: string }>;
  hasMore: boolean;
  totalEstimate?: number;
  loadMore: () => void;
  isLoadingMore: boolean;
};

function renderProbe(initial: { queryText: string; filters?: { agentId: string; teamId: string } }) {
  const probe: Probe = {
    sessions: [],
    hasMore: false,
    totalEstimate: undefined,
    loadMore: () => {},
    isLoadingMore: false,
  };
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  function Probe({ queryText, filters }: { queryText: string; filters: { agentId: string; teamId: string } }) {
    const result = useSessionSearchQuery({ queryText, filters, enabled: true });
    probe.sessions = result.sessions;
    probe.hasMore = result.hasMore;
    probe.totalEstimate = result.totalEstimate;
    probe.loadMore = () => void result.loadMore();
    probe.isLoadingMore = result.isLoadingMore;
    return null;
  }
  act(() => {
    root.render(
      <QueryClientProvider client={client}>
        <Probe queryText={initial.queryText} filters={initial.filters ?? { agentId: "", teamId: "" }} />
      </QueryClientProvider>,
    );
  });
  return {
    probe,
    setQuery: (queryText: string) => {
      act(() => {
        root.render(
          <QueryClientProvider client={client}>
            <Probe queryText={queryText} filters={initial.filters ?? { agentId: "", teamId: "" }} />
          </QueryClientProvider>,
        );
      });
    },
    client,
  };
}

describe("useSessionSearchQuery", () => {
  beforeEach(() => {
    querySessionsMock.mockReset();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => {
      root.unmount();
    });
    container.remove();
  });

  it("debounces the raw query and merges cursor pages with totalEstimate", async () => {
    querySessionsMock
      .mockResolvedValueOnce(page([{ id: "session-1" }, { id: "session-2" }], "2", 3))
      .mockResolvedValueOnce(page([{ id: "session-1" }, { id: "session-2" }], "2", 3))
      .mockResolvedValueOnce(page([{ id: "session-3" }], "", 3));

    const { probe, setQuery } = renderProbe({ queryText: "重构" });

    // Only the debounced value hits the API: one call so far, with q attached.
    await vi.waitFor(() => {
      expect(querySessionsMock).toHaveBeenCalledTimes(1);
      expect(querySessionsMock.mock.calls[0]?.[0]).toMatchObject({ q: "重构", limit: 50, cursor: "" });
      expect(probe.hasMore).toBe(true);
      expect(probe.totalEstimate).toBe(3);
    });

    // Retyping within the debounce window collapses into one request.
    setQuery("重构会");
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 260));
    });
    await vi.waitFor(() => {
      expect(querySessionsMock).toHaveBeenCalledTimes(2);
    });
    expect(querySessionsMock.mock.calls[1]?.[0]).toMatchObject({ q: "重构会" });

    probe.loadMore();
    await vi.waitFor(() => {
      expect(querySessionsMock).toHaveBeenCalledTimes(3);
      expect(querySessionsMock.mock.calls[2]?.[0]).toMatchObject({ cursor: "2" });
      expect(probe.sessions.map((session) => session.id)).toEqual(["session-1", "session-2", "session-3"]);
      expect(probe.hasMore).toBe(false);
    });
  });

  it("forwards agent and team scope filters to the session query", async () => {
    querySessionsMock.mockResolvedValue(page([], "", 0));
    renderProbe({ queryText: "", filters: { agentId: "agent-9", teamId: "team-1" } });

    await vi.waitFor(() => {
      expect(querySessionsMock).toHaveBeenCalledTimes(1);
    });
    expect(querySessionsMock.mock.calls[0]?.[0]).toMatchObject({ agentId: "agent-9", teamId: "team-1" });
  });
});
