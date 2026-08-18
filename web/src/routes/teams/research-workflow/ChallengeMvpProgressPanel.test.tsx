/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

type QueryState = {
  isPending: boolean;
  isError: boolean;
  error: Error | null;
  data: unknown;
  refetch: () => void;
};

type MutationMock = {
  isPending: boolean;
  isError: boolean;
  error: Error | null;
  isIdle: boolean;
  isSuccess: boolean;
  data: unknown;
  mutate: (variables?: unknown) => void;
  reset: () => void;
};

const queryState = vi.hoisted((): { current: QueryState } => ({
  current: {
    isPending: false,
    isError: false,
    error: null,
    data: undefined,
    refetch: () => {},
  },
}));

const devControlsQueryState = vi.hoisted((): { current: QueryState } => ({
  current: {
    isPending: false,
    isError: false,
    error: null,
    data: undefined,
    refetch: () => {},
  },
}));

const mutationState = vi.hoisted(() => {
  const blank = (): MutationMock => ({
    isPending: false,
    isError: false,
    error: null,
    isIdle: true,
    isSuccess: false,
    data: undefined,
    mutate: () => {},
    reset: () => {},
  });
  const map: Record<string, MutationMock> = {
    runDevReadiness: blank(),
    runDev1: blank(),
    runDev5: blank(),
    default: blank(),
  };
  return {
    get: (name: string) => map[name] ?? map.default,
    set: (name: string, patch: Partial<MutationMock>) => {
      Object.assign(map[name] ?? map.default, patch);
    },
    reset: () => {
      for (const key of Object.keys(map)) {
        Object.assign(map[key], blank());
      }
    },
  };
});

const queryClientMock = vi.hoisted(() => ({ invalidateQueries: vi.fn() }));

vi.mock("@tanstack/react-query", () => ({
  useQuery: (options?: { queryKey?: readonly unknown[] }) => {
    const key = (options?.queryKey ?? []) as readonly unknown[];
    if (key.includes("dev-controls")) {
      return devControlsQueryState.current;
    }
    return queryState.current;
  },
  useMutation: (options?: { mutationFn?: { name?: string }; onSuccess?: (...args: unknown[]) => void }) => {
    const name = options?.mutationFn?.name ?? "default";
    const mock = mutationState.get(name);
    return {
      ...mock,
      mutate: (variables?: unknown) => {
        mock.mutate(variables);
        options?.onSuccess?.({}, variables, undefined);
      },
    };
  },
  useQueryClient: () => queryClientMock,
}));

import { ChallengeMvpProgressPanel } from "./ChallengeMvpProgressPanel";

function setMainData(data: unknown) {
  Object.assign(queryState.current, {
    isPending: false,
    isError: false,
    error: null,
    data,
    refetch: () => {},
  });
}

function setDevControls(data: unknown) {
  Object.assign(devControlsQueryState.current, {
    isPending: false,
    isError: false,
    error: null,
    data,
    refetch: () => {},
  });
}

function questionStatus(results: Array<Record<string, unknown>> = []) {
  return {
    teamId: "team-1",
    storePath: "path",
    summary: {
      recordCount: results.length,
      validCandidateCount: results.length,
      validatedQuestionCount: results.length,
      validatedQuestionIds: results.map((item) => String(item.questionId)),
      validatedOutcomeCounts: { approved: results.length },
      validatedQuestionResults: results,
      completedCount: results.length,
      completedQuestionIds: results.map((item) => String(item.questionId)),
      latestCandidate: null,
    },
  };
}

