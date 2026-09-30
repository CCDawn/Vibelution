import { describe, expect, it } from "vitest";

import type {
  EvolutionActiveRun,
  SelfEvolutionAutonomousLoopRun,
  SelfEvolutionWorkspaceSnapshot,
  SelfObservationRun,
  SupervisedWorktreeRun,
} from "../api/types";
import {
  buildUnifiedEvolutionRuns,
  selectUnifiedEvolutionRun,
} from "./unifiedEvolutionRuns";

function worktreeRun(
  runId: string,
  overrides: Partial<SupervisedWorktreeRun> = {},
): SupervisedWorktreeRun {
  return {
    runId,
    runKind: "supervised_worktree_evolution_run",
    status: "done",
    phase: "complete",
    runtimeStatus: "done",
    outcome: "completed",
    mode: "supervised",
    executionMode: "worktree",
    sourceKind: "dataset",
    datasetName: "",
    datasetLimit: null,
    bundleName: "",
    keepWorktree: true,
    startedAt: "",
    updatedAt: "",
    finishedAt: "",
    latestMessage: "",
    costEstimate: {
      caseCount: 0,
      evaluationCalls: 0,
      selfEditCalls: 0,
      modelCalls: 0,
      estimatedInputTokens: 0,
      estimatedOutputTokens: 0,
      estimatedTotalTokens: 0,
      note: "",
    },
    decision: {},
    mergeAnalysis: {},
    actionStates: {},
    ...overrides,
  } as SupervisedWorktreeRun;
}

function activeRun(
  runId: string,
  overrides: Partial<EvolutionActiveRun> = {},
): EvolutionActiveRun {
  return {
    runId,
    status: "done",
    sourceKind: "dataset",
    datasetName: "",
    bundleName: "",
    ...overrides,
  } as EvolutionActiveRun;
}

function autonomousRun(
  runId: string,
  overrides: Partial<SelfEvolutionAutonomousLoopRun> = {},
): SelfEvolutionAutonomousLoopRun {
  return {
    runId,
    status: "completed",
    request: { goal: "", maxIterations: 1 },
    ...overrides,
  } as SelfEvolutionAutonomousLoopRun;
}

function observationRun(
  runId: string,
  overrides: Partial<SelfObservationRun> = {},
): SelfObservationRun {
  return {
    runId,
    status: "completed",
    goal: "",
    ...overrides,
  } as SelfObservationRun;
}

function selfSnapshot(
  overrides: Partial<SelfEvolutionWorkspaceSnapshot> = {},
): SelfEvolutionWorkspaceSnapshot {
  return {
    overview: {} as SelfEvolutionWorkspaceSnapshot["overview"],
    transactions: [],
    worktreeActiveRun: null,
    observationActiveRun: null,
    autonomousActiveRun: null,
    autonomousLatestRun: null,
    ...overrides,
  };
}

