/**
 * Composition-level behavior tests for ResearchProcessWorkspace: loading /
 * error surfacing and deep-link driven inspector visibility. Hook internals
 * are covered by their own dedicated test files.
 * @vitest-environment happy-dom
 */
import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { queryKeys } from "../../../api/queryKeys";

const harness = vi.hoisted(() => ({
  location: {
    runId: "",
    selectedNodeId: null as string | null,
    questionId: "",
    panel: "" as string,
    replaceParams: vi.fn(),
    openPanel: vi.fn(),
    selectNode: vi.fn(),
  },
  runState: {
    run: null as unknown,
    projection: null as unknown,
    error: null as string | null,
    busy: false,
    commandOffers: [] as unknown[],
    createRun: vi.fn(),
    refresh: vi.fn(),
    lastSequence: 0,
    streamState: "idle",
  },
  catalog: {
    effectiveBindings: [] as unknown[],
    questions: [] as unknown[],
    runOptions: [] as unknown[],
    error: null as string | null,
  },
  chain: {
    chainState: null,
    meetings: [] as unknown[],
    collectionRequests: [] as unknown[],
    reviewRoundLinks: [] as unknown[],
    selection: null,
    error: null as string | null,
  },
  nodeDetail: { state: { kind: "idle" } as unknown, retry: vi.fn() },
  insights: { ledger: null, budget: null, hypotheses: null },
  formalCommand: { submit: vi.fn(), commandError: null as string | null, busy: false },
  commands: {
    error: null as string | null,
    busy: false,
    submitRun: vi.fn(),
    pendingTaskId: null as string | null,
    submitOffer: vi.fn(),
  },
}));

vi.mock("./useResearchWorkflowWorkspace", () => ({
  useResearchWorkflowWorkspace: () => harness.location,
}));
vi.mock("./useResearchWorkflowRun", () => ({
  useResearchWorkflowRun: () => harness.runState,
}));
vi.mock("./useResearchWorkflowCatalog", () => ({
  useResearchWorkflowCatalog: () => harness.catalog,
}));
vi.mock("./useHypothesisFirstChain", () => ({
  useHypothesisFirstChain: () => harness.chain,
  useHypothesisFirstChainInvalidation: () => undefined,
}));
vi.mock("./useNodeDetailState", () => ({
  useNodeDetailState: () => harness.nodeDetail,
}));
vi.mock("./useResearchWorkflowInsights", () => ({
  useResearchWorkflowInsights: () => harness.insights,
}));
vi.mock("./useResearchWorkflowCommand", () => ({
  useResearchWorkflowCommand: () => harness.formalCommand,
}));
vi.mock("./useResearchWorkflowCommands", () => ({
  useResearchWorkflowCommands: () => harness.commands,
}));

import { ResearchProcessWorkspace } from "./ResearchProcessWorkspace";

async function renderWorkspace() {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  queryClient.setQueryDefaults(queryKeys.configPublic(), { staleTime: Number.POSITIVE_INFINITY });
  queryClient.setQueryData(queryKeys.configPublic(), { language: "zh" });
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <ResearchProcessWorkspace teamId="research-team" />
        </MemoryRouter>
      </QueryClientProvider>,
    );
  });
  return { container, root };
}

describe("ResearchProcessWorkspace", () => {
  let root: Root | null = null;

  afterEach(async () => {
    if (root) {
      await act(async () => root?.unmount());
      root = null;
    }
    document.body.innerHTML = "";
    vi.clearAllMocks();
    harness.location.runId = "";
    harness.location.selectedNodeId = null;
    harness.location.panel = "";
    harness.runState.error = null;
    harness.commands.error = null;
    harness.formalCommand.commandError = null;
  });

  it("shows the canvas loading state while no projection is available", async () => {
    const rendered = await renderWorkspace();
    root = rendered.root;

    expect(rendered.container.textContent).toContain("加载流程定义");
    expect(rendered.container.querySelector('[data-testid="research-process-workspace-shell"]')).not.toBeNull();
  });

  it("surfaces run-state errors on the canvas host", async () => {
    harness.runState.error = "快照同步失败，请检查网络";
    const rendered = await renderWorkspace();
    root = rendered.root;

    expect(rendered.container.querySelector('[role="alert"]')?.textContent).toContain("快照同步失败，请检查网络");
  });

  it("surfaces command-layer errors on the same canvas alert", async () => {
    harness.commands.error = "命令提交被拒绝";
    const rendered = await renderWorkspace();
    root = rendered.root;

    expect(rendered.container.querySelector('[role="alert"]')?.textContent).toContain("命令提交被拒绝");
  });

  it("keeps the inspector hidden when the node panel has no selection", async () => {
    harness.location.panel = "node";
    const rendered = await renderWorkspace();
    root = rendered.root;

    expect(rendered.container.querySelector('[data-vui="canvas-workbench-inspector"]')).toBeNull();
  });

  it("opens the inspector when the URL deep-links into a node panel", async () => {
    harness.location.panel = "node";
    harness.location.selectedNodeId = "source_finding";
    const rendered = await renderWorkspace();
    root = rendered.root;

    expect(rendered.container.querySelector('[data-vui="canvas-workbench-inspector"]')).not.toBeNull();
  });
});