function experimentStatus() {
  return {
    competitionProgramProjection: {
      schemaVersion: 2,
      contractVersion: "2.2.0",
      contractId: "cc-xh-202619-program-v2",
      status: "core_frozen",
      program: {
        problemId: "XH-202619",
        title: "面向前沿科学问题的AI假设生成与研究计划设计平台",
        track: "赛道一：科学问题",
        direction: "方向1：科学实验任务规划与反馈迭代",
        dimensions: ["A", "B"],
        directionMode: "a_plus_b",
        foundationModelFamily: "Qwen",
        officialQuestionCount: 125,
        catalogId: "science-125-questions-2021",
        catalogSha256: "D5035032F80574B9521CC9CC8D73F127721CCADF54451411004323727D2FAAB9",
        questionSchemaVersion: 2,
        completed: false,
      },
      directions: [],
      programContract: { version: "2.2.0", coreBehaviorHash: "hash" },
      fullCatalogPolicy: { version: "1.2.0", corePolicyHash: "policy" },
      questionSchema: { activeVersion: 2, readOnlyVersions: [1], migrationMode: "append_only" },
      fullCatalogResultSet: {
        questionCount: 125,
        requiredApprovedQuestionCount: 125,
        approvedQuestionCount: 0,
        approvedQuestionIds: [],
        missingQuestionCount: 125,
        complete: false,
      },
      questionCatalog: {
        catalogId: "science-125-questions-2021",
        catalogSha256: "D5035032F80574B9521CC9CC8D73F127721CCADF54451411004323727D2FAAB9",
        questionCount: 125,
        questions: [],
      },
      requiredDeepExperiments: [
        {
          experimentId: "EXP-GPU-OPERATOR-001",
          questionId: "SCI-091",
          name: "GPU 算子智能生成、自动优化与性能边界实验",
          themeId: "cc-gpu-operator-001",
          campaignId: "cc-campaign-gpu-operator-001",
          required: true,
          questionResultApproved: false,
          approved: false,
        },
        {
          experimentId: "EXP-NEURAL-SPIKE-001",
          questionId: "SCI-096",
          name: "神经元脉冲编码竞争假说实验",
          themeId: "cc-neural-information-001",
          campaignId: "cc-campaign-neural-spike-001",
          required: true,
          questionResultApproved: false,
          approved: false,
        },
      ],
      allRequiredDeepExperimentsApproved: false,
      independentThemeBoundaries: {
        separateThemes: true,
        separateCampaigns: true,
        crossExperimentScientificEvidenceReuse: "forbidden",
      },
      completion: {
        programRule: "full_catalog_result_set_approved AND all_required_deep_experiments_approved",
        fullCatalogResultSetRequired: null,
        allRequiredDeepExperimentsRequired: null,
        projectCompletedDerivedOnly: true,
        legacyQuestionCountsAffectCompletion: false,
        legacyRepresentativeCaseCountsAffectCompletion: false,
        completed: false,
      },
      directionSubmissionRequirement: {
        captured: false,
        officialPageObservedState: "submission_entry_coming_soon",
        blocksSubmissionReady: true,
      },
      legacyProjection: { mode: "read_only", schemaVersion: 1, affectsCompletion: false, deprecated: true },
      isolationPolicy: { separateThemeContracts: true, separateCampaigns: true, separateTeams: true },
    },
  };
}

type DevSnapshot = {
  schemaVersion: number;
  teamId: string;
  generatedAt: string;
  mode: string;
  realCampaignAllowed: boolean;
  nextLegalAction: string;
  report: Record<string, unknown> | null;
  batches: Record<string, Record<string, unknown>>;
  boundary: Record<string, unknown>;
};

function devSnapshot(overrides: Partial<DevSnapshot> = {}): DevSnapshot {
  return {
    schemaVersion: 1,
    teamId: "team-1",
    generatedAt: "2026-08-18T00:00:00Z",
    mode: "dev",
    realCampaignAllowed: false,
    nextLegalAction: "run_dev_readiness",
    report: null,
    batches: {},
    boundary: {
      mode: "dev",
      realCampaignAllowed: false,
      authorizedPlans: ["dev-1", "dev-5"],
      forbiddenPlans: ["dev-12", "dev-125"],
      forbiddenFeatures: [
        "real_qwen_invocation",
        "network_collection",
        "cuda_gpu",
        "dandi_download",
        "formal_submission",
        "g1_g5_g12_g125_real_gates",
      ],
      fixtureOnly: true,
    },
    ...overrides,
  };
}

function readyReport() {
  return {
    schemaVersion: 1,
    reportKind: "platform_flow_readiness",
    status: "READY",
    mode: "dev",
    realCampaignAllowed: false,
    researchAuthorizationRequired: true,
    nextLegalAction: "RESEARCH_AUTHORIZATION_REQUIRED",
    generatedAt: "2026-08-18T00:00:00Z",
    updatedAt: "2026-08-18T00:00:00Z",
    gates: [
      { gateId: "r1_clean_clone", status: "PASS", detail: "R1 pytest passed" },
      { gateId: "source_integrity", status: "PASS", detail: "clean tree verified" },
    ],
  };
}

