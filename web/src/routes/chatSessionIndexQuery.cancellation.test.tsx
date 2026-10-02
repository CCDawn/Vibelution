// @vitest-environment happy-dom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import type { SessionQueryResponse, SessionSummary } from "../api/types";
import { useSessionIndexQuery } from "./chatSessionIndexQuery";

vi.mock("../api/client", () => ({ fetchJson: vi.fn() }));

let root: Root | null;
let container: HTMLElement;
let client: QueryClient;
let settle: (page: SessionQueryResponse) => void;
let signal: AbortSignal;

function page(id: string): SessionQueryResponse {
  return {
    items: [{ id, title: id, status: "ready" } as SessionSummary],
    nextCursor: "",
    totalEstimate: 1,
    filters: { q: "", agentId: "", sessionKind: "", state: "", sort: "updatedAt_desc", limit: 50, cursor: "" },
  };
}

function Reader() {
  useSessionIndexQuery({ queryClient: client, queryText: "", enabled: true, refetchInterval: false, refetchIntervalInBackground: false });
  return null;
}

async function render(first: boolean, second = false) {
  await act(async () => {
    root!.render(<QueryClientProvider client={client}>{first ? <Reader key="first" /> : null}{second ? <Reader key="second" /> : null}</QueryClientProvider>);
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  vi.mocked(fetchJson).mockImplementation((_url, init) => {
    signal = init!.signal as AbortSignal;
    // Deliberately ignore abort here: a late transport must not backfill caches.
    return new Promise<SessionQueryResponse>((resolve) => { settle = resolve; });
  });
});

afterEach(async () => {
  if (root) await act(async () => root!.unmount());
  root = null;
  client.clear();
  container.remove();
});

describe("session index route cancellation", () => {
  it("aborts on navigation and prevents a late response from seeding the list cache", async () => {
    const existing = page("existing").items;
    client.setQueryData(queryKeys.sessions(), existing);
    await render(true);
    expect(signal).toBeInstanceOf(AbortSignal);
    expect(signal.aborted).toBe(false);

    await act(async () => { root!.unmount(); });
    root = null;
    expect(signal.aborted).toBe(true);
    await act(async () => { settle(page("late")); });

    expect(client.getQueryData(queryKeys.sessions())).toEqual(existing);
    expect(client.getQueryData(queryKeys.sessionQuery("", 50))).toBeUndefined();
  });

  it("keeps a shared read alive while another observer still needs it", async () => {
    await render(true, true);
    expect(fetchJson).toHaveBeenCalledTimes(1);
    await render(false, true);
    expect(signal.aborted).toBe(false);

    await act(async () => { settle(page("current")); });
    expect(client.getQueryData<SessionSummary[]>(queryKeys.sessions())?.map((row) => row.id)).toEqual(["current"]);
  });

  it("starts a fresh read when returning before the cancelled response arrives", async () => {
    client.setQueryData(queryKeys.sessions(), page("existing").items);
    await render(true);
    const oldSignal = signal;
    const settleOldRead = settle;

    await render(false);
    expect(oldSignal.aborted).toBe(true);
    await render(true);
    expect(fetchJson).toHaveBeenCalledTimes(2);
    expect(signal).not.toBe(oldSignal);
    expect(signal.aborted).toBe(false);

    await act(async () => { settleOldRead(page("late")); });
    expect(client.getQueryData<SessionSummary[]>(queryKeys.sessions())?.map((row) => row.id)).toEqual(["existing"]);
    await act(async () => { settle(page("fresh")); });
    expect(client.getQueryData<SessionSummary[]>(queryKeys.sessions())?.map((row) => row.id)).toEqual(["existing", "fresh"]);
  });
});
