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
const stageRailSource = readFileSync(
  new URL("./ChallengeCupStageRail.tsx", import.meta.url),
  "utf8",
);
const experimentStageSource = readFileSync(
  new URL("./ChallengeCupExperimentStage.tsx", import.meta.url),
  "utf8",
);
const experimentProtocolSource = readFileSync(
  new URL("./ChallengeCupExperimentProtocol.tsx", import.meta.url),
  "utf8",
);
const iterationStageSource = readFileSync(
  new URL("./ChallengeCupIterationStage.tsx", import.meta.url),
  "utf8",
);
const iterationResultPackageSource = readFileSync(
  new URL("./ChallengeCupIterationResultPackage.tsx", import.meta.url),
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
      status: "blocked",
      completionDefinition: "one_golden_sample_and_three_trial_questions_pass_mvp_gates",
      blockers: ["mvp_human_review_revision_required"],
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
        outcomeCounts: { approved: 1, needs_revision: 3 },
      },
      mvpManifest: {
        requiredQuestionCount: 4,
        completedQuestionCount: 4,
        goldenSampleQuestionId: "SCI-096",
        trialQuestionIds: ["SCI-031", "SCI-097", "SCI-118"],
        testQuestionIds: ["SCI-031", "SCI-097", "SCI-118"],
        scaleUpDeferred: true,
      },
        humanReview: {
          requiredQuestionCount: 4,
          approvedQuestionCount: 1,
          approvedQuestionIds: ["SCI-096"],
          pendingQuestionIds: [],
          revisionRequiredQuestionIds: ["SCI-031", "SCI-097", "SCI-118"],
        rejectedQuestionIds: [],
        allQuestionsApproved: false,
      },
      independentEvaluationDimensions: ["novelty", "testability", "evidence", "impact", "feasibility", "clarity", "risk"],
      aggregateScoreAllowed: false,
      humanGates: ["scope", "evidence", "hypothesis", "plan"],
      acceptance: {
        schemaValidation: true,
        citationValidation: true,
        minimumHypothesisCount: 2,
        allSevenDimensionsReviewed: true,
        allFourHumanGatesApproved: false,
        researchPlanPresent: true,
        feedbackRevisionCount: 1,
      },
    },
    stage2BatchGovernance: {
      status: "blocked_by_stage1",
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
    graphHref: "/teams?team=research-team&researchView=canvas",
    questionHref: (questionId) => `/teams?team=research-team&challengeQuestion=${questionId}`,
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
  it("keeps machine validation and human revision requirements in the compact knowledge stage", () => {
    const markup = renderWorkspace();

    expect(markup).toContain("面向前沿科学问题的 AI 假设生成与研究计划设计平台");
    expect(markup).toContain("资料与证据");
    expect(markup).toContain("SCI-096");
    expect(markup).toContain("SCI-031");
    expect(markup).toContain("通过");
    expect(markup).toContain("需修订");
    expect(markup).toContain("qwen-plus");
    expect(markup).not.toContain("3 项待人工");
  });

  it("renders the approved universal research platform from the live projection without preview claims", () => {
    const markup = renderWorkspace({
      projectSwitcher: (context) => (
        <div>
          项目切换器 · {context.statusLabel} · {context.primaryActionLabel}
        </div>
      ),
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
    expect(markup).toContain("资料与证据");
    expect(markup).toContain("项目切换器");
    expect(markup).toContain("继续知识搜集");
    expect(markup).toContain("神经预测编码中的层级反馈与可塑性学习机制");
    expect(markup).not.toContain("Claim Map");
    expect(markup).not.toContain("从真实题目、模型调用证据与人工门禁判断");
    expect(markup).toContain("SCI-096");
    expect(markup).toContain("challengeQuestion=SCI-096");
    expect(markup).toContain("challengeQuestion=SCI-031");
    expect(markup).toContain("qwen-plus");
    expect(markup).not.toContain("weight=0.875");
  });

  it("routes each challenge question action to its own immutable artifact", () => {
    const markup = renderWorkspace({
      stageHrefs: {
        knowledge_collection: "/teams?team=research-team&researchView=knowledge_collection",
      },
    });

    expect(markup).toContain("challengeQuestion=SCI-096");
    expect(markup).toContain("challengeQuestion=SCI-031");
    expect(markup).toContain("challengeQuestion=SCI-097");
    expect(markup).toContain("challengeQuestion=SCI-118");
    expect(stageRailSource).toContain("to={item.href}");
    expect(componentSource).toContain("resolveQuestionHref(question.id)");
  });

  it("wires Stage 2 and Stage 3 to fixed flat-session Agent responsibilities", () => {
    expect(componentSource).toContain("<ChallengeCupExperimentStage");
    expect(componentSource).toContain("<ChallengeCupIterationStage");
    expect(experimentStageSource).toContain("<ResearchProjectAgentTaskPanel");
    expect(experimentStageSource).toContain('stage="experiment"');
    expect(iterationStageSource).toContain("<ResearchProjectAgentTaskPanel");
    expect(iterationStageSource).toContain('stage="iteration"');
    expect(componentSource).toContain("onStartResearchProjectAgentTask");
    expect(componentSource).toContain("onOpenResearchProjectAgentTask");
  });

  it("keeps the experiment protocol compact and removes the redundant intra-stage open action", () => {
    const markup = renderWorkspace({ initialStage: "experiment" });

    expect(markup).toContain("实验协议");
    expect(markup).toContain("研究计划");
    expect(markup).toContain("评审门");
    expect(markup).toContain("账本");
    expect(experimentStageSource).toContain("<ChallengeCupExperimentProtocol");
    expect(experimentStageSource).not.toContain("VRouteLinkButton");
    expect(experimentProtocolSource).toContain("VTooltip");
    expect(experimentProtocolSource).not.toContain('tone="success"');
  });

  it("keeps iteration results compact and moves result detail to hover", () => {
    const markup = renderWorkspace({ initialStage: "iteration" });

    expect(markup).toContain("研究结果");
    expect(markup).toContain("FashionMNIST 预测编码");
    expect(iterationStageSource).toContain("<ChallengeCupIterationResultPackage");
    expect(iterationResultPackageSource).toContain("VTooltip");
    expect(iterationResultPackageSource).not.toContain('tone="success"');
  });

  it("places the current stage Agent configuration cards beside the operation surface", () => {
    const markup = renderWorkspace({
      initialStage: "experiment",
      agentConfiguration: (stage) => <div data-testid="challenge-agent-slot">{stage} Agent 配置</div>,
    });

    expect(markup).toContain('data-testid="challenge-agent-slot"');
    expect(markup).toContain("experiment Agent 配置");
    expect(componentSource).toContain("platform-stage-agent-configuration");
    expect(componentSource).toContain("agentConfiguration(activeStage)");
  });

  it("routes challenge status chrome through VUI while preserving the approved workspace layout", () => {
    expect(componentSource).toContain("VStatusChip");
    expect(componentSource).toContain("VRouteLinkButton");
    expect(componentSource).toContain("vuiStatusTone");
    expect(componentSource).not.toContain('<Link className={cx("button"');
    expect(componentSource).not.toContain('<Link className={cx("text-button")');
    expect(componentSource).not.toContain(
      '<Link\n                      className={cx("button", "secondary")}',
    );
    expect(componentSource).not.toContain('<section className={cx("platform-empty-state")}');
    expect(componentSource).not.toContain('<div className={cx("platform-empty-state")}');
    expect(componentSource).not.toContain('cx("status-pill", stageState(activeStage).tone)');
    expect(componentSource).not.toContain('cx("status-icon", question.machinePassed');
    expect(componentStyles).not.toContain(".status-icon.success");
    expect(componentStyles).not.toContain(".status-pill.warning");
    expect(componentStyles).not.toContain(".badge.success");
  });

  it("uses compact VUI states while loading or unavailable", () => {
    const loadingMarkup = renderWorkspace({ projection: undefined, isLoading: true });
    const unavailableMarkup = renderWorkspace({ projection: undefined, isUnavailable: true });

    expect(loadingMarkup).toContain('data-testid="challenge-cup-platform-loading"');
    expect(loadingMarkup).toContain("skeleton-panel");
    expect(unavailableMarkup).toContain("科研工作台数据暂不可用");
    expect(unavailableMarkup).not.toContain("实验设计");
  });

  it("removes the retired progress-screen contract instead of retaining a hidden fallback", () => {
    expect(componentSource).not.toContain('surface?: "workspace" | "progress"');
    expect(componentSource).not.toContain("挑战杯 MVP 总览");
    expect(componentSource).not.toContain("125 题批处理与 3 个代表性深研案例");
  });

  it("keeps production styling responsive, theme-aware, and scoped to the workspace", () => {
    expect(componentSource).toContain('data-testid="challenge-cup-platform-workspace"');
    expect(componentStyles).toContain(".workspace");
    expect(componentStyles).toContain("min-width: 0");
    expect(componentStyles).not.toContain("color-scheme: light");
    expect(componentStyles).toContain("--bg: var(--vui-surface-workspace)");
    expect(componentStyles).toContain("--panel: var(--vui-surface-panel)");
    expect(componentStyles).toContain("--text: var(--fg-primary)");
    expect(componentStyles).not.toContain("min-width: 860px");
    expect(componentStyles).toContain("container-type: inline-size");
    expect(componentStyles).toContain("@container challenge-workspace (max-width: 1080px)");
    expect(componentStyles).toContain("@container challenge-workspace (max-width: 760px)");
    expect(componentStyles).toContain("@container challenge-workspace (min-width: 1600px)");
    expect(componentStyles).toContain(".platform-console");
    expect(componentStyles).toContain("grid-template-columns: 220px minmax(0, 1fr)");
    expect(componentStyles).toContain(".platform-project-header");
    expect(componentStyles).toContain(".platform-canvas");
    expect(componentStyles).toContain("width: 100%");
    expect(componentStyles).toContain("max-width: none");
    expect(componentStyles).not.toContain(".platform-grid");
    expect(componentStyles).not.toContain(".platform-inspector");
    expect(componentStyles).not.toContain(".program-header");
    expect(componentStyles).not.toContain("@media (max-width: 760px)");
    expect(componentStyles).not.toContain("@media (max-width: 430px)");
  });
});