function batchCheckpoint(planId: string, overrides: Record<string, unknown> = {}) {
  return {
    schemaVersion: 1,
    planId,
    gateId: planId === "dev-1" ? "G1" : "G5",
    questionCount: planId === "dev-1" ? 1 : 5,
    statusSummary: {
      pending: overrides.pending ?? 0,
      running: 0,
      succeeded: overrides.succeeded ?? 0,
      failed: overrides.failed ?? 0,
      blocked: overrides.blocked ?? 0,
    },
    pendingCount: overrides.pending ?? 0,
    succeededCount: overrides.succeeded ?? 0,
    failedCount: overrides.failed ?? 0,
    blockedCount: overrides.blocked ?? 0,
    totalAttempts: overrides.totalAttempts ?? (overrides.succeeded ?? 0),
    completedQuestionIds: overrides.completedQuestionIds ?? [],
    pendingQuestionIds: overrides.pendingQuestionIds ?? [],
    lastUpdatedAt: "2026-08-18T00:00:00Z",
    canResume: overrides.canResume ?? false,
    ...overrides,
  };
}

function stateReadinessOnly() {
  return devSnapshot({ report: readyReport(), nextLegalAction: "run_dev_1_fixture_batch" });
}

function stateDev1Done() {
  return devSnapshot({
    report: readyReport(),
    nextLegalAction: "run_dev_5_fixture_batch",
    batches: {
      "dev-1": batchCheckpoint("dev-1", { succeeded: 1, completedQuestionIds: ["SCI-091"], totalAttempts: 1 }),
    },
  });
}

function stateDev5Paused() {
  return devSnapshot({
    report: readyReport(),
    nextLegalAction: "resume_dev_5_fixture_batch",
    batches: {
      "dev-1": batchCheckpoint("dev-1", { succeeded: 1, completedQuestionIds: ["SCI-091"], totalAttempts: 1 }),
      "dev-5": batchCheckpoint("dev-5", {
        succeeded: 2,
        pending: 3,
        completedQuestionIds: ["SCI-092", "SCI-093"],
        pendingQuestionIds: ["SCI-094", "SCI-095", "SCI-096"],
        totalAttempts: 2,
        canResume: true,
      }),
    },
  });
}

function stateDev5Done() {
  return devSnapshot({
    report: readyReport(),
    nextLegalAction: "RESEARCH_AUTHORIZATION_REQUIRED",
    batches: {
      "dev-1": batchCheckpoint("dev-1", { succeeded: 1, completedQuestionIds: ["SCI-091"], totalAttempts: 1 }),
      "dev-5": batchCheckpoint("dev-5", {
        succeeded: 5,
        completedQuestionIds: ["SCI-092", "SCI-093", "SCI-094", "SCI-095", "SCI-096"],
        totalAttempts: 5,
      }),
    },
  });
}

function stateDev1Repair() {
  return devSnapshot({
    report: readyReport(),
    nextLegalAction: "repair_dev_1_fixture_batch",
    batches: {
      "dev-1": batchCheckpoint("dev-1", { failed: 1, succeeded: 0 }),
    },
  });
}

function stateDev5Repair() {
  return devSnapshot({
    report: readyReport(),
    nextLegalAction: "repair_dev_5_fixture_batch",
    batches: {
      "dev-1": batchCheckpoint("dev-1", { succeeded: 1, completedQuestionIds: ["SCI-091"], totalAttempts: 1 }),
      "dev-5": batchCheckpoint("dev-5", { succeeded: 2, blocked: 1, pending: 2, totalAttempts: 3 }),
    },
  });
}

function emptyMainData() {
  return {
    questionStatus: questionStatus(),
    experimentStatus: experimentStatus(),
    questionError: "",
    programError: "",
  };
}

