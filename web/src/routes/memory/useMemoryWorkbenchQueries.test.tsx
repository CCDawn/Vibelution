// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { listAgentSummaries } from "../../api/agents";
import { fetchMemoryAgentDetail, fetchMemoryAgents } from "../../api/memory";
import { useMemoryCoreQueries, type MemoryRouteView } from "./useMemoryWorkbenchQueries";

vi.mock("../../api/agents", () => ({
  listAgentSummaries: vi.fn().mockResolvedValue([]),
  listAgentProjectMemoryUpdates: vi.fn().mockResolvedValue({}),
}));
vi.mock("../../api/memory", () => ({
  fetchMemoryAgents: vi.fn().mockResolvedValue({
    agents: [{ agentId: "saved-agent", hasPrivateMemory: true, fileCount: 1 }],
  }),
  fetchMemoryAgentDetail: vi.fn().mockResolvedValue({ selectedAgent: { agentId: "saved-agent" } }),
  fetchMemoryOverview: vi.fn().mockResolvedValue({}),
  fetchMemoryUsageContract: vi.fn().mockResolvedValue({}),
  fetchMemoryKnowledgeGraph: vi.fn().mockResolvedValue({}),
  fetchMemoryKnowledgeGraphNodeDetail: vi.fn().mockResolvedValue({}),
  fetchGithubProjectLibrary: vi.fn().mockResolvedValue({}),
}));

let root: Root | undefined;
let client: QueryClient | undefined;
let host: HTMLDivElement | undefined;

beforeEach(() => vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true));

afterEach(async () => {
  await act(async () => root?.unmount());
  client?.clear();
  host?.remove();
  root = undefined;
  client = undefined;
  host = undefined;
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

function Probe({ view }: { view: MemoryRouteView }) {
  const result = useMemoryCoreQueries({
    forcedView: view,
    pageVisible: true,
    memoryProposalStatusFilter: "pending",
    requestedKnowledgeActorAgentId: "",
    requestedTeamId: "",
    selectedGraphNodeId: "",
  });
  return <span>{result.selectedAgentMemoryAgentId}</span>;
}

async function show(view: MemoryRouteView) {
  if (!host) {
    host = document.createElement("div");
    document.body.append(host);
    root = createRoot(host);
    client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  }
  await act(async () => {
    root!.render(<QueryClientProvider client={client!}><Probe view={view} /></QueryClientProvider>);
  });
}

describe("memory entry requests", () => {
  it.each(["personal", "agents"] as const)("loads %s selection and content without a second Agent list", async (view) => {
    await show(view);
    await act(async () => {
      await vi.waitFor(() => expect(fetchMemoryAgentDetail).toHaveBeenCalledTimes(1));
    });
    expect(fetchMemoryAgents).toHaveBeenCalledTimes(1);
    expect(listAgentSummaries).not.toHaveBeenCalled();
    expect(host?.textContent).toBe("saved-agent");
    expect(fetchMemoryAgentDetail).toHaveBeenCalledWith("saved-agent", expect.objectContaining({
      actorAgentId: "saved-agent", includeContent: true,
    }));
  });

  it.each(["team", "graph", "manage"] as const)("still loads actor choices when switching to %s", async (view) => {
    await show("personal");
    await act(async () => {
      await vi.waitFor(() => expect(fetchMemoryAgentDetail).toHaveBeenCalledTimes(1));
    });
    await show(view);
    await vi.waitFor(() => expect(listAgentSummaries).toHaveBeenCalledTimes(1));
    expect(fetchMemoryAgents).toHaveBeenCalledTimes(1);
  });
});
