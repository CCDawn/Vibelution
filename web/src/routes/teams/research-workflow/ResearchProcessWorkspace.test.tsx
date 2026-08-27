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
import { MemoryRouter, useLocation } from "react-router-dom";
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
    inspectorOpen: true,
    replaceParams: vi.fn(),
    openPanel: vi.fn(),
    selectNode: vi.fn(),
    responsiveInspectorOnOpenChange: undefined as ((open: boolean) => void) | undefined,
  },
  runState: {
    run: null as unknown,
    projection: null as unknown,
    snapshot: null as unknown,
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
    stateV2: null,
    v2ReadState: "route_unavailable",
    stateSource: "v1_legacy",
    chainState: null,
    meetings: [] as unknown[],
    collectionRequests: [] as unknown[],
    reviewRoundLinks: [] as unknown[],
    selection: null,
    loading: false,
    error: null as string | null,
    recoveryBusy: false,
    recoveryError: null as string | null,
    recoverCollection: vi.fn(),
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
vi.mock("./useHypothesisFirstChain", async () => ({
  ...(await vi.importActual<typeof import("./useHypothesisFirstChain")>("./useHypothesisFirstChain")),
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
      toolbarClassName?: string;
      layoutId?: string;
      responsive?: {
        enabled?: boolean;
        rail?: { label?: string };
        inspector?: {
          label?: string;
          open?: boolean;
          onOpenChange?: (open: boolean) => void;
        };
      };
    }) => {
      harness.responsiveInspectorOnOpenChange = props.responsive?.inspector?.onOpenChange;
      return (
        <div
          data-testid={props.shellTestId ?? "research-process-workspace-shell"}
          data-toolbar-class={props.toolbarClassName}
          data-layout-id={props.layoutId}
          data-responsive-enabled={String(props.responsive?.enabled)}
          data-responsive-rail={props.responsive?.rail?.label}
          data-responsive-inspector={props.responsive?.inspector?.label}
          data-responsive-inspector-open={String(props.responsive?.inspector?.open)}
        >
          {props.toolbar}
          <div data-vui="canvas-workbench-rail">{props.rail}</div>
          <div data-vui="canvas-workbench-canvas">{props.canvas}</div>
          <div data-vui="canvas-workbench-inspector">{props.inspector}</div>
        </div>
      );
    },
  };
});
vi.mock("./ResearchWorkflowCanvasPane", () => ({
  ResearchWorkflowCanvasPane: (props: {
    error?: string | null;
    currentTaskNodeId?: string | null;
    onSelectNode?: (nodeId: string | null) => void;
  }) => (
    <div
      role={props.error ? "alert" : undefined}
      data-current-task-node={props.currentTaskNodeId || undefined}
    >
      {props.error || "加载流程定义"}
      <button
        type="button"
        data-testid="research-workflow-canvas-node"
        onClick={() => props.onSelectNode?.("source_finding")}
      />
    </div>
  ),
}));
vi.mock("./ResearchProcessInspectorPane", () => ({
  ResearchProcessInspectorPane: (props: {
    scope: { panel: string };
    actions?: { replaceParams?: (patch: Record<string, string>) => void };
    archiveSummary?: unknown;
    allowLaunchPanel?: boolean;
    onRecoverCollection?: (requestId: string) => Promise<void>;
    collectionRecoveryBusy?: boolean;
    collectionRecoveryError?: string | null;
    discussionModel?: { status?: string; roomId?: string };
  }) => (
    <div
      data-testid="research-process-inspector-pane"
      data-panel={props.scope.panel}
      data-allow-launch-panel={props.allowLaunchPanel == null ? undefined : String(props.allowLaunchPanel)}
      data-has-archive-summary={String(Boolean(props.archiveSummary))}
      data-has-collection-recovery={String(Boolean(props.onRecoverCollection))}
      data-collection-recovery-busy={String(Boolean(props.collectionRecoveryBusy))}
      data-collection-recovery-error={props.collectionRecoveryError || undefined}
      data-discussion-status={props.discussionModel?.status || undefined}
      data-discussion-room={props.discussionModel?.roomId || undefined}
    >
      <button
        type="button"
        data-testid="formal-run-created"
        onClick={() => props.actions?.replaceParams?.({
          runId: "run-new",
          node: "hf_generation",
          questionId: "SCI-096",
          panel: "node",
        })}
      />
    </div>
  ),
}));

import { fetchHypothesisFirstFocusNode } from "./hypothesisFirstFocus";
import { ResearchProcessWorkspace } from "./ResearchProcessWorkspace";

const mockedFocus = vi.mocked(fetchHypothesisFirstFocusNode);

function RouteProbe() {
  const location = useLocation();
  return <output data-testid="route-probe">{location.pathname}{location.search}</output>;
}

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