describe("ChallengeMvpProgressPanel", () => {
  beforeEach(() => {
    Object.assign(queryState.current, {
      isPending: false,
      isError: false,
      error: null,
      data: undefined,
      refetch: () => {},
    });
    Object.assign(devControlsQueryState.current, {
      isPending: false,
      isError: false,
      error: null,
      data: undefined,
      refetch: () => {},
    });
    mutationState.reset();
    queryClientMock.invalidateQueries.mockClear();
  });

  it("renders Program v2, question rows, and real DEV readiness/boundary data", () => {
    setMainData({
      questionStatus: questionStatus([{
        questionId: "SCI-001",
        runId: "run-9",
        status: "approved",
        validation: { schemaValidation: "passed" },
        humanGates: { allApproved: true },
        outputSha256: "sha",
        artifactPath: "artifact",
      }]),
      experimentStatus: experimentStatus(),
      questionError: "",
      programError: "",
    });
    setDevControls(devSnapshot());
    const markup = renderToStaticMarkup(
      <ChallengeMvpProgressPanel teamId="team-1" onOpenQuestion={vi.fn()} />,
    );
    expect(markup).toContain("Challenge Cup Program v2");
    expect(markup).toContain("合同");
    expect(markup).toContain("2.2.0");
    expect(markup).toContain("125 题批准");
    expect(markup).toContain("0/125");
    expect(markup).toContain("GPU 算子智能生成");
    expect(markup).toContain("神经元脉冲编码");
    expect(markup).toContain("独立 Theme + 独立 Campaign");
    expect(markup).toContain("SCI-001");
    expect(markup).toContain("run-9");
    expect(markup).toContain("详情");
    expect(markup).toContain("运行 DEV readiness");
    expect(markup).toContain("未运行");
    expect(markup).toContain("dev-1");
    expect(markup).toContain("dev-5");
    expect(markup).toContain("platform_flow_ready.py");
    expect(markup).toContain("DEV fixture");
    expect(markup).toContain("dev-12 / dev-125");
  });

  it("keeps zero-approved Program state explicit without claiming completion", () => {
    setMainData(emptyMainData());
    setDevControls(devSnapshot());
    const markup = renderToStaticMarkup(
      <ChallengeMvpProgressPanel teamId="team-1" onOpenQuestion={vi.fn()} />,
    );
    expect(markup).toContain("开发/任务未完成");
    expect(markup).toContain("尚缺题目");
    expect(markup).toContain("125");
    expect(markup).toContain("未启动/未批准");
    expect(markup).toContain("暂无已验证题目");
  });

  it("shows Program v2 unavailable independently from available question results", () => {
    setMainData({
      questionStatus: questionStatus(),
      experimentStatus: null,
      questionError: "",
      programError: "program projection unavailable",
    });
    setDevControls(devSnapshot());
    const markup = renderToStaticMarkup(
      <ChallengeMvpProgressPanel teamId="team-1" onOpenQuestion={vi.fn()} />,
    );
    expect(markup).toContain("Program v2 状态不可用");
    expect(markup).toContain("program projection unavailable");
    expect(markup).toContain("单题结果与审核");
    expect(markup).toContain("运行 DEV readiness");
  });

  it("surfaces a total load error with a retry action", () => {
    Object.assign(queryState.current, {
      isPending: false,
      isError: true,
      error: new Error("program and question status unavailable"),
      data: undefined,
      refetch: vi.fn(),
    });
    const markup = renderToStaticMarkup(
      <ChallengeMvpProgressPanel teamId="team-1" onOpenQuestion={vi.fn()} />,
    );
    expect(markup).toContain("program and question status unavailable");
    expect(markup).toContain("重试");
  });

  it("advances readiness → dev-1 → dev-5 pause/resume through legal buttons", () => {
    setMainData(emptyMainData());

    setDevControls(devSnapshot());
    let markup = renderToStaticMarkup(<ChallengeMvpProgressPanel teamId="team-1" onOpenQuestion={vi.fn()} />);
    expect(markup).toContain("运行 DEV readiness");
    expect(markup).not.toContain("运行 dev-1 fixture");
    expect(markup).not.toContain("首次运行 dev-5");

    setDevControls(stateReadinessOnly());
    markup = renderToStaticMarkup(<ChallengeMvpProgressPanel teamId="team-1" onOpenQuestion={vi.fn()} />);
    expect(markup).toContain("运行 dev-1 fixture");
    expect(markup).toContain("READY");
    expect(markup).toContain("r1_clean_clone");
    expect(markup).toContain("PASS");
    expect(markup).toContain("生成 2026-08-18T00:00:00Z");
    expect(markup).not.toContain("运行 DEV readiness");

    setDevControls(stateDev1Done());
    markup = renderToStaticMarkup(<ChallengeMvpProgressPanel teamId="team-1" onOpenQuestion={vi.fn()} />);
    expect(markup).toContain("首次运行 dev-5（maxItems=2）");
    expect(markup).toContain("成功 1/1");

    setDevControls(stateDev5Paused());
    markup = renderToStaticMarkup(<ChallengeMvpProgressPanel teamId="team-1" onOpenQuestion={vi.fn()} />);
    expect(markup).toContain("恢复 dev-5（maxItems=null）");
    expect(markup).toContain("暂停可恢复");
    expect(markup).toContain("成功 2/5");
    expect(markup).toContain("canResume=true");
    expect(markup).not.toContain("首次运行 dev-5");

    setDevControls(stateDev5Done());
    markup = renderToStaticMarkup(<ChallengeMvpProgressPanel teamId="team-1" onOpenQuestion={vi.fn()} />);
    expect(markup).toContain("RESEARCH_AUTHORIZATION_REQUIRED");
    expect(markup).toContain("成功 5/5");
    expect(markup).not.toContain("首次运行 dev-5");
    expect(markup).not.toContain("恢复 dev-5");
  });

  it("runs dev-5 first with maxItems=2 then resumes with null", async () => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    const runDev5Spy = vi.fn();
    mutationState.set("runDev5", { mutate: runDev5Spy });
    setMainData(emptyMainData());

    setDevControls(stateDev1Done());
    await act(async () => {
      root.render(<ChallengeMvpProgressPanel teamId="team-1" onOpenQuestion={vi.fn()} />);
    });
    const firstButton = Array.from(container.querySelectorAll("button"))
      .find((button) => button.textContent?.includes("首次运行 dev-5"));
    expect(firstButton).toBeTruthy();
    await act(async () => {
      firstButton!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(runDev5Spy).toHaveBeenCalledWith({ teamId: "team-1", maxItems: 2 });
    expect(queryClientMock.invalidateQueries).toHaveBeenCalled();

    setDevControls(stateDev5Paused());
    await act(async () => {
      root.render(<ChallengeMvpProgressPanel teamId="team-1" onOpenQuestion={vi.fn()} />);
    });
    const resumeButton = Array.from(container.querySelectorAll("button"))
      .find((button) => button.textContent?.includes("恢复 dev-5"));
    expect(resumeButton).toBeTruthy();
    await act(async () => {
      resumeButton!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(runDev5Spy).toHaveBeenLastCalledWith({ teamId: "team-1", maxItems: null });

    await act(async () => {
      root.unmount();
    });
    container.remove();
  });

  it("blocks repair stages and never lets the next stage run", () => {
    setMainData(emptyMainData());

    setDevControls(stateDev1Repair());
    let markup = renderToStaticMarkup(<ChallengeMvpProgressPanel teamId="team-1" onOpenQuestion={vi.fn()} />);
    expect(markup).toContain("修复 dev-1 fixture");
    expect(markup).toContain("失败/阻塞");
    expect(markup).toContain("禁止放行");
    expect(markup).not.toContain("运行 dev-1 fixture");
    expect(markup).not.toContain("首次运行 dev-5");

    setDevControls(stateDev5Repair());
    markup = renderToStaticMarkup(<ChallengeMvpProgressPanel teamId="team-1" onOpenQuestion={vi.fn()} />);
    expect(markup).toContain("修复 dev-5 fixture");
    expect(markup).toContain("禁止放行");
    expect(markup).not.toContain("首次运行 dev-5");
    expect(markup).not.toContain("恢复 dev-5");
  });

  it("surfaces a mutation failure as an in-panel alert and allows a safe retry", () => {
    setMainData(emptyMainData());
    setDevControls(devSnapshot());
    mutationState.set("runDevReadiness", { isError: true, error: new Error("readiness boom") });
    const markup = renderToStaticMarkup(
      <ChallengeMvpProgressPanel teamId="team-1" onOpenQuestion={vi.fn()} />,
    );
    expect(markup).toContain('role="alert"');
    expect(markup).toContain("readiness boom");
    expect(markup).toContain("可安全重试");
    expect(markup).toContain("运行 DEV readiness");
  });

  it("shows pending/loading feedback on the active mutation button and disables it", () => {
    setMainData(emptyMainData());
    setDevControls(devSnapshot());
    mutationState.set("runDevReadiness", { isPending: true });
    const markup = renderToStaticMarkup(
      <ChallengeMvpProgressPanel teamId="team-1" onOpenQuestion={vi.fn()} />,
    );
    expect(markup).toContain("运行中");
    expect(markup).toContain('aria-busy="true"');
    expect(markup).toContain('data-pending="true"');
    expect(markup).toContain('disabled=""');
  });

  it("shows the DEV-only boundary, forbidden plans, and CLI locator as secondary diagnostics", () => {
    setMainData(emptyMainData());
    setDevControls(devSnapshot());
    const markup = renderToStaticMarkup(
      <ChallengeMvpProgressPanel teamId="team-1" onOpenQuestion={vi.fn()} />,
    );
    expect(markup).toContain("DEV 隔离边界");
    expect(markup).toContain("dev-1 / dev-5");
    expect(markup).toContain("dev-12 / dev-125");
    expect(markup).toContain("fixtureOnly=true");
    expect(markup).toContain("real_qwen_invocation");
    expect(markup).toContain("CLI 诊断");
    expect(markup).toContain("platform_flow_ready.py");
    expect(markup).toContain("下一合法动作：运行 DEV readiness");
  });
});