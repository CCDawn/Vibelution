// @vitest-environment happy-dom
/**
 * Behavioral gate for the composer knowledge-reference item query.
 *
 * The composer "reference" dropdown used to enumerate citable knowledge items
 * with an unconditional empty-query `GET /api/knowledge/search` that fired on
 * every chat-workbench mount and agent switch — the dominant source of the
 * live audit's scopeless empty-query search noise. `searchKnowledgeItems`
 * remains the data source (it is the only endpoint enumerating items across
 * the agent's private plus team-readable bases with a server-side limit), but
 * the call must stay gated on the agent-scoped knowledge overview: when
 * `summary.itemCount` is 0 the search provably cannot return anything, so no
 * request may leave the page. This test mounts only the extracted query hook.
 */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useComposerKnowledgeReferenceQueries } from "./useComposerKnowledgeReferenceQueries";

// happy-dom needs an explicit act environment; without it act() only warns.
// Repo pattern: (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// vi.mock factories are hoisted above imports; vi.hoisted guarantees the mock
// binding exists before the factory is first invoked.
const { fetchJsonMock } = vi.hoisted(() => ({
  fetchJsonMock: vi.fn(),
}));

vi.mock("../../api/client", () => ({
  fetchJson: (...args: unknown[]) => fetchJsonMock(...args),
}));

let root: Root | null = null;
let container: HTMLElement;
let queryClient: QueryClient;
let overviewItemCount = 0;
let hostDataSnapshots: Array<{ bases: unknown; items: unknown }> = [];

function Host({ agentId, draft = "" }: { agentId: string; draft?: string }) {
  // Consuming `.data` registers the tracked props that let the observer
  // re-render the host when the overview lands (and the gate flips).
  const { agentKnowledgeBasesQuery, agentKnowledgeItemsQuery, knowledgeReferenceState } =
    useComposerKnowledgeReferenceQueries(agentId, draft);
  hostDataSnapshots.push({
    bases: agentKnowledgeBasesQuery.data,
    items: agentKnowledgeItemsQuery.data,
  });
  return <button onClick={knowledgeReferenceState.onRequest} data-loading={knowledgeReferenceState.loading} data-error={knowledgeReferenceState.error}>Load</button>;
}

function mount(agentId: string, requested = true, draft = "") {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  act(() => {
    root!.render(
      React.createElement(
        QueryClientProvider,
        { client: queryClient },
        React.createElement(Host, { agentId, draft }),
      ),
    );
  });
  if (requested) act(() => container.querySelector("button")!.click());
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

function requestedPaths(): string[] {
  return fetchJsonMock.mock.calls.map((call) => String(call[0]));
}

beforeEach(() => {
  fetchJsonMock.mockReset();
  overviewItemCount = 0;
  fetchJsonMock.mockImplementation((url: unknown) => {
    const path = String(url);
    if (path.includes("/api/knowledge/overview")) {
      return Promise.resolve({ summary: { itemCount: overviewItemCount } });
    }
    if (path.includes("/api/knowledge/search")) {
      return Promise.resolve({ results: [] });
    }
    if (path.includes("/knowledge-bases")) {
      return Promise.resolve({ knowledgeBases: [] });
    }
    throw new Error(`unexpected knowledge fetch: ${path}`);
  });
  queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });
  hostDataSnapshots = [];
});

afterEach(() => {
  act(() => {
    root?.unmount();
  });
  root = null;
  container?.remove();
});

describe("composer knowledge-reference query gate", () => {
  it("makes no knowledge requests on mount until the picker is requested", async () => {
    overviewItemCount = 3;
    mount("agent-1", false);
    await flush();
    expect(requestedPaths()).toEqual([]);
    act(() => container.querySelector("button")!.click());
    await vi.waitFor(() => expect(requestedPaths().some(path => path.includes("/search"))).toBe(true));
    expect(requestedPaths()).toHaveLength(3);
    act(() => container.querySelector("button")!.click());
    await flush();
    expect(requestedPaths()).toHaveLength(3);
  });

  it("loads candidates for @ input without opening the picker", async () => {
    overviewItemCount = 1;
    mount("agent-1", false, "请查看 @文档");
    await vi.waitFor(() => expect(requestedPaths().some(path => path.includes("/search"))).toBe(true));
  });

  it("does not carry picker demand to a different agent", async () => {
    mount("agent-1");
    await vi.waitFor(() => expect(requestedPaths()).toHaveLength(2));
    act(() => root!.render(<QueryClientProvider client={queryClient}><Host agentId="agent-2" /></QueryClientProvider>));
    await flush();
    expect(requestedPaths()).toHaveLength(2);
    act(() => container.querySelector("button")!.click());
    await vi.waitFor(() => expect(requestedPaths()).toHaveLength(4));
    expect(requestedPaths().slice(2).every(path => path.includes("agent-2"))).toBe(true);
  });

  it("exposes a failed lookup and retries it on request", async () => {
    fetchJsonMock.mockRejectedValueOnce(new Error("offline"));
    mount("agent-1");
    await vi.waitFor(() => expect(container.querySelector("button")?.dataset.error).toBe("true"));
    act(() => container.querySelector("button")!.click());
    await vi.waitFor(() => expect(container.querySelector("button")?.dataset.error).toBe("false"));
  });
  it("skips the empty-query search when the overview proves the agent owns no knowledge items", async () => {
    overviewItemCount = 0;
    mount("agent-1");
    await flush();

    // Wait until the cheap metadata lookups have actually landed, then let a
    // real-timer settle window pass: if the gate were broken the search would
    // fire on the same enable chain test 2 proves fires within this window.
    await vi.waitFor(() => {
      expect(requestedPaths().some((path) => path.includes("/api/knowledge/overview"))).toBe(true);
      expect(requestedPaths().some((path) => path.includes("/api/agents/agent-1/knowledge-bases"))).toBe(true);
    });
    await new Promise((resolve) => setTimeout(resolve, 150));

    const paths = requestedPaths();
    expect(paths.some((path) => path.includes("/api/knowledge/search"))).toBe(false);
  });

  it("issues the scoped search once the overview reports reachable items", async () => {
    overviewItemCount = 3;
    mount("agent-1");
    // The gated search fires through a chained enable (overview resolves ->
    // observer re-render -> enabled flips -> fetch effect), which spans
    // microtasks plus scheduler work; fixed microtask flushes race it, so poll
    // on real timers until the request has actually left the page.
    await vi.waitFor(() => {
      expect(requestedPaths().some((path) => path.includes("/api/knowledge/search"))).toBe(true);
    });

    const searchCalls = requestedPaths().filter((path) => path.includes("/api/knowledge/search"));
    expect(searchCalls).toHaveLength(1);
    expect(searchCalls[0]).toContain("agentId=agent-1");
    expect(searchCalls[0]).toContain("limit=20");
  });

  it("issues no knowledge requests at all without an agent id", async () => {
    mount("");
    await flush();

    expect(requestedPaths().some((path) => path.includes("/api/knowledge"))).toBe(false);
    expect(requestedPaths().some((path) => path.includes("knowledge-bases"))).toBe(false);
  });
});
