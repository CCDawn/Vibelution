/**
 * Composition-level behavior tests for ResearchProcessWorkspace: loading /
 * error surfacing, deep-link driven inspector visibility, and experiment
 * switcher selection semantics. Hook internals are covered by their own
 * dedicated test files.
 * @vitest-environment happy-dom
 */
import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { queryKeys } from "../../../api/queryKeys";
import type {
  ResearchWorkflowLaunchOption,
  WorkflowRunRecord,
} from "../../../api/researchWorkflow";

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
    questionId: "",
    questionScopeKey: "research-team::no-question",
    scopeMismatch: false,
    chainState: null,
    meetings: [] as unknown[],
    collectionRequests: [] as unknown[],
    reviewRoundLinks: [] as unknown[],
    selection: null,
    loading: false,
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
vi.mock("./hypothesisFirstFocus", () => ({
  fetchHypothesisFirstFocusNode: vi.fn(async () => "hf_generation"),
}));
vi.mock("../../../components/vui", async () => {
  const actual = await vi.importActual<typeof import("../../../components/vui")>("../../../components/vui");
  return {
    ...actual,
    VCanvasWorkbenchPage: (props: {
      toolbar?: React.ReactNode;
      rail?: React.ReactNode;
      canvas?: React.ReactNode;
      inspector?: React.ReactNode;
      shellTestId?: string;
    }) => (
      <div data-testid={props.shellTestId ?? "research-process-workspace-shell"}>
        {props.toolbar}
        <div data-vui="canvas-workbench-canvas">{props.canvas}</div>
        <div data-vui="canvas-workbench-inspector">{props.inspector}</div>
      </div>
    ),
  };
});
vi.mock("./ResearchWorkflowCanvasPane", () => ({
  ResearchWorkflowCanvasPane: (props: { error?: string | null }) => (
    <div role={props.error ? "alert" : undefined}>{props.error || "加载流程定义"}</div>
  ),
}));

import { fetchHypothesisFirstFocusNode } from "./hypothesisFirstFocus";
import { ResearchProcessWorkspace } from "./ResearchProcessWorkspace";

const mockedFocus = vi.mocked(fetchHypothesisFirstFocusNode);

const checkpointQuestion: ResearchWorkflowLaunchOption = {
  questionId: "SCI-096",
  title: "What are the coding principles embedded in neuronal spike trains?",
  scope: "neuroscience",
  domain: "neuroscience",
  catalogId: "science-125-questions-2021",
  reviewRunId: "",
  artifactSha256: "",
  source: "catalog",
  launchable: true,
  checkpoint: {
    runId: "run-96",
    status: "waiting_human",
    currentNodeId: "knowledge_handoff",
    currentNodeLabel: "知识包交接",
    completedCount: 4,
    totalSteps: 16,
    resumable: true,
  },
};

const restoreQuestion: ResearchWorkflowLaunchOption = {
  ...checkpointQuestion,
  questionId: "SCI-003",
  title: "Is the Riemann hypothesis true?",
  scope: "mathematical_sciences",
  domain: "mathematical_sciences",
  checkpoint: {
    runId: "run-3",
    status: "running",
    currentNodeId: "protocol_design",
    currentNodeLabel: "协议设计",
    completedCount: 6,
    totalSteps: 16,
    resumable: true,
  },
};

const freshQuestion: ResearchWorkflowLaunchOption = {
  ...checkpointQuestion,
  questionId: "SCI-005",
  title: "Fresh question",
  checkpoint: null,
};

const currentRun = {
  runId: "run-96",
  questionId: "SCI-096",
  runVersion: 1,
  status: "waiting_human",
  workflowId: "challenge-cup-research",
  workflowVersionId: "v1",
  teamId: "research-team",
  projectId: "project-x",
  runtimeCurrentNodeIds: ["knowledge_handoff"],
} as WorkflowRunRecord;

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
          <ResearchProcessWorkspace teamId="research-team" lang="zh" />
        </MemoryRouter>
      </QueryClientProvider>,
    );
  });
  return { container, root };
}

async function openSwitchSelect(trigger: HTMLElement): Promise<NodeListOf<Element>> {
  await act(async () => {
    trigger.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
  let options = document.body.querySelectorAll('[role="option"]');
  if (!options.length) {
    await act(async () => {
      trigger.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true, button: 0 }));
    });
    options = document.body.querySelectorAll('[role="option"]');
  }
  return options;
}

