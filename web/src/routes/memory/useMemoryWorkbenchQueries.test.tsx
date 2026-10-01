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

beforeEach(() => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  vi.mocked(fetchMemoryAgents).mockReset().mockResolvedValue({
    agents: [{ agentId: "saved-agent", hasPrivateMemory: true, fileCount: 1 }],
  });
  vi.mocked(fetchMemoryAgentDetail).mockReset().mockResolvedValue({ selectedAgent: { agentId: "saved-agent" } });
});

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

function Probe({ view, actor = "" }: { view: MemoryRouteView; actor?: string }) {
  const result = useMemoryCoreQueries({
    forcedView: view,
    pageVisible: true,
    memoryProposalStatusFilter: "pending",
    requestedKnowledgeActorAgentId: actor,
    requestedTeamId: "",
    selectedGraphNodeId: "",
  });
  const content = result.agentMemoryDetailQuery.data?.selectedAgent?.items?.[0]?.content;
  return <span data-generation={result.agentMemoryInventoryQuery.data?.generatedAt}>
    {result.selectedAgentMemoryAgentId}{content ? `:${content}` : ""}
  </span>;
}

async function show(view: MemoryRouteView, actor = "") {
  if (!host) {
    host = document.createElement("div");
    document.body.append(host);
    root = createRoot(host);
    client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  }
  await act(async () => {
    root!.render(<QueryClientProvider client={client!}><Probe view={view} actor={actor} /></QueryClientProvider>);
  });
}

describe("memory entry requests", () => {
  it.each(["personal", "agents"] as const)("loads %s selection and content without a second Agent list", async (view) => {
    await show(view);
    await act(async () => {
      await expectEventually(() => expect(fetchMemoryAgentDetail).toHaveBeenCalledTimes(1));
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
      await expectEventually(() => expect(fetchMemoryAgentDetail).toHaveBeenCalledTimes(1));
    });
    await show(view);
    await expectEventually(() => expect(listAgentSummaries).toHaveBeenCalledTimes(1));
    expect(fetchMemoryAgents).toHaveBeenCalledTimes(1);
  });

  it("refreshes open content when the selected Agent changes in the inventory", async () => {
    vi.mocked(fetchMemoryAgents).mockResolvedValue(inventory("r1"));
    vi.mocked(fetchMemoryAgentDetail)
      .mockResolvedValueOnce(detail("before"))
      .mockResolvedValueOnce(detail("after!"));
    await show("personal", "saved-agent");
    await expectEventually(() => expect(host?.textContent).toBe("saved-agent:before"));

    await act(async () => { client!.setQueryData(["memory", "agents", "inventory"], inventory("r2")); });

    await expectEventually(() => expect(host?.textContent).toBe("saved-agent:after!"));
    expect(fetchMemoryAgentDetail).toHaveBeenCalledTimes(2);
    expect(listAgentSummaries).not.toHaveBeenCalled();
  });

  it("does not reread content for a new poll timestamp or another Agent's changes", async () => {
    vi.mocked(fetchMemoryAgents).mockResolvedValue(inventory("r1"));
    vi.mocked(fetchMemoryAgentDetail).mockResolvedValue(detail("before"));
    await show("personal", "saved-agent");
    await expectEventually(() => expect(host?.textContent).toBe("saved-agent:before"));
    const changed = inventory("r1");
    changed.generatedAt = "later";
    changed.agents.push({ ...changed.agents[0], agentId: "other-agent", items: [{ id: "other", revision: "new", content: "" }] });

    await act(async () => { client!.setQueryData(["memory", "agents", "inventory"], changed); });

    await expectEventually(() => expect(host?.querySelector("span")?.getAttribute("data-generation")).toBe("later"));
    expect(fetchMemoryAgentDetail).toHaveBeenCalledTimes(1);
    expect(host?.textContent).toBe("saved-agent:before");
  });

  it("removes deleted content after the next inventory update", async () => {
    vi.mocked(fetchMemoryAgents).mockResolvedValue(inventory("r1"));
    vi.mocked(fetchMemoryAgentDetail)
      .mockResolvedValueOnce(detail("before"))
      .mockResolvedValueOnce({ selectedAgent: { agentId: "saved-agent", items: [] } });
    await show("personal", "saved-agent");
    await expectEventually(() => expect(host?.textContent).toBe("saved-agent:before"));
    const changed = inventory("r1");
    changed.agents[0].items = [];
    changed.agents[0].fileCount = 0;

    await act(async () => { client!.setQueryData(["memory", "agents", "inventory"], changed); });

    await expectEventually(() => expect(fetchMemoryAgentDetail).toHaveBeenCalledTimes(2));
    await expectEventually(() => expect(host?.textContent).toBe("saved-agent"));
  });

  it("never uses the previous Agent's content as a placeholder when switching", async () => {
    const initial = inventory("r1");
    initial.agents.push({ ...initial.agents[0], agentId: "other-agent" });
    vi.mocked(fetchMemoryAgents).mockResolvedValue(initial);
    vi.mocked(fetchMemoryAgentDetail).mockResolvedValueOnce(detail("private-body"));
    await show("personal", "saved-agent");
    await expectEventually(() => expect(host?.textContent).toBe("saved-agent:private-body"));
    let settle!: (value: unknown) => void;
    vi.mocked(fetchMemoryAgentDetail).mockImplementationOnce(() => new Promise((resolve) => { settle = resolve; }));

    await show("personal", "other-agent");

    await expectEventually(() => expect(fetchMemoryAgentDetail).toHaveBeenCalledTimes(2));
    expect(host?.textContent).toBe("other-agent");
    await act(async () => { settle({ selectedAgent: { agentId: "other-agent", items: [] } }); });
  });
});

function inventory(revision: string) {
  return {
    generatedAt: "initial",
    agents: [{
      agentId: "saved-agent", hasPrivateMemory: true, fileCount: 1,
      items: [{ id: "lesson", revision, content: "" }],
    }],
  };
}

function detail(content: string) {
  return { selectedAgent: { agentId: "saved-agent", items: [{ id: "lesson", content }] } };
}

async function expectEventually(assertion: () => unknown) {
  await act(async () => { await vi.waitFor(assertion); });
}
