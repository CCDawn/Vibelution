/** @vitest-environment happy-dom */
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

type QueryState = {
  isPending: boolean;
  isError: boolean;
  isSuccess: boolean;
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
    isSuccess: false,
    error: null,
    data: undefined,
    refetch: () => {},
  },
}));

const experimentQueryState = vi.hoisted((): { current: QueryState } => ({
  current: {
    isPending: false,
    isError: false,
    isSuccess: false,
    error: null,
    data: undefined,
    refetch: () => {},
  },
}));

const submissionReadinessQueryState = vi.hoisted((): { current: QueryState } => ({
  current: {
    isPending: false,
    isError: false,
    isSuccess: false,
    error: null,
    data: undefined,
    refetch: () => {},
  },
}));

const catalogOverviewQueryState = vi.hoisted((): { current: QueryState } => ({
  current: {
    isPending: false,
    isError: false,
    isSuccess: false,
    error: null,
    data: undefined,
    refetch: () => {},
  },
}));

const tokenUsageQueryState = vi.hoisted((): { current: QueryState } => ({
  current: {
    isPending: false,
    isError: false,
    isSuccess: false,
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
    inspectSubmissionDeliverables: blank(),
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
  useQuery: (options?: { queryKey?: readonly unknown[]; enabled?: boolean }) => {
    const key = (options?.queryKey ?? []) as readonly unknown[];
    if (key.includes("catalog-overview")) {
      return catalogOverviewQueryState.current;
    }
    if (key.includes("token-usage")) {
      return tokenUsageQueryState.current;
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
          const onSuccessResult = options?.onSuccess?.(mock.data ?? {}, variables, undefined);
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
    isSuccess: true,
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

function setSubmissionReadiness(data: unknown) {
  Object.assign(submissionReadinessQueryState.current, {
    isPending: false,
    isError: false,
    error: null,
    data,
    refetch: () => {},
  });
}

function setCatalogOverview(data: unknown) {
  Object.assign(catalogOverviewQueryState.current, {
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
      { key: "full_catalog_results", label: "125 题结果包", required: true, status: "blocked", detail: "0/125 题已通过提交门。", blocker: "full_catalog_results_incomplete", primaryAction: { kind: "repair", target: "full-catalog-results", label: "修复缺失结果", questionId: "SCI-042" } },
      { key: "deep_experiment_suite", label: "两个深实验包", required: true, status: "blocked", detail: "0/2 个独立深实验已通过提交门。", blocker: "deep_experiment_suite_incomplete", primaryAction: { kind: "repair", target: "deep-experiment-suite", label: "修复深实验", questionId: "SCI-097" } },
      { key: "technical_proposal_pdf", label: "20 页以内技术方案 PDF", required: true, status: "blocked", detail: "尚无服务端确认的 PDF 提交包收据。", blocker: "technical_proposal_pdf_not_packaged", primaryAction: { kind: "inspect", target: "submission-package", label: "检查交付材料" } },
      { key: "demo_video", label: "10 分钟以内演示视频", required: false, status: "optional", detail: "可选附件尚无服务端确认收据。", blocker: "", primaryAction: { kind: "inspect", target: "submission-package", label: "检查交付材料" } },
      { key: "test_api", label: "稳定测试 API", required: true, status: "blocked", detail: "尚无可提交 API 入口与演练收据。", blocker: "test_api_not_packaged", primaryAction: { kind: "inspect", target: "submission-package", label: "检查交付材料" } },
      { key: "source_code", label: "源码与复现说明", required: true, status: "blocked", detail: "尚无干净克隆复现与源码提交包收据。", blocker: "source_code_not_packaged", primaryAction: { kind: "inspect", target: "submission-package", label: "检查交付材料" } },
    ],
    blockers: [{ code: "full_catalog_results_incomplete", label: "125 题结果包", action: { kind: "repair", target: "full-catalog-results", label: "修复缺失结果", questionId: "SCI-042" } }],
    programSummary: { title: "Challenge Cup", questionCount: 125, approvedQuestionCount: 0, deepExperimentCount: 2, approvedDeepExperimentCount: 0 },
  };
}

describe("ChallengeMvpProgressPanel", () => {
  beforeEach(() => {
    for (const state of [questionQueryState.current, experimentQueryState.current, submissionReadinessQueryState.current, catalogOverviewQueryState.current, tokenUsageQueryState.current]) {
      Object.assign(state, {
        isPending: false,
        isError: false,
        isSuccess: false,
        error: null,
        data: undefined,
        refetch: () => {},
      });
    }
    setSubmissionReadiness(submissionReadiness());
    setCatalogOverview({
      schemaVersion: 1,
      teamId: "team-1",
      generatedAt: "2026-08-20T00:00:00Z",
      questionCount: 0,
      counts: { queued: 0, running: 0, succeeded: 0, failed: 0 },
      questions: [],
    });
    mutationState.reset();
    queryClientMock.invalidateQueries.mockClear();
  });

  it("composes the standalone submission readiness panel", () => {
    const markup = renderToStaticMarkup(<ChallengeMvpProgressPanel teamId="team-1" onOpenQuestion={vi.fn()} />);
    expect(markup).toContain('data-vui="challenge-submission-readiness"');
  });

  it("renders Program v2 and question rows", () => {
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
    const markup = renderToStaticMarkup(
      <ChallengeMvpProgressPanel teamId="team-1" onOpenQuestion={vi.fn()} />,
    );
    expect(markup).toContain("AI Research Program v2");
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
  });

  it("keeps zero-approved Program state explicit without claiming completion", () => {
    setMainData(emptyMainData());
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
    const markup = renderToStaticMarkup(
      <ChallengeMvpProgressPanel teamId="team-1" onOpenQuestion={vi.fn()} />,
    );
    expect(markup).toContain("Program v2 状态不可用");
    expect(markup).toContain("competitionProgramProjection");
    expect(markup).toContain("单题结果与审核");
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
    const markup = renderToStaticMarkup(
      <ChallengeMvpProgressPanel teamId="team-1" onOpenQuestion={vi.fn()} />,
    );
    expect(markup).toContain("比赛状态加载失败");
    expect(markup).toContain("program projection unavailable");
    expect(markup).toContain("单题结果与审核");
    expect(markup).toContain("暂无已验证题目");
  });

  it("surfaces the register/publish entry only after the question status loads", () => {
    setMainData(emptyMainData());
    let markup = renderToStaticMarkup(
      <ChallengeMvpProgressPanel teamId="team-1" onOpenQuestion={vi.fn()} />,
    );
    expect(markup).toContain("登记题目 / 发布产出");
    expect(panelSource).toContain("ChallengeQuestionRegisterDialog");

    Object.assign(questionQueryState.current, {
      isPending: true,
      isError: false,
      isSuccess: false,
      error: null,
      data: undefined,
      refetch: vi.fn(),
    });
    markup = renderToStaticMarkup(
      <ChallengeMvpProgressPanel teamId="team-1" onOpenQuestion={vi.fn()} />,
    );
    expect(markup).not.toContain("登记题目 / 发布产出");

    Object.assign(questionQueryState.current, {
      isPending: false,
      isError: true,
      isSuccess: false,
      error: new Error("question status unavailable"),
      data: undefined,
      refetch: vi.fn(),
    });
    markup = renderToStaticMarkup(
      <ChallengeMvpProgressPanel teamId="team-1" onOpenQuestion={vi.fn()} />,
    );
    expect(markup).not.toContain("登记题目 / 发布产出");
  });

  it("renders pending and error states for program token usage instead of hiding them", () => {
    setMainData(emptyMainData());
    Object.assign(tokenUsageQueryState.current, {
      isPending: true,
      isError: false,
      error: null,
      data: undefined,
      refetch: vi.fn(),
    });
    let markup = renderToStaticMarkup(
      <ChallengeMvpProgressPanel teamId="team-1" onOpenQuestion={vi.fn()} />,
    );
    expect(markup).toContain("读取 token 消耗");

    Object.assign(tokenUsageQueryState.current, {
      isPending: false,
      isError: true,
      error: new Error("token usage unavailable"),
      data: undefined,
      refetch: vi.fn(),
    });
    markup = renderToStaticMarkup(
      <ChallengeMvpProgressPanel teamId="team-1" onOpenQuestion={vi.fn()} />,
    );
    expect(markup).toContain("token 消耗加载失败");
    expect(markup).toContain("token usage unavailable");
  });

  it("links the jump nav to every rendered progress section", () => {
    setMainData(emptyMainData());
    const markup = renderToStaticMarkup(
      <ChallengeMvpProgressPanel teamId="team-1" onOpenQuestion={vi.fn()} />,
    );
    for (const id of ["program", "submission", "readiness", "batches", "token", "catalog", "results"]) {
      expect(markup).toContain(`data-testid="ch-cup-jump-ch-cup-${id}"`);
      expect(markup).toContain(`id="ch-cup-${id}"`);
    }
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

  it("no longer mounts the removed DEV controls surface", () => {
    setMainData(emptyMainData());
    const markup = renderToStaticMarkup(
      <ChallengeMvpProgressPanel teamId="team-1" onOpenQuestion={vi.fn()} />,
    );
    expect(markup).not.toContain('id="ch-cup-dev"');
    expect(markup).not.toContain("开发态");
    expect(panelSource).not.toContain("fetchChallengeCupDevControlSnapshot");
    expect(panelSource).not.toContain("runChallengeCupDevReadiness");
    expect(panelSource).not.toContain("runChallengeCupDevBatch");
    expect(panelSource).not.toContain("import.meta.env.DEV");
  });

  it("uses the canonical query keys so the planning status dedupes with other panels", () => {
    expect(panelSource).toContain("queryKeys.challengeQuestionRunStatus(teamId)");
    expect(panelSource).toContain("experimentPlanningStatusQueryKey(teamId)");
    expect(panelSource).not.toContain('"program-v2"');
  });
});
