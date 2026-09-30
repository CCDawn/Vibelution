/** @vitest-environment happy-dom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { EvolutionWorkspaceSnapshot, SupervisedWorktreeRun } from "../api/types";
import { queryKeys } from "../api/queryKeys";
import { useShellStore } from "../store/shellStore";
import { EvolutionRoute } from "./EvolutionRoute";

const apiMocks = vi.hoisted(() => ({
  fetchPublicConfig: vi.fn(),
  fetchEvolutionWorkspaceSnapshot: vi.fn(),
  fetchEvolutionWorkbench: vi.fn(),
  fetchSelfEvolutionWorkspaceSnapshot: vi.fn(),
  fetchSelfObservationRun: vi.fn(),
  fetchEvolutionWorktreeRun: vi.fn(),
}));

const mutationMocks = vi.hoisted(() => {
  const mutation = () => ({ mutate: vi.fn(), isPending: false, error: null });
  return {
    run: {
      startWorktreeRunMutation: mutation(),
      startSelfObservationMutation: mutation(),
      selfObservationActionMutation: mutation(),
      startSelfAutonomousLoopMutation: mutation(),
      selfAutonomousLoopActionMutation: mutation(),
      deleteSelfHistoryMutation: mutation(),
      actionMutation: mutation(),
      approvalWorktreeActionMutation: mutation(),
    },
    proposal: {
      updateProposalMutation: mutation(),
      deleteProposalMutation: mutation(),
      bulkDeleteMutation: mutation(),
      deleteRunRecordMutation: mutation(),
      bulkDeleteRunRecordsMutation: mutation(),
    },
  };
});

vi.mock("../api/config", () => ({ fetchPublicConfig: apiMocks.fetchPublicConfig }));
vi.mock("../api/evolution", () => ({
  EVOLUTION_WORKBENCH_POLL_INTERVAL_MS: 60_000,
  fetchEvolutionWorkspaceSnapshot: apiMocks.fetchEvolutionWorkspaceSnapshot,
  fetchEvolutionWorkbench: apiMocks.fetchEvolutionWorkbench,
  fetchSelfEvolutionWorkspaceSnapshot: apiMocks.fetchSelfEvolutionWorkspaceSnapshot,
  fetchSelfObservationRun: apiMocks.fetchSelfObservationRun,
  fetchEvolutionWorktreeRun: apiMocks.fetchEvolutionWorktreeRun,
}));
vi.mock("../app/pollingPolicy", () => ({
  resolvePollingInterval: () => false,
  usePageVisibility: () => true,
}));
vi.mock("../i18n/useAppI18n", () => ({
  useAppI18n: () => ({
    lang: "zh",
    t: (key: string) => ({
      supervisedEvolutionMode: "监督进化",
      selfEvolutionMode: "自进化",
      loading: "加载中",
      startSupervisedRun: "开始监督运行",
    }[key] ?? key),
    statusLabel: (status: string) => String(status ?? ""),
    intakeModeLabel: (value: string) => value,
    viewLabel: (value: string) => value,
    decisionLabel: (value: string) => value,
    riskLabel: (value: string) => value,
    workbenchSourceLabel: (value: string) => value,
    proposalActionLabel: (value: string) => value,
    sourceKindLabel: (value: string) => value,
  }),
}));
vi.mock("./evolution/useEvolutionRunMutations", () => ({
  useEvolutionRunMutations: () => mutationMocks.run,
}));
vi.mock("./evolution/useEvolutionProposalMutations", () => ({
  useEvolutionProposalMutations: () => mutationMocks.proposal,
}));

vi.mock("../components/vui", async () => {
  const ReactModule = await import("react");
  const passthrough = ({ children }: { children?: React.ReactNode }) =>
    ReactModule.createElement("div", null, children);
  const VButton = ({
    children,
    onPress,
    isDisabled,
    disabledReason,
  }: {
    children?: React.ReactNode;
    onPress?: () => void;
    isDisabled?: boolean;
    disabledReason?: string;
  }) => ReactModule.createElement("button", {
    type: "button",
    disabled: isDisabled,
    title: disabledReason,
    onClick: onPress,
  }, children);
  const VDialog = ({
    open,
    title,
    children,
    footer,
  }: {
    open?: boolean;
    title?: React.ReactNode;
    children?: React.ReactNode;
    footer?: React.ReactNode;
  }) => open
    ? ReactModule.createElement("section", { "data-testid": "route-dialog" },
      title ? ReactModule.createElement("h2", null, title) : null,
      children,
      footer)
    : null;
  const VTrackWorkbenchPage = ReactModule.forwardRef<HTMLDivElement, Record<string, any>>(
    ({ children, header, ...props }, ref) => ReactModule.createElement(
      "main",
      { ...props, ref, "data-testid": "workbench-page" },
      header?.actions,
      children,
    ),
  );
  const VTabs = ({ items = [], onValueChange }: { items?: Array<{ id: string; label: React.ReactNode }>; onValueChange?: (id: string) => void }) =>
    ReactModule.createElement("div", null, ...items.map((item) => ReactModule.createElement(
      "button",
      { key: item.id, type: "button", onClick: () => onValueChange?.(item.id) },
      item.label,
    )));
  return {
    VButton,
    VDialog,
    VMetricStrip: passthrough,
    VSection: passthrough,
    VSurface: passthrough,
    VTabs,
    VTooltip: passthrough,
    VTrackWorkbenchPage,
  };
});

vi.mock("./SupervisedConversationWorkspace", async () => {
  const ReactModule = await import("react");
  const navigationButtons = (groups: any[], onTrackChange: (track: string) => void) => [
    ReactModule.createElement("button", {
      key: "switch-self",
      type: "button",
      "data-testid": "switch-self",
      onClick: () => onTrackChange("self"),
    }, "自进化"),
    ReactModule.createElement("button", {
      key: "switch-supervised",
      type: "button",
      "data-testid": "switch-supervised",
      onClick: () => onTrackChange("supervised"),
    }, "监督进化"),
    ...groups.flatMap((group) => group.runs.map((run: any) => ReactModule.createElement(
      "button",
      {
        key: run.id,
        type: "button",
        "data-testid": "workspace-run",
        "data-run-key": run.id,
        "aria-pressed": run.selected,
        onClick: run.onSelect,
      },
      run.title,
    ))),
  ];

  return {
    SupervisedConversationWorkspace: (props: any) => ReactModule.createElement(
      "section",
      { "data-testid": "supervised-workspace", "data-active-track": props.activeTrack },
      ...navigationButtons(props.runGroups ?? [], props.onTrackChange),
      ReactModule.createElement("output", { "data-testid": "workspace-title" }, props.title),
      ReactModule.createElement("output", { "data-testid": "selected-step" }, props.selectedStepId),
      ReactModule.createElement("div", { "data-testid": "conversation-slot" }, props.conversation),
      ReactModule.createElement("div", { "data-testid": "footer-slot" }, props.footer),
      ReactModule.createElement("div", { hidden: true, "data-testid": "progress-evidence" },
        props.evidenceTabs?.find((tab: any) => tab.id === "progress")?.content),
      ...props.phases.map((phase: any) => ReactModule.createElement(
        "button",
        {
          key: phase.id,
          type: "button",
          "data-testid": "select-phase",
          "data-phase-id": phase.id,
          onClick: () => props.onSelectStep(phase.id),
        },
        phase.label,
      )),
    ),
  };
});

vi.mock("./SelfEvolutionConversationWorkspace", async () => {
  const ReactModule = await import("react");
  return {
    SelfEvolutionConversationWorkspace: (props: any) => ReactModule.createElement(
      "section",
      { "data-testid": "self-workspace", "data-active-track": props.workspaceNavigation.activeTrack },
      ReactModule.createElement("button", {
        type: "button",
        "data-testid": "switch-self-to-supervised",
        onClick: () => props.workspaceNavigation.onTrackChange("supervised"),
      }, "监督进化"),
      ...props.workspaceNavigation.runGroups.flatMap((group: any) => group.runs.map((run: any) => ReactModule.createElement(
        "button",
        {
          key: run.id,
          type: "button",
          "data-testid": "self-workspace-run",
          "data-run-key": run.id,
          onClick: run.onSelect,
        },
        run.title,
      ))),
      ReactModule.createElement("output", { "data-testid": "self-selected-run" },
        props.autonomousRun?.runId
        || props.observationRun?.runId
        || props.worktreeRun?.runId
        || ""),
    ),
  };
});

vi.mock("./SupervisedAgentConversationPanel", async () => {
  const ReactModule = await import("react");
  return {
    SupervisedAgentConversationPanel: (props: any) => {
      const member = props.members?.find((item: any) => item.role === props.selectedRole);
      return ReactModule.createElement("output", {
        "data-testid": "conversation-session",
        "data-live": String(Boolean(props.isLive)),
      }, member?.conversationSession?.conversationSessionId || "no-session");
    },
  };
});

vi.mock("./SupervisedApprovalDecisionPanel", async () => {
  const ReactModule = await import("react");
  return {
    SupervisedApprovalDecisionPanel: (props: any) => ReactModule.createElement("output", {
      "data-testid": "review-run",
      "data-review-run-id": props.run?.runId || "none",
    }, props.run?.runId || "none"),
  };
});

vi.mock("./EvolutionActiveRunMonitorPanel", async () => {
  const ReactModule = await import("react");
  return {
    EvolutionActiveRunMonitorPanel: (props: any) => {
      const termination = props.run?.termination;
      return ReactModule.createElement("div", { "data-testid": "active-monitor" },
        ReactModule.createElement("output", { "data-testid": "monitor-run-id" }, props.header?.title || ""),
        termination ? ReactModule.createElement("button", {
          type: "button",
          "data-testid": "active-stop",
          disabled: termination.disabled,
          onClick: termination.onClick,
        }, "停止活动运行") : null);
    },
  };
});

vi.mock("./EvolutionSupervisedLiveSetupPanel", () => ({ EvolutionSupervisedLiveSetupPanel: () => null }));
vi.mock("./EvolutionSupervisedWorkflowMembersPanel", () => ({ EvolutionSupervisedWorkflowMembersPanel: () => null }));
vi.mock("./EvolutionSupervisedConversationEvidencePanel", () => ({ EvolutionSupervisedConversationEvidencePanel: () => null }));
vi.mock("./EvolutionSupervisedLiveIoPanel", () => ({ EvolutionSupervisedLiveIoPanel: () => null }));
vi.mock("./evolution/EvolutionBaselinePromotionStrip", () => ({ EvolutionBaselinePromotionStrip: () => null }));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const currentRunId = "swte-active-current";
const historyRunId = "swte-history-previous";

function workflowStep(
  id: string,
  role: string | null,
  conversationSessionId: string,
  current = false,
) {
  return {
    id,
    label: id,
    ownerKind: role ? "agent" : "human",
    role,
    status: current ? "running" : "done",
    current,
    summary: `summary-${id}`,
    livePreview: `preview-${id}`,
    metrics: {},
    conversationSessionId,
    chatRoute: "",
  };
}

function worktreeRun(
  runId: string,
  status: string,
  datasetName: string,
  overrides: Partial<SupervisedWorktreeRun> = {},
): SupervisedWorktreeRun {
  return {
    runId,
    runKind: "supervised_worktree_evolution_run",
    status,
    phase: status === "running" ? "baseline" : "complete",
    runtimeStatus: status,
    outcome: status === "running" ? "" : "completed",
    mode: "supervised",
    executionMode: "worktree",
    sourceKind: "dataset",
    datasetName,
    datasetLimit: 20,
    bundleName: "",
    keepWorktree: true,
    startedAt: "2026-09-30T10:00:00Z",
    updatedAt: "2026-09-30T10:01:00Z",
    finishedAt: status === "running" ? "" : "2026-09-30T10:01:00Z",
    latestMessage: `${datasetName} update`,
    costEstimate: {
      caseCount: 20,
      evaluationCalls: 20,
      selfEditCalls: 1,
      modelCalls: 21,
      estimatedInputTokens: 100,
      estimatedOutputTokens: 100,
      estimatedTotalTokens: 200,
      note: "fixture",
    },
    decision: {},
    mergeAnalysis: {},
    actionStates: {},
    agentBindings: {
      baseline: { agentId: "agent-baseline", roleLabel: "基线" },
      baseline_rerun: { agentId: "agent-rerun", roleLabel: "复跑" },
      judge: { agentId: "agent-judge", roleLabel: "评审" },
    },
    workflowSteps: [
      workflowStep("baseline_eval", "baseline", `${runId}-baseline-session`, status === "running"),
      workflowStep("baseline_judge", "judge", `${runId}-judge-session`),
      workflowStep("improve", "baseline", `${runId}-improve-session`),
      workflowStep("rerun_eval", "baseline_rerun", `${runId}-rerun-session`),
      workflowStep("rerun_judge", "judge", `${runId}-rerun-judge-session`),
      workflowStep("approval", null, ""),
    ],
    ...overrides,
  } as SupervisedWorktreeRun;
}

const activeWorktree = worktreeRun(currentRunId, "running", "当前评估集", {
  actionStates: { terminate: { enabled: true, reason: "" } },
});
const activeWorktreeSummary = { ...activeWorktree, detailLevel: "summary" as const };
const historicalSummary = {
  ...worktreeRun(historyRunId, "done", "历史评估集"),
  detailLevel: "summary" as const,
  workflowSteps: undefined,
};
const historicalDetail = worktreeRun(historyRunId, "done", "历史评估集", {
  actionStates: { approveReview: { enabled: true, reason: "" } },
});

const initialWorkspaceSnapshot = (): EvolutionWorkspaceSnapshot => ({
  overview: {
    currentStatus: null,
    recentRuns: [],
    workbench: { source: "dataset", datasetName: "当前评估集", bundleName: "", datasetLimit: 20 },
    intakeMode: "standard",
  } as never,
  runs: [],
  library: { items: [], pending: [] },
  workbench: {
    defaultBundleName: "fixture-bundle",
    savedState: { source: "dataset", datasetName: "当前评估集", datasetLimit: 20 } as never,
    bundles: [],
    datasets: [],
    datasetCatalog: [],
    activeRun: null,
  },
  activeRun: null,
  latestRun: null,
  latestClosedLoopRecord: null,
  currentAgentBindings: {},
  worktreeActiveRun: activeWorktree,
  worktreeRuns: [activeWorktreeSummary, historicalSummary],
  selfOverview: {} as never,
  selfWorktreeActiveRun: null,
  selfWorktreeRuns: [],
  selfObservationActiveRun: null,
  selfAutonomousActiveRun: null,
  selfAutonomousLatestRun: {
    runId: "self-latest-run",
    status: "completed",
    request: { goal: "最近的自主目标", maxIterations: 1 },
  } as never,
  selfTransactions: [],
});

function makeWorkbench() {
  return {
    defaultBundleName: "fixture-bundle",
    savedState: { source: "dataset", datasetName: "当前评估集", datasetLimit: 20 },
    bundles: [{ name: "fixture-bundle", declaredName: "fixture-bundle", path: "", caseCount: 20, benchmark: "" }],
    datasets: [{
      name: "当前评估集",
      effective: true,
      selectable: true,
      visibility: "visible",
      usabilityStatus: "usable",
      caseCount: 20,
    }],
    datasetCatalog: [],
    activeRun: null,
  };
}

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="route-location">{location.pathname}</output>;
}

let host: HTMLDivElement | null = null;
let root: Root | null = null;
let queryClient: QueryClient;
let currentSnapshot: EvolutionWorkspaceSnapshot;

function elementByTestId(id: string): HTMLElement {
  const item = host?.querySelector<HTMLElement>(`[data-testid="${id}"]`);
  if (!item) throw new Error(`element not found: ${id}`);
  return item;
}

async function click(element: HTMLElement) {
  await act(async () => {
    element.click();
    await Promise.resolve();
    await new Promise<void>((resolve) => window.setTimeout(resolve, 0));
  });
}

async function renderRoute() {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => {
    root?.render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/supervised-evolution"]}>
          <EvolutionRoute forcedTrack="supervised" forcedView="live" />
          <LocationProbe />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await Promise.resolve();
  });
}

async function waitFor(test: () => void) {
  await vi.waitFor(test, { timeout: 2_000 });
}

describe("EvolutionRoute unified workspace run selection", () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    useShellStore.setState({ evolutionTrack: "supervised", evolutionView: "live" });
    currentSnapshot = initialWorkspaceSnapshot();
    apiMocks.fetchPublicConfig.mockReset().mockResolvedValue({
      language: "zh",
      intakeMode: "standard",
      modeAvailability: { supervised_evolution: true, self_evolution: true },
      modelLabels: {},
    });
    apiMocks.fetchEvolutionWorkspaceSnapshot.mockReset().mockImplementation(async () => currentSnapshot);
    apiMocks.fetchEvolutionWorkbench.mockReset().mockResolvedValue(makeWorkbench());
    apiMocks.fetchSelfEvolutionWorkspaceSnapshot.mockReset().mockResolvedValue({
      overview: {},
      transactions: [],
      worktreeActiveRun: null,
      observationActiveRun: null,
      autonomousActiveRun: null,
      autonomousLatestRun: {
        runId: "self-latest-run",
        status: "completed",
        request: { goal: "最近的自主目标", maxIterations: 1 },
      },
    });
    apiMocks.fetchSelfObservationRun.mockReset().mockResolvedValue(null);
    apiMocks.fetchEvolutionWorktreeRun.mockReset().mockImplementation(async (runId: string) => {
      if (runId === historyRunId) return historicalDetail;
      return activeWorktree;
    });
    for (const mutation of Object.values(mutationMocks.run)) mutation.mutate.mockReset();
    for (const mutation of Object.values(mutationMocks.proposal)) mutation.mutate.mockReset();
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0, refetchOnWindowFocus: false } },
    });
  });

  afterEach(async () => {
    if (root) {
      await act(async () => { root?.unmount(); });
    }
    queryClient.clear();
    host?.remove();
    root = null;
    host = null;
  });

  it("lets a forced supervised route switch to self evolution without navigating away", async () => {
    await renderRoute();
    await waitFor(() => expect(elementByTestId("workbench-page").getAttribute("data-evolution-track")).toBe("supervised"));
    expect(elementByTestId("route-location").textContent).toBe("/supervised-evolution");

    await click(elementByTestId("switch-self"));

    await waitFor(() => expect(elementByTestId("self-workspace").getAttribute("data-active-track")).toBe("self"));
    expect(elementByTestId("workbench-page").getAttribute("data-evolution-track")).toBe("self");
    expect(elementByTestId("route-location").textContent).toBe("/supervised-evolution");
    expect(elementByTestId("self-selected-run").textContent).toBe("self-latest-run");
  });

  it("loads a selected historical worktree for conversation and review while stop targets the live run", async () => {
    await renderRoute();
    await waitFor(() => expect(elementByTestId("active-stop").hasAttribute("disabled")).toBe(false));

    await click(elementByTestId("active-stop"));
    expect(mutationMocks.run.approvalWorktreeActionMutation.mutate)
      .toHaveBeenCalledWith({ runId: currentRunId, action: "terminate" });

    await click(Array.from(host?.querySelectorAll<HTMLButtonElement>('[data-testid="workspace-run"]') ?? [])
      .find((button) => button.dataset.runKey === `supervised:worktree:${historyRunId}`)!);

    await waitFor(() => expect(elementByTestId("review-run").getAttribute("data-review-run-id")).toBe(historyRunId));
    expect(elementByTestId("conversation-session").textContent).toContain(historyRunId);
    expect(apiMocks.fetchEvolutionWorktreeRun).toHaveBeenCalledWith(historyRunId);
    expect(mutationMocks.run.approvalWorktreeActionMutation.mutate)
      .toHaveBeenCalledTimes(1);
  });

  it("remembers the selected run and phase across track switches and snapshot refreshes", async () => {
    await renderRoute();
    await waitFor(() => expect(elementByTestId("workspace-title").textContent).toBe("当前评估集"));

    await click(Array.from(host?.querySelectorAll<HTMLButtonElement>('[data-testid="workspace-run"]') ?? [])
      .find((button) => button.dataset.runKey === `supervised:worktree:${historyRunId}`)!);
    await waitFor(() => expect(elementByTestId("review-run").getAttribute("data-review-run-id")).toBe(historyRunId));
    await click(Array.from(host?.querySelectorAll<HTMLButtonElement>('[data-testid="select-phase"]') ?? [])
      .find((button) => button.dataset.phaseId === "rerun_eval")!);
    expect(elementByTestId("selected-step").textContent).toBe("rerun_eval");
    expect(elementByTestId("conversation-session").textContent).toBe(`${historyRunId}-rerun-session`);

    const newlyArrivedRun = {
      ...worktreeRun("swte-newly-arrived", "done", "刚完成的新运行"),
      detailLevel: "summary" as const,
      workflowSteps: undefined,
    };
    currentSnapshot = {
      ...currentSnapshot,
      worktreeRuns: [newlyArrivedRun, activeWorktreeSummary, historicalSummary],
    };
    await act(async () => {
      queryClient.setQueryData(queryKeys.evolutionWorkspaceSnapshot(), currentSnapshot);
      await Promise.resolve();
    });
    expect(elementByTestId("workspace-title").textContent).toBe("历史评估集");
    expect(elementByTestId("selected-step").textContent).toBe("rerun_eval");

    await click(elementByTestId("switch-self"));
    await waitFor(() => expect(elementByTestId("self-workspace")).not.toBeNull());
    await click(elementByTestId("switch-self-to-supervised"));

    await waitFor(() => expect(elementByTestId("workspace-title").textContent).toBe("历史评估集"));
    expect(elementByTestId("selected-step").textContent).toBe("rerun_eval");
    expect(elementByTestId("conversation-session").textContent).toBe(`${historyRunId}-rerun-session`);
  });
});