/** Minimal canonical V2 state whose formal run owns the question (blocked). */
function blockedFormalStateV2(): Record<string, unknown> {
  return {
    schemaVersion: 2,
    currentPhase: "formal_runtime",
    awaitingHumanCount: 0,
    problems: [],
    allowedActions: [],
    generation: { generationMeetingId: null },
    review: { candidates: [], aggregate: { total: 0, completed: 0, pending: 0, failed: 0, blocked: 0 } },
    collection: { requests: [] },
    convergence: { roundBudget: 3, accepted: true },
    formalRuntime: {
      lifecycle: "running",
      outcome: "none",
      actionability: "blocked",
      problems: [],
      runId: "run-bcbca1400d71",
      runVersion: 3,
      runStatus: "blocked",
      completionKind: null,
      lineageDisposition: "current",
      isCurrentRevision: true,
      parentRunId: null,
      childRunIds: [],
      currentNodeIds: ["source_finding"],
    },
  };
}

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
          <RouteProbe />
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
    harness.location.inspectorOpen = true;
    harness.responsiveInspectorOnOpenChange = undefined;
    harness.runState.error = null;
    harness.runState.run = null;
    harness.runState.projection = null;
    harness.runState.snapshot = null;
    (harness.runState as { resyncRequired?: boolean }).resyncRequired = false;
    harness.runState.commandOffers = [];
    harness.commands.error = null;
    harness.commands.busy = false;
    harness.formalCommand.commandError = null;
    harness.chain.chainState = null;
    harness.chain.questionId = "";
    harness.chain.scopeMismatch = false;
    harness.chain.stateV2 = null;
    harness.chain.v2ReadState = "route_unavailable";
    harness.chain.stateSource = "v1_legacy";
    harness.chain.meetings = [];
    harness.chain.collectionRequests = [];
    harness.chain.reviewRoundLinks = [];
    harness.chain.selection = null;
    harness.chain.loading = false;
    harness.chain.error = null;
    harness.chain.recoveryBusy = false;
    harness.chain.recoveryError = null;
  });

  function configureCollectionRecoveryLaunch() {
    harness.location.panel = "launch";
    harness.location.questionId = "SCI-004";
    harness.chain.questionId = "SCI-004";
    harness.chain.selection = {
      questionId: "SCI-004",
      selectionId: "selection-1",
      selectedCandidateIds: ["candidate-1"],
    } as never;
    harness.chain.collectionRequests = [{
      requestId: "collection-request-1",
      questionId: "SCI-004",
      status: "failed",
      collectionRunId: "",
      handoffRef: "",
      createdAt: "2026-08-24T00:00:00Z",
    }] as never;
    harness.runState.projection = {
      definition: { nodes: [], edges: [], stages: [] },
      run: { teamId: "research-team", runtimeCurrentNodeIds: [], nodeRuns: {} },
    } as never;
  }

  it("shows the canvas loading state while no projection is available", async () => {
    const rendered = await renderWorkspace();
    root = rendered.root;

    expect(rendered.container.textContent).toContain("加载流程定义");
    expect(rendered.container.querySelector('[data-testid="research-process-workspace-shell"]')).not.toBeNull();
    expect(rendered.container.querySelector('[data-vui="research-current-task-inspector"]')).not.toBeNull();
    expect(rendered.container.querySelector('[data-vui-region="current-task-body"]')).not.toBeNull();
  });

  it("mounts the unified stage navigator beside the fixed canvas and inspector", async () => {
    const rendered = await renderWorkspace();
    root = rendered.root;

    const shell = rendered.container.querySelector('[data-testid="research-process-workspace-shell"]');
    expect(rendered.container.querySelector('[data-testid="research-workflow-stage-navigator"]')).not.toBeNull();
    expect(rendered.container.querySelector('[data-vui="canvas-workbench-rail"]')).not.toBeNull();
    expect(rendered.container.querySelector('[data-vui="canvas-workbench-canvas"]')).not.toBeNull();
    expect(rendered.container.querySelector('[data-vui="canvas-workbench-inspector"]')).not.toBeNull();
    expect(shell?.getAttribute("data-layout-id")).toBe("research-flow");
    expect(shell?.getAttribute("data-toolbar-class")).toContain("overflow-hidden");
    expect(shell?.getAttribute("data-responsive-enabled")).toBe("true");
    expect(shell?.getAttribute("data-responsive-rail")).toBe("研究阶段");
    expect(shell?.getAttribute("data-responsive-inspector")).toBe("当前任务");
  });

  it("binds node and team deep links to the responsive inspector open state", async () => {
    harness.location.panel = "node";
    harness.location.inspectorOpen = true;
    const nodeRendered = await renderWorkspace();
    root = nodeRendered.root;

    expect(nodeRendered.container.querySelector('[data-testid="research-process-workspace-shell"]')
      ?.getAttribute("data-responsive-inspector-open")).toBe("true");

    await act(async () => {
      harness.responsiveInspectorOnOpenChange?.(false);
    });
    expect(harness.location.replaceParams).toHaveBeenCalledWith({ inspector: "closed" });

    await act(async () => root?.unmount());
    root = null;
    document.body.innerHTML = "";
    vi.clearAllMocks();
    harness.location.replaceParams.mockClear();
    harness.location.panel = "team";
    harness.location.inspectorOpen = true;

    const teamRendered = await renderWorkspace();
    root = teamRendered.root;
    expect(teamRendered.container.querySelector('[data-testid="research-process-workspace-shell"]')
      ?.getAttribute("data-responsive-inspector-open")).toBe("true");
  });

  it("routes one canvas node click through the URL-owned selection callback", async () => {
    harness.location.panel = "team";
    harness.location.inspectorOpen = false;
    const rendered = await renderWorkspace();
    root = rendered.root;

    await act(async () => {
      (rendered.container.querySelector('[data-testid="research-workflow-canvas-node"]') as HTMLButtonElement)
        .click();
    });

    expect(harness.location.selectNode).toHaveBeenCalledTimes(1);
    expect(harness.location.selectNode).toHaveBeenCalledWith("source_finding");
  });

  it("places the read-only question archive in the wide center pane", async () => {
    harness.location.panel = "question";
    harness.location.questionId = "SCI-096";
    harness.location.selectedNodeId = "hf_review";
    harness.chain.questionId = "SCI-096";
    harness.chain.selection = {
      questionId: "SCI-096",
      selectionId: "selection-1",
      selectedCandidateIds: ["candidate-1"],
    } as never;
    const rendered = await renderWorkspace();
    root = rendered.root;

    const rail = rendered.container.querySelector('[data-vui="canvas-workbench-rail"]');
    const canvas = rendered.container.querySelector('[data-vui="canvas-workbench-canvas"]');
    const inspector = rendered.container.querySelector('[data-vui="canvas-workbench-inspector"]');
    expect(rail?.childElementCount).toBe(0);
    expect(canvas?.querySelector('[data-vui="research-question-archive-canvas"]')).not.toBeNull();
    expect(canvas?.querySelector('[data-testid="research-process-inspector-pane"]')?.getAttribute("data-panel")).toBe("question");
    expect(canvas?.querySelector('[data-testid="research-process-inspector-pane"]')?.getAttribute("data-has-archive-summary")).toBe("true");
    expect(inspector?.childElementCount).toBe(0);
    expect(rendered.container.querySelector('[data-vui="research-current-task-inspector"]')).toBeNull();
  });

  it("treats a stable review card as the current ledger meeting", async () => {
    harness.location.panel = "node";
    harness.location.questionId = "SCI-096";
    harness.location.selectedNodeId = "hf_review";
    harness.chain.questionId = "SCI-096";
    harness.chain.chainState = {
      questionId: "SCI-096",
      selectionId: "selection-1",
      candidateCount: 1,
      hypothesisConverged: false,
    } as never;
    harness.chain.selection = {
      questionId: "SCI-096",
      selectionId: "selection-1",
      selectedCandidateIds: ["candidate-1"],
    } as never;
    harness.chain.meetings = [{
      question: "SCI-096",
      meetingRoundId: "meeting-1",
      meetingType: "hypothesis_review",
      mode: "review",
      scopeHash: "scope-1",
      participants: ["reviewer"],
      status: "open",
      startedAt: "2026-08-24T00:00:00Z",
      roundIndex: 1,
    }] as never;
    harness.runState.projection = {
      definition: { nodes: [], edges: [], stages: [] },
      run: { teamId: "research-team", runtimeCurrentNodeIds: [], nodeRuns: {} },
    } as never;
    const rendered = await renderWorkspace();
    root = rendered.root;

    expect(rendered.container.querySelector('[data-vui="research-current-task-inspector"]')?.getAttribute("data-history-mode")).toBe("false");
    expect(rendered.container.querySelector('[data-current-task-node]')?.getAttribute("data-current-task-node")).toBe("hf_review");
  });

  it("uses the server-owned scoped discussion anchor for current-task navigation", async () => {
    harness.location.questionId = "SCI-096";
    harness.chain.questionId = "SCI-096";
    harness.chain.chainState = {
      questionId: "SCI-096",
      candidateCount: 0,
      hypothesisConverged: false,
    } as never;
    harness.runState.snapshot = {
      launchContext: {
        activeDiscussionAnchor: {
        scope: {
          version: 1,
          kind: "question_generation",
          teamId: "research-team",
          researchProjectId: "project-x",
          workflowRunId: "run-1",
          workflowNodeId: "hypothesis-generation",
          questionId: "SCI-096",
        },
        scopeHash: "scope-hash",
        roomId: "scoped-room-1",
        meetingRoundId: "meeting-1",
        questionId: "SCI-096",
        selectionId: "",
        candidateId: "",
        deepLink: "/chat?room=scoped-room-1",
        status: "ready",
        degradedReason: "",
        },
      },
    } as never;
    harness.runState.projection = {
      definition: { nodes: [], edges: [], stages: [] },
      run: { teamId: "research-team", runtimeCurrentNodeIds: [], nodeRuns: {} },
    } as never;

    const rendered = await renderWorkspace();
    root = rendered.root;
    const inspector = rendered.container.querySelector('[data-testid="research-process-inspector-pane"]');
    expect(inspector?.getAttribute("data-discussion-status")).toBe("ready");
    expect(inspector?.getAttribute("data-discussion-room")).toBe("scoped-room-1");
    await act(async () => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "k", ctrlKey: true, bubbles: true }));
    });

    const command = Array.from(document.body.querySelectorAll("button"))
      .find((button) => button.textContent?.includes("前往候选生成"));
    expect(command).toBeTruthy();
    await act(async () => command?.click());

    expect(rendered.container.querySelector('[data-testid="route-probe"]')?.textContent)
      .toBe(
        "/chat?room=scoped-room-1&returnTo=%2Fteams%3FteamId%3Dresearch-team%26researchView%3Dworkflow%26workflowId%3Dchallenge-cup-research%26questionId%3DSCI-096%26runId%3Drun-1%26node%3Dhypothesis-generation%26panel%3Dnode&returnLabel=%E8%BF%94%E5%9B%9E%E7%A7%91%E7%A0%94%E6%B5%81%E7%A8%8B",
      );
    expect(harness.location.replaceParams).not.toHaveBeenCalled();
  });

  it("keeps an explicit formal-run handoff ahead of a stale discussion anchor", async () => {
    harness.location.panel = "node";
    harness.location.questionId = "SCI-096";
    harness.location.selectedNodeId = "hf_generation";
    harness.chain.questionId = "SCI-096";
    harness.chain.chainState = {
      questionId: "SCI-096",
      candidateCount: 0,
      hypothesisConverged: false,
    } as never;
    harness.runState.snapshot = {
      launchContext: {
        activeDiscussionAnchor: {
          scope: {
            version: 1,
            kind: "question_generation",
            teamId: "research-team",
            researchProjectId: "project-x",
            workflowRunId: "run-old",
            workflowNodeId: "hypothesis-generation",
            questionId: "SCI-096",
          },
          scopeHash: "scope-hash",
          roomId: "stale-review-room",
          meetingRoundId: "meeting-old",
          questionId: "SCI-096",
          selectionId: "",
          candidateId: "",
          deepLink: "/chat?room=stale-review-room",
          status: "ready",
          degradedReason: "",
        },
      },
    } as never;
    harness.runState.projection = {
      definition: { nodes: [], edges: [], stages: [] },
      run: { teamId: "research-team", runtimeCurrentNodeIds: [], nodeRuns: {} },
    } as never;

    const rendered = await renderWorkspace();
    root = rendered.root;
    await act(async () => {
      (rendered.container.querySelector('[data-testid="formal-run-created"]') as HTMLButtonElement)
        .click();
    });

    expect(harness.location.replaceParams).toHaveBeenCalledWith({
      runId: "run-new",
      node: "hf_generation",
      questionId: "SCI-096",
      panel: "node",
    });
    expect(rendered.container.querySelector('[data-testid="route-probe"]')?.textContent)
      .not.toContain("/chat");
  });

  it("keeps an unresolved hypothesis gate current when convergence is already projected", async () => {
    harness.location.panel = "node";
    harness.location.runId = "run-created";
    harness.location.questionId = "SCI-096";
    harness.chain.questionId = "SCI-096";
    harness.chain.chainState = {
      questionId: "SCI-096",
      candidateCount: 0,
      hypothesisConverged: true,
    } as never;
    harness.chain.loading = true;
    harness.chain.meetings = [{
      question: "SCI-096",
      meetingRoundId: "candidate-generation-1",
      meetingType: "hypothesis_candidate_generation",
      mode: "review",
      scopeHash: "scope-1",
      participants: ["search", "extractor", "reviewer", "experiment"],
      status: "awaiting_approval",
      startedAt: "2026-08-24T00:00:00Z",
      roundIndex: 0,
    }] as never;
    harness.runState.run = {
      ...currentRun,
      runId: "run-created",
      questionId: "SCI-096",
      runtimeCurrentNodeIds: ["problem_understanding"],
    } as WorkflowRunRecord;
    harness.runState.projection = {
      definition: { nodes: [], edges: [], stages: [] },
      run: {
        runId: "run-created",
        teamId: "research-team",
        runVersion: 1,
        status: "running",
        runtimeCurrentNodeIds: ["problem_understanding"],
        nodeRuns: {},
      },
    } as never;
    harness.runState.snapshot = {
      run: {
        runId: "run-created",
        teamId: "research-team",
        workflowId: "challenge-cup-research",
        workflowVersionId: "v1",
        runVersion: 1,
        questionId: "SCI-096",
        status: "running",
      },
      currentTask: {
        key: "formal-problem-1",
        nodeId: "problem_understanding",
        stageId: "knowledge_collection",
        nodeRunId: "formal-problem-node-1",
        attempt: 1,
        actorKind: "agent",
        taskId: "formal-problem-task-1",
        state: "auto_running",
        kind: "agent_task",
        label: "问题理解",
        detail: "工作流正在处理当前任务",
        responsibility: "agent",
        automaticNextStep: null,
        blockedReason: null,
        recovery: { retryable: false, scope: "none", resumeFromNodeId: null },
      },
      commandOffers: [],
      progress: null,
      latestEventSequence: 1,
    } as never;

    const rendered = await renderWorkspace();
    root = rendered.root;

    const currentInspector = rendered.container.querySelector(
      '[data-vui="research-current-task-inspector"]',
    );
    expect(currentInspector?.textContent).toContain("确认候选假说清单");
    expect(currentInspector?.textContent).not.toContain("问题理解");
    expect(currentInspector?.getAttribute("data-history-mode")).toBe("false");
    expect(rendered.container.querySelector('[data-current-task-node]')?.getAttribute("data-current-task-node"))
      .toBe("hf_generation");
  });

  it("navigates from the stage rail through URL view state only", async () => {
    harness.runState.projection = {
      definition: {
        nodes: [{
          nodeId: "source_finding",
          stageId: "knowledge_collection",
          label: "资料发现",
          actorKind: "agent",
          description: "发现资料",
          primaryRoleKey: "researcher",
          collaboratorRoleKeys: [],
          producesArtifactKinds: [],
          acceptsGateKinds: [],
        }],
        edges: [],
        stages: [{
          stageId: "knowledge_collection",
          label: "知识搜集",
          nodeIds: ["source_finding"],
          index: 0,
        }],
      },
      run: {
        teamId: "research-team",
        status: "not_started",
        runtimeCurrentNodeIds: [],
        nodeRuns: {},
      },
    } as never;
    const rendered = await renderWorkspace();
    root = rendered.root;

    const nodeButton = Array.from(rendered.container.querySelectorAll("button"))
      .find((button) => button.textContent?.includes("资料发现"));
    expect(nodeButton).toBeTruthy();
    await act(async () => nodeButton?.click());

    expect(harness.location.replaceParams).toHaveBeenCalledTimes(1);
    expect(harness.location.replaceParams).toHaveBeenCalledWith({
      node: "source_finding",
      panel: "node",
    });
    expect(harness.location.selectNode).not.toHaveBeenCalled();
    expect(harness.commands.submitOffer).not.toHaveBeenCalled();
    expect(harness.commands.submitRun).not.toHaveBeenCalled();
    expect(rendered.container.querySelector('[data-vui="canvas-workbench-canvas"]')).not.toBeNull();
    expect(rendered.container.querySelector('[data-vui="canvas-workbench-inspector"]')).not.toBeNull();
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
    expect(rendered.container.textContent).not.toContain("选择题目开始研究");
    expect(rendered.container.querySelector('[data-vui="research-current-task-inspector"]')).not.toBeNull();
    expect(rendered.container.querySelector('[data-task-status="blocked"]')).not.toBeNull();
    expect(harness.location.replaceParams).not.toHaveBeenCalled();
  });

  it("suppresses phase inference while the canonical chain snapshot is still loading", async () => {
    harness.location.panel = "node";
    harness.location.questionId = "SCI-096";
    harness.chain.questionId = "SCI-096";
    harness.chain.stateV2 = null;
    harness.chain.v2ReadState = "pending";
    harness.chain.stateSource = "pending";
    harness.chain.loading = true;
    // Auxiliary reads can resolve before the V2 snapshot; that half-data must
    // never flash a guessed stage or expose a write command.
    harness.chain.meetings = [{
      question: "SCI-096",
      meetingRoundId: "meeting-1",
      meetingType: "hypothesis_review",
      mode: "review",
      scopeHash: "scope-1",
      participants: ["reviewer"],
      status: "open",
      startedAt: "2026-08-24T00:00:00Z",
      roundIndex: 1,
    }] as never;
    const rendered = await renderWorkspace();
    root = rendered.root;

    // Half-data must resolve into the existing blocked-task shape only; every
    // guessed phase/command label stays hidden while the snapshot is missing.
    expect(rendered.container.querySelector('[data-task-status="blocked"]')).not.toBeNull();
    expect(rendered.container.textContent).toContain("当前流程需要处理");
    expect(rendered.container.textContent).not.toContain("查看评审讨论");
    expect(rendered.container.textContent).not.toContain("整理本轮结论");
    expect(rendered.container.textContent).not.toContain("生成候选假说");
  });

  it("surfaces a v2_error read failure and withholds every legacy write action", async () => {
    harness.location.panel = "node";
    harness.location.questionId = "SCI-096";
    harness.chain.questionId = "SCI-096";
    harness.chain.stateV2 = null;
    harness.chain.v2ReadState = "v2_error";
    harness.chain.stateSource = "v2_error";
    harness.chain.error = "规范流程快照读取失败（500）";
    // A cached selection is exactly the half-data that used to unlock the
    // legacy record-selection command during a V2 outage.
    harness.chain.selection = {
      questionId: "SCI-096",
      selectionId: "selection-1",
      selectedCandidateIds: ["candidate-1"],
    } as never;
    const rendered = await renderWorkspace();
    root = rendered.root;

    expect(rendered.container.querySelector('[role="alert"]')?.textContent).toContain("规范流程快照读取失败（500）");
    // The outage resolves into the existing blocked-task shape with the error
    // surfaced as its blocker; no legacy write command may appear.
    expect(rendered.container.querySelector('[data-task-status="blocked"]')).not.toBeNull();
    expect(rendered.container.textContent).toContain("当前流程需要处理");
    expect(rendered.container.textContent).not.toContain("记录选择并开启评审");
    expect(rendered.container.textContent).not.toContain("生成候选假说");
  });

  it("submits the authoritative formal offer once from the fixed footer", async () => {
    const formalOffer = {
      command: "resolve_human_task",
      nodeId: "knowledge_handoff",
      available: true,
      label: "确认知识包交接",
      reasonCode: "ready",
      blockerIds: [],
      idempotencyKey: "offer:run-created:knowledge_handoff:resolve_human_task:v1",
      expectedRunVersion: 1,
      payload: { taskId: "human-1", decision: "accept" },
    };
    harness.location.panel = "launch";
    harness.location.runId = "run-created";
    harness.location.questionId = "SCI-004";
    harness.location.selectedNodeId = "knowledge_handoff";
    harness.chain.questionId = "SCI-004";
    harness.runState.run = {
      ...currentRun,
      runId: "run-created",
      questionId: "SCI-004",
      status: "waiting_human",
    } as WorkflowRunRecord;
    harness.runState.projection = {
      definition: { nodes: [], edges: [], stages: [] },
      run: {
        runId: "run-created",
        teamId: "research-team",
        runVersion: 1,
        status: "waiting_human",
        runtimeCurrentNodeIds: ["knowledge_handoff"],
        nodeRuns: {},
      },
    } as never;
    harness.runState.snapshot = {
      run: {
        runId: "run-created",
        teamId: "research-team",
        workflowId: "challenge-cup-research",
        workflowVersionId: "v1",
        runVersion: 1,
        questionId: "SCI-004",
        status: "waiting_human",
      },
      currentTask: {
        key: "human-1",
        nodeId: "knowledge_handoff",
        stageId: "knowledge_collection",
        nodeRunId: "node-run-1",
        attempt: 1,
        actorKind: "human",
        taskId: "human-1",
        state: "waiting_user",
        kind: "human_task",
        label: "确认知识包交接",
        detail: "确认后自动继续实验设计。",
        responsibility: "user",
        automaticNextStep: { kind: "auto_continue", label: "提交后自动继续" },
        blockedReason: null,
        recovery: { retryable: false, scope: "none", resumeFromNodeId: null },
      },
      commandOffers: [formalOffer],
      progress: null,
      latestEventSequence: 1,
    } as never;
    harness.runState.commandOffers = [formalOffer];
    harness.commands.submitOffer.mockResolvedValue(undefined);
    const rendered = await renderWorkspace();
    root = rendered.root;

    expect(rendered.container.querySelector('[data-task-status="waiting_user"]')).not.toBeNull();
    expect(rendered.container.querySelector('[data-testid="research-process-inspector-pane"]')?.getAttribute("data-allow-launch-panel"))
      .toBe("false");
    const footer = rendered.container.querySelector('[data-vui-region="current-task-action"]');
    const submit = Array.from(footer?.querySelectorAll("button") ?? []).find((button) => (
      button.textContent?.includes("确认知识包交接")
    ));
    expect(footer?.querySelectorAll("button")).toHaveLength(1);
    await act(async () => submit?.click());
    expect(harness.commands.submitOffer).toHaveBeenCalledTimes(1);
    expect(harness.commands.submitOffer).toHaveBeenCalledWith(formalOffer);
  });

  it("does not let a stale launch URL replace an active hypothesis task", async () => {
    harness.location.panel = "launch";
    harness.location.questionId = "SCI-004";
    harness.chain.questionId = "SCI-004";
    harness.chain.chainState = {
      questionId: "SCI-004",
      candidateCount: 0,
      hypothesisConverged: false,
    } as never;
    harness.runState.projection = {
      definition: { nodes: [], edges: [], stages: [] },
      run: { teamId: "research-team", runtimeCurrentNodeIds: [], nodeRuns: {} },
    } as never;

    const rendered = await renderWorkspace();
    root = rendered.root;

    const inspector = rendered.container.querySelector('[data-testid="research-process-inspector-pane"]');
    expect(inspector?.getAttribute("data-allow-launch-panel")).toBe("false");
    expect(rendered.container.textContent).toContain("生成候选假说");
    expect(rendered.container.textContent).not.toContain("开始实验");
    expect(harness.commands.submitRun).not.toHaveBeenCalled();
  });

  it("promotes the stateV2 formal run id into the URL for question-only deep links", async () => {
    harness.location.questionId = "SCI-003";
    harness.chain.questionId = "SCI-003";
    harness.chain.stateV2 = blockedFormalStateV2() as never;
    harness.runState.projection = {
      definition: { nodes: [], edges: [], stages: [] },
      run: { teamId: "research-team", runtimeCurrentNodeIds: [], nodeRuns: {} },
    } as never;

    const rendered = await renderWorkspace();
    root = rendered.root;

    expect(harness.location.replaceParams).toHaveBeenCalledWith({ runId: "run-bcbca1400d71" });
  });

  it("surfaces the blocked formal run retry action instead of an unknown hypothesis card", async () => {
    const startOffer = {
      command: "start_node",
      nodeId: "source_finding",
      available: false,
      label: "开始 资料寻找",
      reasonCode: "retry_owns_recovery",
      blockerIds: [],
      idempotencyKey: "offer:run-bcbca1400d71:source_finding:start_node:v3",
      expectedRunVersion: 3,
      payload: {},
    };
    harness.location.panel = "node";
    harness.location.runId = "run-bcbca1400d71";
    harness.location.questionId = "SCI-003";
    harness.location.selectedNodeId = "source_finding";
    harness.chain.questionId = "SCI-003";
    harness.chain.stateV2 = blockedFormalStateV2() as never;
    harness.runState.run = {
      ...currentRun,
      runId: "run-bcbca1400d71",
      questionId: "SCI-003",
      runVersion: 3,
      status: "blocked",
      runtimeCurrentNodeIds: ["source_finding"],
    } as WorkflowRunRecord;
    harness.runState.projection = {
      definition: { nodes: [], edges: [], stages: [] },
      run: {
        runId: "run-bcbca1400d71",
        teamId: "research-team",
        runVersion: 3,
        status: "blocked",
        runtimeCurrentNodeIds: ["source_finding"],
        nodeRuns: {},
      },
    } as never;
    harness.runState.snapshot = {
      run: {
        runId: "run-bcbca1400d71",
        teamId: "research-team",
        workflowId: "challenge-cup-research",
        workflowVersionId: "v1",
        runVersion: 3,
        questionId: "SCI-003",
        status: "blocked",
      },
      currentTask: {
        key: "node-run-9",
        nodeId: "source_finding",
        stageId: "knowledge_collection",
        nodeRunId: "node-run-9",
        attempt: 3,
        actorKind: "agent",
        taskId: null,
        state: "blocked_retryable",
        kind: "node",
        label: "资料寻找",
        detail: "节点执行被阻塞，可重试。",
        responsibility: "system",
        automaticNextStep: null,
        blockedReason: {
          code: "agent_dispatch_failed",
          detail: "调度失败",
          retryable: true,
          failureClass: "transient",
          message: "节点执行被阻塞",
          blockerIds: [],
        },
        recovery: {
          status: "retryable",
          retryable: true,
          code: "agent_dispatch_failed",
          detail: null,
          retryScope: "task",
          recoveryPoint: "source_finding",
          nextRetryAt: null,
          requiresOperator: false,
          afterSubmit: null,
        },
        authority: "formal_runtime",
      },
      commandOffers: [startOffer],
      retry: {
        available: true,
        command: "retry_node",
        nodeId: "source_finding",
        reasonCode: "retry_available",
        idempotencyKey: "offer:run-bcbca1400d71:source_finding:retry_node:a3:v3",
        expectedRunVersion: 3,
      },
      progress: {
        completed: 1,
        total: 17,
        percent: 5.88,
        completedNodes: 1,
        totalNodes: 17,
        blockedNodes: 1,
        currentStageId: "knowledge_collection",
        stages: [],
        completedNodeIds: ["problem_understanding"],
        blockedNodeIds: ["source_finding"],
        currentNodeId: "source_finding",
        status: "blocked",
      },
      latestEventSequence: 12,
    } as never;
    harness.runState.commandOffers = [startOffer];
    harness.commands.submitOffer.mockResolvedValue(undefined);
    const rendered = await renderWorkspace();
    root = rendered.root;

    expect(rendered.container.textContent).not.toContain("未知的假说先行卡片");
    expect(rendered.container.querySelector('[data-testid="research-process-inspector-pane"]')).not.toBeNull();
    const formalCard = rendered.container.querySelector('[data-task-status="recoverable_error"]');
    expect(formalCard).not.toBeNull();
    const footer = rendered.container.querySelector('[data-vui-region="current-task-action"]');
    const retryButton = Array.from(footer?.querySelectorAll("button") ?? []).find((button) => (
      button.textContent?.includes("重试")
    ));
    expect(retryButton).toBeTruthy();
    await act(async () => retryButton?.click());
    expect(harness.commands.submitOffer).toHaveBeenCalledTimes(1);
    const submitted = harness.commands.submitOffer.mock.calls[0][0] as {
      command: string;
      nodeId: string | null;
      idempotencyKey: string;
      expectedRunVersion: number;
    };
    expect(submitted.command).toBe("retry_node");
    expect(submitted.nodeId).toBe("source_finding");
    expect(submitted.idempotencyKey).toBe("offer:run-bcbca1400d71:source_finding:retry_node:a3:v3");
    expect(submitted.expectedRunVersion).toBe(3);
  });

  it("keeps collection recovery actionable in the fixed current-task footer", async () => {
    harness.location.panel = "node";
    harness.location.questionId = "SCI-004";
    harness.location.selectedNodeId = "source_finding";
    harness.chain.questionId = "SCI-004";
    harness.chain.selection = {
      questionId: "SCI-004",
      selectionId: "selection-1",
      selectedCandidateIds: ["candidate-1"],
    } as never;
    harness.chain.collectionRequests = [{
      requestId: "collection-request-1",
      questionId: "SCI-004",
      status: "failed",
      collectionRunId: "",
      handoffRef: "",
      createdAt: "2026-08-24T00:00:00Z",
    }] as never;
    harness.runState.projection = {
      definition: { nodes: [], edges: [], stages: [] },
      run: { teamId: "research-team", runtimeCurrentNodeIds: [], nodeRuns: {} },
    } as never;
    harness.chain.recoveryError = "worker unavailable";
    harness.chain.recoverCollection.mockResolvedValue(undefined);
    const rendered = await renderWorkspace();
    root = rendered.root;

    expect(rendered.container.querySelector('[data-task-status="recoverable_error"]')).not.toBeNull();
    const footer = rendered.container.querySelector('[data-vui-region="current-task-action"]');
    const retry = Array.from(footer?.querySelectorAll("button") ?? []).find((button) => (
      button.textContent?.includes("重试搜集")
    ));
    expect(retry).toBeTruthy();
    expect(Array.from(footer?.querySelectorAll("button") ?? []).filter((button) => (
      button.textContent?.includes("重试搜集")
    ))).toHaveLength(1);
    const inspector = rendered.container.querySelector('[data-testid="research-process-inspector-pane"]');
    expect(inspector?.getAttribute("data-has-collection-recovery")).toBe("false");
    expect(inspector?.getAttribute("data-collection-recovery-busy")).toBe("false");
    expect(inspector?.getAttribute("data-collection-recovery-error")).toBeNull();
    expect(footer?.querySelector('[role="alert"]')?.textContent).toContain("worker unavailable");
    await act(async () => retry?.click());
    expect(harness.chain.recoverCollection).toHaveBeenCalledTimes(1);
    expect(harness.chain.recoverCollection).toHaveBeenCalledWith("collection-request-1");
  });

  it("hides collection recovery actions while the current-task scope is not ready", async () => {
    const cases: Array<{
      label: string;
      prepare: () => void;
      reset: () => void;
    }> = [
      {
        label: "loading",
        prepare: () => {
          harness.chain.loading = true;
        },
        reset: () => {
          harness.chain.loading = false;
        },
      },
      {
        label: "resync",
        prepare: () => {
          (harness.runState as { resyncRequired?: boolean }).resyncRequired = true;
        },
        reset: () => {
          (harness.runState as { resyncRequired?: boolean }).resyncRequired = false;
        },
      },
      {
        label: "error",
        prepare: () => {
          harness.chain.error = "worker unavailable";
        },
        reset: () => {
          harness.chain.error = null;
        },
      },
    ];

    for (const testCase of cases) {
      configureCollectionRecoveryLaunch();
      testCase.prepare();
      const rendered = await renderWorkspace();
      root = rendered.root;

      const footer = rendered.container.querySelector('[data-vui-region="current-task-action"]');
      expect(footer?.querySelectorAll("button"), testCase.label).toHaveLength(0);

      await act(async () => root?.unmount());
      root = null;
      document.body.innerHTML = "";
      testCase.reset();
    }
  });

  it("opens the inspector when the URL deep-links into a node panel", async () => {
    harness.location.panel = "node";
    harness.location.selectedNodeId = "source_finding";
    harness.location.inspectorOpen = true;
    const rendered = await renderWorkspace();
    root = rendered.root;

    expect(rendered.container.querySelector('[data-vui="canvas-workbench-inspector"]')).not.toBeNull();
    expect(rendered.container.querySelector('[data-testid="research-process-workspace-shell"]')
      ?.getAttribute("data-responsive-inspector-open")).toBe("true");
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
