import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";

import type { ExperimentPlanningStatusPayload } from "../experimentLoopModel";
import {
  ChallengeCupOperationsWorkspace,
  type ChallengeCupOperationsWorkspaceProps,
} from "./ChallengeCupOperationsWorkspace";
const componentSource = readFileSync(
  new URL("./ChallengeCupOperationsWorkspace.tsx", import.meta.url),
  "utf8",
);
const componentStyles = readFileSync(
  new URL("./ChallengeCupOperationsWorkspace.module.css", import.meta.url),
  "utf8",
);

type ChallengeProjection = NonNullable<ExperimentPlanningStatusPayload["challengeProgramProjection"]>;

function projection(): ChallengeProjection {
  return {
    schemaVersion: 1,
    migrationMode: "program_projection_over_append_only_legacy_history",
    program: {
      title: "面向前沿科学问题的 AI 假设生成与研究计划设计平台",
      officialProblemId: "XH-202619",
      track: "赛道一 / 方向一 / A 科学假设生成与研究计划设计",
      officialQuestionCount: 125,
      deliveryMode: "mvp",
      immediateQuestionCount: 4,
      directionBRole: "representative_deep_validation_only",
      completed: false,
    },
    stage1ComplianceReadiness: {
      status: "completed",
      completionDefinition: "one_golden_sample_and_three_test_questions_pass_mvp_gates",
      blockers: [],
      dashscopeQwenProvider: {
        configured: true,
        providerIds: ["dashscope"],
        modelRefs: ["dashscope/qwen-plus"],
      },
      officialModelCallEvidence: {
        count: 8,
        evidenceIds: Array.from({ length: 8 }, (_, index) => `call-${index + 1}`),
      },
      singleQuestionSample: {
        required: 1,
        completed: 1,
        questionId: "SCI-096",
        realCallsRequired: true,
      },
      trialRun: {
        required: 3,
        completed: 3,
        realCallsRequired: true,
        completedQuestionIds: ["SCI-031", "SCI-097", "SCI-118"],
        outcomeCounts: { approved: 1, review_required: 3 },
      },
      mvpManifest: {
        requiredQuestionCount: 4,
        completedQuestionCount: 4,
        goldenSampleQuestionId: "SCI-096",
        testQuestionIds: ["SCI-031", "SCI-097", "SCI-118"],
        scaleUpDeferred: true,
      },
      independentEvaluationDimensions: ["novelty", "testability", "evidence", "impact", "feasibility", "clarity", "risk"],
      aggregateScoreAllowed: false,
      humanGates: ["scope", "evidence", "hypothesis", "plan"],
      acceptance: {
        schemaValidation: true,
        citationValidation: true,
        minimumHypothesisCount: 2,
        allSevenDimensionsReviewed: true,
        allFourHumanGatesApproved: true,
        researchPlanPresent: true,
        feedbackRevisionCount: 1,
      },
    },
    stage2BatchGovernance: {
      status: "deferred_after_mvp",
      completionDefinition: "all_125_questions_schema_valid_traceable_and_audited",
      questionCount: 125,
      completedQuestionCount: 0,
      batchSize: 5,
      batchCount: 25,
      completedBatchCount: 0,
      failedOrBlockedCountedAsComplete: false,
      aggregateScoreAllowed: false,
      pipeline: ["problem_understanding", "evidence_retrieval"],
      ledger: { initialized: false, manifestHashVerified: false, citationAuditComplete: false },
    },
    stage3DeepResearchDelivery: {
      status: "partial",
      completionDefinition: "three_representative_cases_and_submission_package",
      representativeCaseCount: 1,
      requiredRepresentativeCaseCount: 3,
      caseRecords: [{
        caseId: "fashion-mnist",
        title: "FashionMNIST 预测编码",
        internalStatus: "accepted_for_writeup",
        projectCompletionStatus: "case_only",
        bestValidatedResultId: "revision4",
        claimBoundary: "仅证明工程闭环，不证明真实神经机制。",
      }],
      projectCompleted: false,
    },
    compatibility: {
      legacyLifecycleProjectionPreserved: true,
      legacyStage2DesignStatus: "frozen",
      legacyStage3CaseStatus: "accepted_for_writeup",
      acceptedForWriteupMeansProgramComplete: false,
      appendOnlyEvidencePreserved: true,
      historyRewritten: false,
    },
  };
}

