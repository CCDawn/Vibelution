// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { KnowledgeSemanticIndexBuildResponse, KnowledgeSemanticIndexHealthPayload } from "../api/types";
import { buildKnowledgeSemanticIndex, fetchKnowledgeSemanticIndexHealth } from "../api/knowledgeLifecycle";
import { MemoryKnowledgeSearchPanel, type MemoryKnowledgeSearchPanelCopy } from "./MemoryKnowledgeSearchPanel";

vi.mock("../api/knowledgeLifecycle", () => ({
  buildKnowledgeSemanticIndex: vi.fn(),
  fetchKnowledgeSemanticIndexHealth: vi.fn(),
}));

vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);

const copy: MemoryKnowledgeSearchPanelCopy = {
  ragRetrieval: "RAG retrieval",
  ragContextCandidates: "Context candidates",
  ragRetrievalHint: "Cited candidates from formal knowledge.",
  ragHealth: "Health",
  ragProvider: "Provider",
  ragVector: "Vector",
  ragIndexed: "Indexed",
  ragStale: "Stale",
  ragNoPromptInjection: "Not injected",
  ragCitations: "Citations",
  ragNoContexts: "No contexts",
  noDirectApply: "No direct apply",
  loading: "Loading",
  yes: "Yes",
  no: "No",
  semanticIndex: "Semantic index",
  semanticIndexStatus: "Index status",
  semanticIndexModel: "Embedding model",
  semanticIndexReady: "Ready",
  semanticIndexDegraded: "Partially available",
  semanticIndexUnknown: "Unknown status",
  semanticIndexPrepared: "Model prepared",
  semanticIndexNotPrepared: "Model not prepared",
  semanticIndexLoaded: "Model loaded",
  semanticIndexNotLoaded: "Model not loaded",
  semanticIndexIndexed: "Indexed",
  semanticIndexMissing: "Missing",
  semanticIndexTotal: "Indexable",
  semanticIndexOfflineNote: "Local model; after preparation, rebuilds can run offline.",
  prepareAndBuildSemanticIndex: "Prepare model and build index",
  rebuildSemanticIndex: "Rebuild semantic index",
  semanticIndexBuilding: "Building semantic index…",
  semanticIndexBuildCompleted: "Indexed this run",
  semanticIndexBuildFailed: "Semantic index build did not complete",
  semanticIndexReviewRequired: "Knowledge review permission required",
  semanticIndexUnavailable: "Unavailable",
  knowledgeSearch: "Knowledge search",
  governance: "Governance",
  searchQuery: "Query",
  tags: "Tags",
  searchMode: "Search mode",
  exactSearch: "Exact",
  semanticSearch: "Semantic",
  hybridSearch: "Hybrid",
  ragTopK: "Top K",
  ragContextBudget: "Context budget",
  sourceArtifacts: "Sources",
  semanticScore: "Semantic score",
  noMatches: "No matches",
};

const initialHealth = (overrides: Partial<KnowledgeSemanticIndexHealthPayload> = {}): KnowledgeSemanticIndexHealthPayload => ({
  status: "ready",
  modelPrepared: true,
  modelLoaded: false,
  embeddingModel: "model-a",
  indexedItemCount: 1,
  missingItemCount: 0,
  indexableItemCount: 1,
  vectorEnabled: true,
  ...overrides,
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => { resolve = resolvePromise; });
  return { promise, resolve };
}

let root: Root;
let host: HTMLDivElement;
const onIndexBuilt = vi.fn();

function panelProps(agentId: string, knowledgeBaseId: string) {
  return {
    copy,
    draft: { query: "", tags: "", searchMode: "hybrid" as const, ragTopK: 5, ragMaxContextChars: 1200 },
    resultCount: 0,
    results: [],
    searchPending: false,
    searchErrorText: undefined,
    contexts: [],
    ragHealth: undefined,
    ragProviderHealth: undefined,
    retrievalPolicy: undefined,
    ragContextCount: 0,
    ragCitationCount: 0,
    ragPending: false,
    knowledgeBaseId,
    agentId,
    canReviewKnowledge: true,
    onIndexBuilt,
    onDraftChange: vi.fn(),
  };
}

async function mount(agentId: string, knowledgeBaseId = "kb-1") {
  await act(async () => {
    root.render(<MemoryKnowledgeSearchPanel {...panelProps(agentId, knowledgeBaseId)} />);
  });
}

