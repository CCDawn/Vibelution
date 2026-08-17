import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { queryState } from "./__testHelpers/mvpProgressQueryState";
import { ChallengeMvpProgressPanel } from "./ChallengeMvpProgressPanel";

vi.mock("@tanstack/react-query", () => ({ useQuery: () => queryState.current() }));

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

describe("ChallengeMvpProgressPanel", () => {
  afterEach(() => queryState.reset());

  it("renders Program v2, 125-question state, independent experiments, and question rows", () => {
    queryState.set({
      isPending: false,
      isError: false,
      error: null,
      data: {
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
      },
      refetch: vi.fn(),
    });
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
  });

  it("keeps zero-approved Program state explicit without claiming completion", () => {
    queryState.set({
      isPending: false,
      isError: false,
      error: null,
      data: {
        questionStatus: questionStatus(),
        experimentStatus: experimentStatus(),
        questionError: "",
        programError: "",
      },
      refetch: vi.fn(),
    });
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
    queryState.set({
      isPending: false,
      isError: false,
      error: null,
      data: {
        questionStatus: questionStatus(),
        experimentStatus: null,
        questionError: "",
        programError: "program projection unavailable",
      },
      refetch: vi.fn(),
    });
    const markup = renderToStaticMarkup(
      <ChallengeMvpProgressPanel teamId="team-1" onOpenQuestion={vi.fn()} />,
    );
    expect(markup).toContain("Program v2 状态不可用");
    expect(markup).toContain("program projection unavailable");
    expect(markup).toContain("单题结果与审核");
  });

  it("surfaces a total load error with a retry action", () => {
    queryState.set({
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
});