async function pickSwitchOption(option: HTMLElement): Promise<void> {
  await act(async () => {
    option.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
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
    harness.location.questionId = "";
    harness.location.panel = "";
    harness.runState.error = null;
    harness.commands.error = null;
    harness.formalCommand.commandError = null;
    harness.chain.chainState = null;
    harness.chain.questionId = "";
    harness.chain.scopeMismatch = false;
    harness.chain.meetings = [];
    harness.chain.collectionRequests = [];
    harness.chain.reviewRoundLinks = [];
    harness.chain.selection = null;
    harness.chain.loading = false;
  });

  it("shows the canvas loading state while no projection is available", async () => {
    const rendered = await renderWorkspace();
    root = rendered.root;

    expect(rendered.container.textContent).toContain("加载流程定义");
    expect(rendered.container.querySelector('[data-testid="research-process-workspace-shell"]')).not.toBeNull();
  });

  it("leaves overall progress to the parent rail and keeps this workspace focused on canvas details", async () => {
    const rendered = await renderWorkspace();
    root = rendered.root;

    expect(rendered.container.querySelector('[data-testid="research-process-rail"]')).toBeNull();
    expect(rendered.container.querySelector('[data-vui="canvas-workbench-rail"]')).toBeNull();
    expect(rendered.container.querySelector('[data-vui="canvas-workbench-canvas"]')).not.toBeNull();
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

  it("keeps the inspector mounted when the node panel has no selection", async () => {
    harness.location.panel = "node";
    const rendered = await renderWorkspace();
    root = rendered.root;

    expect(rendered.container.querySelector('[data-vui="canvas-workbench-inspector"]')).not.toBeNull();
  });

  it("does not autofocus convergence while the hypothesis chain is still loading", async () => {
    harness.location.panel = "node";
    harness.location.questionId = "SCI-096";
    harness.runState.projection = {
      definition: { nodes: [], edges: [], stages: [] },
      run: { runtimeCurrentNodeIds: [], nodeRuns: {} },
    } as never;
    harness.chain.chainState = { hypothesisConverged: true } as never;
    harness.chain.loading = true;
    const rendered = await renderWorkspace();
    root = rendered.root;

    expect(harness.location.replaceParams).not.toHaveBeenCalled();
  });

  it("fails closed and hides stale commands when the chain scope mismatches", async () => {
    harness.location.panel = "node";
    harness.location.questionId = "SCI-004";
    harness.location.selectedNodeId = "hf_selection";
    harness.chain.questionId = "SCI-004";
    harness.chain.scopeMismatch = true;
    harness.runState.projection = {
      definition: { nodes: [], edges: [], stages: [] },
      run: { teamId: "research-team", runtimeCurrentNodeIds: [], nodeRuns: {} },
    } as never;
    const rendered = await renderWorkspace();
    root = rendered.root;

    expect(rendered.container.textContent).toContain("正在切换题目");
    expect(rendered.container.textContent).not.toContain("记录选择并开启评审");
    expect(rendered.container.querySelector('[data-vui="research-current-task-inspector"]')).toBeNull();
    expect(harness.location.replaceParams).not.toHaveBeenCalled();
  });

  it("opens the inspector when the URL deep-links into a node panel", async () => {
    harness.location.panel = "node";
    harness.location.selectedNodeId = "source_finding";
    const rendered = await renderWorkspace();
    root = rendered.root;

    expect(rendered.container.querySelector('[data-vui="canvas-workbench-inspector"]')).not.toBeNull();
  });

  it("applies the launch patch directly when switching to a checkpoint-less question", async () => {
    harness.catalog.questions = [checkpointQuestion, restoreQuestion, freshQuestion];
    harness.runState.run = currentRun;
    const rendered = await renderWorkspace();
    root = rendered.root;

    const trigger = rendered.container.querySelector('[data-vui-select-trigger="true"]') as HTMLElement | null;
    expect(trigger).toBeTruthy();
    const options = await openSwitchSelect(trigger!);
    const fresh = Array.from(options).find((option) => option.textContent?.includes("SCI-005")) as HTMLElement | undefined;
    expect(fresh).toBeTruthy();
    await pickSwitchOption(fresh!);

    expect(mockedFocus).not.toHaveBeenCalled();
    expect(harness.location.replaceParams).toHaveBeenCalledWith({
      questionId: "SCI-005",
      runId: "",
      node: null,
      panel: "launch",
    });
  });

  it("restores a checkpoint question through the hypothesis-first focus node", async () => {
    harness.catalog.questions = [checkpointQuestion, restoreQuestion, freshQuestion];
    harness.runState.run = currentRun;
    const rendered = await renderWorkspace();
    root = rendered.root;

    const trigger = rendered.container.querySelector('[data-vui-select-trigger="true"]') as HTMLElement | null;
    expect(trigger).toBeTruthy();
    const options = await openSwitchSelect(trigger!);
    const restore = Array.from(options).find((option) => option.textContent?.includes("SCI-003")) as HTMLElement | undefined;
    expect(restore).toBeTruthy();
    await pickSwitchOption(restore!);

    expect(mockedFocus).toHaveBeenCalledWith("research-team", "SCI-003");
    await act(async () => {
      await Promise.resolve();
    });
    expect(harness.location.replaceParams).toHaveBeenCalledWith({
      questionId: "SCI-003",
      runId: "run-3",
      node: "hf_generation",
      panel: "node",
    });
  });
});