function button(label: string): HTMLButtonElement {
  const result = [...host.querySelectorAll<HTMLButtonElement>("button")].find((candidate) => candidate.textContent?.includes(label));
  if (!result) {
    throw new Error(`Button not found: ${label}`);
  }
  return result;
}

beforeEach(() => {
  vi.mocked(fetchKnowledgeSemanticIndexHealth).mockReset();
  vi.mocked(buildKnowledgeSemanticIndex).mockReset();
  onIndexBuilt.mockReset();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

describe("MemoryKnowledgeRagPanel semantic-index controls", () => {
  it("clears the previous Agent's index health while the next Agent is loading", async () => {
    const previousHealth = deferred<KnowledgeSemanticIndexHealthPayload>();
    const nextHealth = deferred<KnowledgeSemanticIndexHealthPayload>();
    vi.mocked(fetchKnowledgeSemanticIndexHealth).mockImplementation(({ agentId }) =>
      agentId === "agent-a" ? previousHealth.promise : nextHealth.promise,
    );

    await mount("agent-a");
    expect(host.textContent).toContain("Loading");

    await mount("agent-b");
    expect(host.textContent).not.toContain("model-a");
    expect(host.textContent).toContain("Loading");

    await act(async () => {
      previousHealth.resolve(initialHealth({ embeddingModel: "model-a" }));
      await previousHealth.promise;
    });
    expect(host.textContent).not.toContain("model-a");
    expect(host.textContent).toContain("Loading");

    await act(async () => {
      nextHealth.resolve(initialHealth({ embeddingModel: "model-b", indexedItemCount: 7 }));
      await nextHealth.promise;
    });
    expect(host.textContent).toContain("model-b");
    expect(host.textContent).toContain("Indexed: 7");
  });

  it("shows an in-progress label, prepares once, then reports the completed build", async () => {
    const build = deferred<KnowledgeSemanticIndexBuildResponse>();
    vi.mocked(fetchKnowledgeSemanticIndexHealth)
      .mockResolvedValueOnce(initialHealth({ modelPrepared: false, embeddingModel: "local-model" }))
      .mockResolvedValueOnce(initialHealth({ embeddingModel: "local-model", indexedItemCount: 3, missingItemCount: 2, indexableItemCount: 5 }));
    vi.mocked(buildKnowledgeSemanticIndex).mockReturnValue(build.promise);

    await mount("agent-a");
    await vi.waitFor(() => expect(host.textContent).toContain("local-model"));

    await act(async () => {
      button("Prepare model and build index").click();
      await Promise.resolve();
    });
    expect(button("Building semantic index…")).toBeTruthy();
    expect(buildKnowledgeSemanticIndex).toHaveBeenCalledWith("kb-1", { actorAgentId: "agent-a", prepareModel: true });

    await act(async () => {
      build.resolve({ status: "ready", indexedItemCount: 3, candidateItemCount: 5, knowledgeBaseId: "kb-1" });
      await build.promise;
      await Promise.resolve();
    });
    await vi.waitFor(() => expect(host.textContent).toContain("Indexed this run: 3 / 5"));
    expect(onIndexBuilt).toHaveBeenCalledOnce();
  });

  it("does not carry an earlier knowledge-base build into the next scope", async () => {
    const build = deferred<KnowledgeSemanticIndexBuildResponse>();
    vi.mocked(fetchKnowledgeSemanticIndexHealth).mockResolvedValue(initialHealth({ modelPrepared: false }));
    vi.mocked(buildKnowledgeSemanticIndex).mockReturnValue(build.promise);

    await mount("agent-a", "kb-a");
    await vi.waitFor(() => expect(host.textContent).toContain("model-a"));
    await act(async () => {
      button("Prepare model and build index").click();
      await Promise.resolve();
    });
    expect(button("Building semantic index…")).toBeTruthy();

    await mount("agent-a", "kb-b");
    await vi.waitFor(() => expect(host.textContent).toContain("model-a"));
    expect(host.textContent).not.toContain("Building semantic index…");
    expect(host.textContent).not.toContain("Indexed this run");

    await act(async () => {
      build.resolve({
        status: "degraded",
        indexedItemCount: 2,
        candidateItemCount: 5,
        knowledgeBaseId: "kb-a",
      });
      await build.promise;
      await Promise.resolve();
    });
    expect(host.textContent).not.toContain("Indexed this run");
    expect(host.textContent).not.toContain("Semantic index build did not complete");
    expect(onIndexBuilt).not.toHaveBeenCalled();
    expect(fetchKnowledgeSemanticIndexHealth).toHaveBeenCalledTimes(1);
  });
});
