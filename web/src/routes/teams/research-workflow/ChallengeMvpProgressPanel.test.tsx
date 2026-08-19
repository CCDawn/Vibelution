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

const questionQueryState = vi.hoisted((): { current: QueryState } => ({
  current: {
    isPending: false,
    isError: false,
    error: null,
    data: undefined,
    refetch: () => {},
  },
}));

const experimentQueryState = vi.hoisted((): { current: QueryState } => ({
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

const submissionReadinessQueryState = vi.hoisted((): { current: QueryState } => ({
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
    if (key.includes("submission-readiness")) {
      return submissionReadinessQueryState.current;
    }
    if (key.includes("question-runs")) {
      return questionQueryState.current;
    }
    return experimentQueryState.current;
  },
  useMutation: (options?: { mutationFn?: { name?: string }; onSuccess?: (...args: unknown[]) => unknown }) => {
    const name = options?.mutationFn?.name ?? "default";
    const mock = mutationState.get(name);
    return {
      ...mock,
      mutate: (variables?: unknown) => {
        void (async () => {
          Object.assign(mock, { isPending: true, isIdle: false, isError: false, isSuccess: false });
          mock.mutate(variables);
          const onSuccessResult = options?.onSuccess?.({}, variables, undefined);
          await onSuccessResult;
          Object.assign(mock, { isPending: false, isIdle: false, isSuccess: true });
        })();
      },
    };
  },
  useQueryClient: () => queryClientMock,
}));

import { ChallengeMvpProgressPanel } from "./ChallengeMvpProgressPanel";
import panelSource from "./ChallengeMvpProgressPanel.tsx?raw";

function setQuestionData(data: unknown) {
  Object.assign(questionQueryState.current, {
    isPending: false,
    isError: false,
    error: null,
    data,
    refetch: () => {},
  });
}

function setExperimentData(data: unknown) {
  Object.assign(experimentQueryState.current, {
    isPending: false,
    isError: false,
    error: null,
    data,
    refetch: () => {},
  });
}

function setMainData(data: { questionStatus: unknown; experimentStatus: unknown }) {
  setQuestionData(data.questionStatus);
  setExperimentData(data.experimentStatus);
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

function setSubmissionReadiness(data: unknown) {
  Object.assign(submissionReadinessQueryState.current, {
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

function stateRepairReadiness() {
  return devSnapshot({
    report: {
      schemaVersion: 1,
      reportKind: "platform_flow_readiness",
      status: "FAILED",
      mode: "dev",
      realCampaignAllowed: false,
      researchAuthorizationRequired: true,
      nextLegalAction: "repair_failed_platform_gates",
      generatedAt: "2026-08-18T00:00:00Z",
      updatedAt: "2026-08-18T00:00:00Z",
      gates: [
        { gateId: "r1_clean_clone", status: "FAIL", detail: "R1 pytest failed" },
      ],
    },
    nextLegalAction: "repair_failed_platform_gates",
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
  };
}

function submissionReadiness() {
  return {
    schemaVersion: 1,
    teamId: "team-1",
    status: "blocked",
    readyCount: 0,
    requiredCount: 5,
    blockerCount: 5,
    artifacts: [
      { key: "full_catalog_results", label: "125 题结果包", required: true, status: "blocked", detail: "0/125 题已通过提交门。", blocker: "full_catalog_results_incomplete", primaryAction: { kind: "repair", target: "full-catalog-results", label: "修复缺失结果" } },
      { key: "deep_experiment_suite", label: "两个深实验包", required: true, status: "blocked", detail: "0/2 个独立深实验已通过提交门。", blocker: "deep_experiment_suite_incomplete", primaryAction: { kind: "repair", target: "deep-experiment-suite", label: "修复深实验" } },
      { key: "technical_proposal_pdf", label: "20 页以内技术方案 PDF", required: true, status: "blocked", detail: "尚无服务端确认的 PDF 提交包收据。", blocker: "technical_proposal_pdf_not_packaged", primaryAction: { kind: "export", target: "submission-package", label: "生成提交清单" } },
      { key: "demo_video", label: "10 分钟以内演示视频", required: false, status: "optional", detail: "可选附件尚无服务端确认收据。", blocker: "", primaryAction: { kind: "export", target: "submission-package", label: "查看交付清单" } },
      { key: "test_api", label: "稳定测试 API", required: true, status: "blocked", detail: "尚无可提交 API 入口与演练收据。", blocker: "test_api_not_packaged", primaryAction: { kind: "export", target: "submission-package", label: "生成提交清单" } },
      { key: "source_code", label: "源码与复现说明", required: true, status: "blocked", detail: "尚无干净克隆复现与源码提交包收据。", blocker: "source_code_not_packaged", primaryAction: { kind: "export", target: "submission-package", label: "生成提交清单" } },
    ],
    blockers: [{ code: "full_catalog_results_incomplete", label: "125 题结果包", action: { kind: "repair", target: "full-catalog-results", label: "修复缺失结果" } }],
    programSummary: { title: "Challenge Cup", questionCount: 125, approvedQuestionCount: 0, deepExperimentCount: 2, approvedDeepExperimentCount: 0 },
  };
}

function findButton(container: HTMLElement, text: string): HTMLButtonElement | undefined {
  return Array.from(container.querySelectorAll("button"))
    .find((button) => button.textContent?.includes(text)) as HTMLButtonElement | undefined;
}

describe("ChallengeMvpProgressPanel", () => {
  beforeEach(() => {
    for (const state of [questionQueryState.current, experimentQueryState.current, devControlsQueryState.current, submissionReadinessQueryState.current]) {
      Object.assign(state, {
        isPending: false,
        isError: false,
        error: null,
        data: undefined,
        refetch: () => {},
      });
    }
    setSubmissionReadiness(submissionReadiness());
    mutationState.reset();
    queryClientMock.invalidateQueries.mockClear();
  });

  it("keeps submission readiness as one low-density source with a single primary action", () => {
    const markup = renderToStaticMarkup(<ChallengeMvpProgressPanel teamId="team-1" onOpenQuestion={vi.fn()} />);

    expect(markup).toContain('data-vui="challenge-submission-readiness"');
    expect(markup).toContain("125 题结果包");
    expect(markup).toContain("两个深实验包");
    expect(markup).toContain("20 页以内技术方案 PDF");
    expect(markup).toContain("10 分钟以内演示视频");
    expect(markup).toContain("稳定测试 API");
    expect(markup).toContain("源码与复现说明");
    expect(markup).toContain("查看阻塞项");
    expect(markup).not.toContain("themeId");
    expect(markup).not.toContain("campaignId");
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
      experimentStatus: {},
    });
    setDevControls(devSnapshot());
    const markup = renderToStaticMarkup(
      <ChallengeMvpProgressPanel teamId="team-1" onOpenQuestion={vi.fn()} />,
    );
    expect(markup).toContain("Program v2 状态不可用");
    expect(markup).toContain("competitionProgramProjection");
    expect(markup).toContain("单题结果与审核");
    expect(markup).toContain("运行 DEV readiness");
  });

  it("shows the program error independently from available question results", () => {
    setQuestionData(questionStatus());
    Object.assign(experimentQueryState.current, {
      isPending: false,
      isError: true,
      error: new Error("program projection unavailable"),
      data: undefined,
      refetch: vi.fn(),
    });
    setDevControls(devSnapshot());
    const markup = renderToStaticMarkup(
      <ChallengeMvpProgressPanel teamId="team-1" onOpenQuestion={vi.fn()} />,
    );
    expect(markup).toContain("比赛状态加载失败");
    expect(markup).toContain("program projection unavailable");
    expect(markup).toContain("单题结果与审核");
    expect(markup).toContain("暂无已验证题目");
  });

  it("offers a register/publish entry that opens the question-write dialog", async () => {
    setMainData(emptyMainData());
    setDevControls(devSnapshot());
    const markup = renderToStaticMarkup(
      <ChallengeMvpProgressPanel teamId="team-1" onOpenQuestion={vi.fn()} />,
    );
    expect(markup).toContain("登记 / 发布题目产出");

    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => {
      root.render(<ChallengeMvpProgressPanel teamId="team-1" onOpenQuestion={vi.fn()} />);
    });
    const entry = Array.from(container.querySelectorAll("button"))
      .find((button) => button.textContent?.includes("登记 / 发布题目产出"));
    expect(entry).toBeTruthy();
    await act(async () => {
      entry!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(document.body.querySelector('[role="dialog"]')).not.toBeNull();
    expect(document.body.textContent).toContain("粘贴研究运行产出的题目 JSON");
    await act(async () => {
      root.unmount();
    });
    container.remove();
  });

  it("surfaces a total load error with a retry action", () => {
    for (const state of [questionQueryState.current, experimentQueryState.current]) {
      Object.assign(state, {
        isPending: false,
        isError: true,
        error: new Error("program and question status unavailable"),
        data: undefined,
        refetch: vi.fn(),
      });
    }
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

  it("routes normal batch actions through retryFailed=false and repair through retryFailed=true", () => {
    expect(panelSource).toMatch(/async function runDev1[\s\S]*?retryFailed: false/);
    expect(panelSource).toMatch(/async function runDev5[\s\S]*?retryFailed: false/);
    expect(panelSource).toMatch(/async function repairDev1[\s\S]*?retryFailed: true/);
    expect(panelSource).toMatch(/async function repairDev5[\s\S]*?retryFailed: true/);
  });

  it("uses the canonical query keys so the planning status dedupes with other panels", () => {
    expect(panelSource).toContain("queryKeys.challengeQuestionRunStatus(teamId)");
    expect(panelSource).toContain("experimentPlanningStatusQueryKey(teamId)");
    expect(panelSource).toContain("queryKeys.challengeSubmissionReadiness(teamId)");
    expect(panelSource).not.toContain('"program-v2"');
  });

  it("gates the DEV readiness/fixture/repair controls behind import.meta.env.DEV", () => {
    expect(panelSource).toContain("import.meta.env.DEV");
    expect(panelSource).toMatch(/import\.meta\.env\.DEV && Boolean\(teamId/);
    expect(panelSource).toMatch(/\{import\.meta\.env\.DEV \?\s*\(\s*<section className=\{styles\.devControls\}/);
  });

  it("clicks the full readiness → dev-1 → dev-5(maxItems=2) → resume(null) loop", async () => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);

    const readinessSpy = vi.fn();
    const dev1Spy = vi.fn();
    const runDev5Spy = vi.fn();
    mutationState.set("runDevReadiness", { mutate: readinessSpy });
    mutationState.set("runDev1", { mutate: dev1Spy });
    mutationState.set("runDev5", { mutate: runDev5Spy });
    setMainData(emptyMainData());
    setDevControls(devSnapshot());

    await act(async () => {
      root.render(<ChallengeMvpProgressPanel teamId="team-1" onOpenQuestion={vi.fn()} />);
    });

    let readinessButton = findButton(container, "运行 DEV readiness");
    expect(readinessButton).toBeTruthy();
    await act(async () => {
      readinessButton!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(readinessSpy).toHaveBeenCalledWith({ teamId: "team-1" });
    expect(queryClientMock.invalidateQueries).toHaveBeenCalled();

    setDevControls(stateReadinessOnly());
    await act(async () => {
      root.render(<ChallengeMvpProgressPanel teamId="team-1" onOpenQuestion={vi.fn()} />);
    });
    let dev1Button = findButton(container, "运行 dev-1 fixture");
    expect(dev1Button).toBeTruthy();
    await act(async () => {
      dev1Button!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(dev1Spy).toHaveBeenCalledWith({ teamId: "team-1" });

    setDevControls(stateDev1Done());
    await act(async () => {
      root.render(<ChallengeMvpProgressPanel teamId="team-1" onOpenQuestion={vi.fn()} />);
    });
    let dev5First = findButton(container, "首次运行 dev-5");
    expect(dev5First).toBeTruthy();
    await act(async () => {
      dev5First!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(runDev5Spy).toHaveBeenLastCalledWith({ teamId: "team-1", maxItems: 2 });

    setDevControls(stateDev5Paused());
    await act(async () => {
      root.render(<ChallengeMvpProgressPanel teamId="team-1" onOpenQuestion={vi.fn()} />);
    });
    let resumeButton = findButton(container, "恢复 dev-5");
    expect(resumeButton).toBeTruthy();
    await act(async () => {
      resumeButton!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(runDev5Spy).toHaveBeenLastCalledWith({ teamId: "team-1", maxItems: null });

    setDevControls(stateDev5Done());
    await act(async () => {
      root.render(<ChallengeMvpProgressPanel teamId="team-1" onOpenQuestion={vi.fn()} />);
    });
    expect(container.textContent).toContain("RESEARCH_AUTHORIZATION_REQUIRED");

    await act(async () => {
      root.unmount();
    });
    container.remove();
  });

  it("renders a re-run readiness repair action for failed platform gates without advancing", () => {
    setMainData(emptyMainData());
    setDevControls(stateRepairReadiness());
    const markup = renderToStaticMarkup(
      <ChallengeMvpProgressPanel teamId="team-1" onOpenQuestion={vi.fn()} />,
    );
    expect(markup).toContain("重新运行 readiness");
    expect(markup).toContain("禁止放行");
    expect(markup).not.toContain("运行 DEV readiness");
    expect(markup).not.toContain("运行 dev-1 fixture");
    expect(markup).not.toContain("首次运行 dev-5");
  });

  it("re-runs readiness from the failed-platform-gates repair action", async () => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    const readinessSpy = vi.fn();
    mutationState.set("runDevReadiness", { mutate: readinessSpy });
    setMainData(emptyMainData());
    setDevControls(stateRepairReadiness());

    await act(async () => {
      root.render(<ChallengeMvpProgressPanel teamId="team-1" onOpenQuestion={vi.fn()} />);
    });
    const repairButton = findButton(container, "重新运行 readiness");
    expect(repairButton).toBeTruthy();
    await act(async () => {
      repairButton!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(readinessSpy).toHaveBeenCalledWith({ teamId: "team-1" });
    expect(queryClientMock.invalidateQueries).toHaveBeenCalled();

    await act(async () => {
      root.unmount();
    });
    container.remove();
  });

  it("clicks the dev-1 repair button that posts retryFailed=true", async () => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    const repairDev1Spy = vi.fn();
    mutationState.set("repairDev1", { mutate: repairDev1Spy });
    setMainData(emptyMainData());
    setDevControls(stateDev1Repair());

    await act(async () => {
      root.render(<ChallengeMvpProgressPanel teamId="team-1" onOpenQuestion={vi.fn()} />);
    });
    const repairButton = findButton(container, "修复 dev-1 fixture");
    expect(repairButton).toBeTruthy();
    await act(async () => {
      repairButton!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(repairDev1Spy).toHaveBeenCalledWith({ teamId: "team-1" });
    expect(container.querySelector('[data-dev-controls="actions"]')?.textContent).toContain("禁止放行");

    await act(async () => {
      root.unmount();
    });
    container.remove();
  });

  it("clicks the dev-5 repair button that posts retryFailed=true", async () => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    const repairDev5Spy = vi.fn();
    mutationState.set("repairDev5", { mutate: repairDev5Spy });
    setMainData(emptyMainData());
    setDevControls(stateDev5Repair());

    await act(async () => {
      root.render(<ChallengeMvpProgressPanel teamId="team-1" onOpenQuestion={vi.fn()} />);
    });
    const repairButton = findButton(container, "修复 dev-5 fixture");
    expect(repairButton).toBeTruthy();
    await act(async () => {
      repairButton!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(repairDev5Spy).toHaveBeenCalledWith({ teamId: "team-1" });

    await act(async () => {
      root.unmount();
    });
    container.remove();
  });

  it("keeps actions disabled while the snapshot refetch is pending and never double-POSTs", async () => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);

    let resolveRefetch: (() => void) | undefined;
    const deferred = new Promise<void>((resolve) => {
      resolveRefetch = resolve;
    });
    queryClientMock.invalidateQueries.mockReturnValue(deferred);

    const readinessSpy = vi.fn();
    mutationState.set("runDevReadiness", { mutate: readinessSpy });
    setMainData(emptyMainData());
    setDevControls(devSnapshot());

    await act(async () => {
      root.render(<ChallengeMvpProgressPanel teamId="team-1" onOpenQuestion={vi.fn()} />);
    });
    const readinessButton = findButton(container, "运行 DEV readiness");
    expect(readinessButton).toBeTruthy();

    await act(async () => {
      readinessButton!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(readinessSpy).toHaveBeenCalledTimes(1);

    // The snapshot refetch is still pending: the action must stay disabled.
    expect(readinessButton!.disabled).toBe(true);
    expect(readinessButton!.getAttribute("disabled")).not.toBeNull();

    // A second click on the disabled action must not trigger a second POST.
    await act(async () => {
      readinessButton!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(readinessSpy).toHaveBeenCalledTimes(1);

    // Once the refetch resolves the snapshot advances and the next action appears.
    await act(async () => {
      resolveRefetch!();
    });
    setDevControls(stateReadinessOnly());
    await act(async () => {
      root.render(<ChallengeMvpProgressPanel teamId="team-1" onOpenQuestion={vi.fn()} />);
    });
    const nextButton = findButton(container, "运行 dev-1 fixture");
    expect(nextButton).toBeTruthy();
    expect(nextButton!.disabled).toBe(false);

    await act(async () => {
      root.unmount();
    });
    container.remove();
    queryClientMock.invalidateQueries.mockReset();
  });

  it("keeps DEV controls operable when the program/question query fails entirely", () => {
    for (const state of [questionQueryState.current, experimentQueryState.current]) {
      Object.assign(state, {
        isPending: false,
        isError: true,
        error: new Error("program and question boom"),
        data: undefined,
        refetch: vi.fn(),
      });
    }
    setDevControls(devSnapshot());
    const markup = renderToStaticMarkup(
      <ChallengeMvpProgressPanel teamId="team-1" onOpenQuestion={vi.fn()} />,
    );
    expect(markup).toContain("program and question boom");
    expect(markup).toContain("运行 DEV readiness");
    expect(markup).toContain("单题结果与审核");
    expect(markup).toContain("DEV 隔离边界");
  });

  it("executes DEV actions even when the program/question query failed", async () => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    for (const state of [questionQueryState.current, experimentQueryState.current]) {
      Object.assign(state, {
        isPending: false,
        isError: true,
        error: new Error("program and question boom"),
        data: undefined,
        refetch: vi.fn(),
      });
    }
    setDevControls(devSnapshot());
    const readinessSpy = vi.fn();
    mutationState.set("runDevReadiness", { mutate: readinessSpy });
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => {
      root.render(<ChallengeMvpProgressPanel teamId="team-1" onOpenQuestion={vi.fn()} />);
    });
    const readinessButton = findButton(container, "运行 DEV readiness");
    expect(readinessButton).toBeTruthy();
    await act(async () => {
      readinessButton!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(readinessSpy).toHaveBeenCalledWith({ teamId: "team-1" });
    await act(async () => {
      root.unmount();
    });
    container.remove();
  });

  it("shows an independent retry for the DEV snapshot error without hiding the program section", () => {
    setMainData(emptyMainData());
    Object.assign(devControlsQueryState.current, {
      isPending: false,
      isError: true,
      error: new Error("dev snapshot boom"),
      data: undefined,
      refetch: vi.fn(),
    });
    const markup = renderToStaticMarkup(
      <ChallengeMvpProgressPanel teamId="team-1" onOpenQuestion={vi.fn()} />,
    );
    expect(markup).toContain("dev snapshot boom");
    expect(markup).toContain('data-dev-controls="snapshot-retry"');
    expect(markup).toContain('data-dev-controls="snapshot-readiness-repair"');
    expect(markup).toContain("Challenge Cup Program v2");
    expect(markup).toContain("重新运行 DEV readiness");
  });

  it("can refetch or repair a stale DEV snapshot from the error surface", async () => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    setMainData(emptyMainData());
    const devRefetch = vi.fn();
    const readinessSpy = vi.fn();
    mutationState.set("runDevReadiness", { mutate: readinessSpy });
    Object.assign(devControlsQueryState.current, {
      isPending: false,
      isError: true,
      error: new Error("dev snapshot boom"),
      data: undefined,
      refetch: devRefetch,
    });
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => {
      root.render(<ChallengeMvpProgressPanel teamId="team-1" onOpenQuestion={vi.fn()} />);
    });
    const retryButton = container.querySelector('[data-dev-controls="snapshot-retry"]') as HTMLButtonElement | null;
    expect(retryButton).toBeTruthy();
    await act(async () => {
      retryButton!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(devRefetch).toHaveBeenCalled();
    const repairButton = container.querySelector('[data-dev-controls="snapshot-readiness-repair"]') as HTMLButtonElement | null;
    expect(repairButton).toBeTruthy();
    await act(async () => {
      repairButton!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(readinessSpy).toHaveBeenCalledWith({ teamId: "team-1" });
    await act(async () => {
      root.unmount();
    });
    container.remove();
  });

  it("announces DEV action changes in a live region", () => {
    setMainData(emptyMainData());
    setDevControls(devSnapshot());
    const markup = renderToStaticMarkup(
      <ChallengeMvpProgressPanel teamId="team-1" onOpenQuestion={vi.fn()} />,
    );
    expect(markup).toContain('aria-live="polite"');
    expect(markup).toContain('data-dev-controls="actions"');
  });
});