function props(overrides: Partial<ChallengeCupOperationsWorkspaceProps> = {}): ChallengeCupOperationsWorkspaceProps {
  return {
    projection: projection(),
    agents: [{
      agentId: "agent-source-finder",
      name: "白书遥",
      code: "A033",
      role: "资料寻找",
      workspace: "证据链",
      model: "gpt-5.6-terra",
      status: "可用",
      tone: "ready",
      configHref: "/agents/agent-source-finder",
    }],
    graphHref: "/teams?team=research-team&researchView=canvas",
    researchTopic: "神经预测编码中的层级反馈与可塑性学习机制",
    isLoading: false,
    isUnavailable: false,
    isRefreshing: false,
    onRefresh: () => undefined,
    ...overrides,
  };
}

function renderWorkspace(overrides: Partial<ChallengeCupOperationsWorkspaceProps> = {}) {
  return renderToStaticMarkup(
    <MemoryRouter>
      <ChallengeCupOperationsWorkspace {...props(overrides)} />
    </MemoryRouter>,
  );
}

describe("ChallengeCupOperationsWorkspace", () => {
  it("renders the approved desktop MVP hierarchy from the live projection", () => {
    const markup = renderWorkspace();

    expect(markup).toContain("XH-202619");
    expect(markup).toContain("面向前沿科学问题的 AI 假设生成与研究计划设计平台");
    expect(markup).toContain("机器验证");
    expect(markup).toContain("<strong>4 / 4</strong>");
    expect(markup).toContain("人工审核");
    expect(markup).toContain("<strong>1 / 4</strong>");
    expect(markup).toContain("3 题待抽检");
    expect(markup).toContain("模型调用证据");
    expect(markup).toContain("125 题批处理与 3 个代表性深研案例");
    expect(markup).toContain("FashionMNIST 仅为工程案例");
    expect(markup).toContain("白书遥");
  });

  it("renders the approved universal research platform from the live projection without preview claims", () => {
    const markup = renderWorkspace({
      projectSwitcher: (context) => (
        <div>
          项目切换器 · {context.statusLabel} · {context.primaryActionLabel}
        </div>
      ),
      surface: "workspace",
      stageHrefs: {
        knowledge_collection: "/teams/research-team/source-collection",
        experiment: "/teams/research-team/experiment",
        iteration: "/teams/research-team/iteration",
      },
    });

    expect(markup).toContain('data-testid="challenge-cup-platform-workspace"');
    expect(markup).toContain("知识搜集");
    expect(markup).toContain("实验设计");
    expect(markup).toContain("执行与迭代");
    expect(markup).toContain("资料工作表");
    expect(markup).toContain("项目切换器");
    expect(markup).toContain("继续知识搜集");
    expect(markup).toContain("当前对象");
    expect(markup).toContain("神经预测编码中的层级反馈与可塑性学习机制");
    expect(markup).toContain("Claim Map 0");
    expect(markup).toContain("当前投影未提供正式 Claim Map 时保持为 0");
    expect(markup).toContain("SCI-096");
    expect(markup).toContain("模型调用证据");
    expect(markup).not.toContain("weight=0.875");
  });

  it("keeps the approved identity visible during loading and unavailable states", () => {
    const loadingMarkup = renderWorkspace({ projection: undefined, isLoading: true });
    const unavailableMarkup = renderWorkspace({ projection: undefined, isUnavailable: true });

    expect(loadingMarkup).toContain("XH-202619");
    expect(loadingMarkup).toContain("正在读取挑战杯 MVP 状态");
    expect(unavailableMarkup).toContain("XH-202619");
    expect(unavailableMarkup).toContain("无法读取 MVP 投影");
    expect(unavailableMarkup).not.toContain("实验设计");
  });

  it("keeps production styling desktop-only and scoped to the workspace", () => {
    expect(componentSource).toContain('data-testid="challenge-cup-operations-workspace"');
    expect(componentStyles).toContain(".workspace");
    expect(componentStyles).toContain("min-width: 860px");
    expect(componentStyles).toContain("container-type: inline-size");
    expect(componentStyles).toContain("@container challenge-workspace (max-width: 1080px)");
    expect(componentStyles).toContain("@container challenge-workspace (min-width: 1600px)");
    expect(componentStyles).toContain(".platform-console");
    expect(componentStyles).toContain("grid-template-columns: 220px minmax(620px, 1fr) clamp(280px, 19vw, 340px)");
    expect(componentStyles).toContain(".platform-stage-rail");
    expect(componentStyles).toContain("position: sticky");
    expect(componentStyles).toContain(".platform-grid");
    expect(componentStyles).toContain("display: contents");
    expect(componentStyles).toContain("width: 100%");
    expect(componentStyles).toContain("max-width: none");
    expect(componentStyles).not.toContain("@media (max-width: 760px)");
    expect(componentStyles).not.toContain("@media (max-width: 430px)");
  });
});