describe("buildUnifiedEvolutionRuns", () => {
  it("deduplicates active and latest snapshots while keeping the active payload", () => {
    const listedWorktree = worktreeRun("worktree-1", {
      detailLevel: "summary",
      status: "done",
      datasetName: "旧摘要标题",
    });
    const activeWorktree = worktreeRun("worktree-1", {
      status: "running",
      datasetName: "活动详情标题",
      workflowSteps: [],
    });
    const activeSession = activeRun("session-1", {
      status: "running",
      datasetName: "活动评估集",
    });
    const latestSession = activeRun("session-1", {
      status: "done",
      datasetName: "旧评估集",
    });

    const rows = buildUnifiedEvolutionRuns({
      supervisedWorktreeRuns: [listedWorktree],
      supervisedActiveWorktreeRun: activeWorktree,
      supervisedActiveRun: activeSession,
      supervisedLatestRun: latestSession,
    });

    const worktreeRows = rows.filter((row) => row.key === "supervised:worktree:worktree-1");
    const sessionRows = rows.filter((row) => row.key === "supervised:session:session-1");
    expect(worktreeRows).toHaveLength(1);
    expect(worktreeRows[0].worktreeRun).toBe(activeWorktree);
    expect(worktreeRows[0].title).toBe("活动详情标题");
    expect(sessionRows).toHaveLength(1);
    expect(sessionRows[0].activeRun).toBe(activeSession);
    expect(sessionRows[0].title).toBe("活动评估集");
  });

  it("classifies self-origin worktrees under self and keeps cross-track keys distinct", () => {
    const supervised = worktreeRun("shared-id", { datasetName: "监督评测" });
    const self = worktreeRun("shared-id", {
      selfEvolutionOrigin: { sourceTrack: "self_evolution", goal: "修复重复重试" },
      datasetName: "内部评测",
    });

    const rows = buildUnifiedEvolutionRuns({
      supervisedWorktreeRuns: [supervised, self],
    });

    expect(rows.map((row) => row.key)).toEqual([
      "supervised:worktree:shared-id",
      "self:worktree:shared-id",
    ]);
    expect(rows.map((row) => row.track)).toEqual(["supervised", "self"]);
    expect(rows[1].title).toBe("修复重复重试");
  });

  it("uses actual self goals and falls back to the run id when a title is empty", () => {
    const rows = buildUnifiedEvolutionRuns({
      supervisedWorktreeRuns: [worktreeRun("empty-supervised-title")],
      selfSnapshot: selfSnapshot({
        autonomousLatestRun: autonomousRun("autonomous-1", {
          request: { goal: "减少重复重试", maxIterations: 2 },
        }),
      }),
      observationRun: observationRun("observation-1", { goal: "观察当前页面" }),
    });

    expect(rows.find((row) => row.runId === "empty-supervised-title")?.title)
      .toBe("empty-supervised-title");
    expect(rows.find((row) => row.kind === "autonomous")?.title).toBe("减少重复重试");
    expect(rows.find((row) => row.kind === "observation")?.title).toBe("观察当前页面");
  });

  it("does not turn self-evolution transactions into run rows", () => {
    const rows = buildUnifiedEvolutionRuns({
      supervisedWorktreeRuns: [],
      selfSnapshot: selfSnapshot({
        transactions: [{ txnId: "txn-1", status: "completed" } as never],
      }),
    });

    expect(rows).toEqual([]);
  });
});

describe("selectUnifiedEvolutionRun", () => {
  const rows = buildUnifiedEvolutionRuns({
    supervisedWorktreeRuns: [
      worktreeRun("history", { status: "done", datasetName: "历史任务" }),
      worktreeRun("active", { status: "running", datasetName: "当前任务" }),
    ],
  });

  it("keeps an explicit historical selection when an active run exists", () => {
    expect(selectUnifiedEvolutionRun(rows, "supervised", "supervised:worktree:history")?.runId)
      .toBe("history");
  });

  it("does not fall back to the active run when an explicit key is missing", () => {
    expect(selectUnifiedEvolutionRun(rows, "supervised", "supervised:worktree:missing"))
      .toBeNull();
  });

  it("chooses an active run when there is no explicit selection", () => {
    expect(selectUnifiedEvolutionRun(rows, "supervised", null)?.runId).toBe("active");
  });

  it("defaults to the latest autonomous run before older self worktree history", () => {
    const selfRows = buildUnifiedEvolutionRuns({
      supervisedWorktreeRuns: [worktreeRun("self-history", {
        status: "done",
        selfEvolutionOrigin: { sourceTrack: "self_evolution", goal: "较早的自进化工作树" },
      })],
      selfSnapshot: selfSnapshot({
        autonomousLatestRun: autonomousRun("self-latest", {
          status: "completed",
          request: { goal: "最近的自主进化", maxIterations: 1 },
        }),
      }),
    });

    expect(selectUnifiedEvolutionRun(selfRows, "self", null)?.runId).toBe("self-latest");
  });

  it("never selects a row from the other track", () => {
    expect(selectUnifiedEvolutionRun(rows, "self", null)).toBeNull();
  });
});
