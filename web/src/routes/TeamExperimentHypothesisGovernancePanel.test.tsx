import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type {
  ExperimentHypothesisCandidateSummary,
  ExperimentPlanRecord,
} from "./teams/experimentLoopModel";
import {
  TeamExperimentHypothesisGovernancePanel,
  createEngineeringProxyHypothesisDraft,
} from "./TeamExperimentHypothesisGovernancePanel";
import panelSource from "./TeamExperimentHypothesisGovernancePanel.tsx?raw";

const activePlan = {
  planId: "exp-plan-proxy-v2",
  stageRoundId: "round-experiment",
  status: "draft",
  title: "SCI-098 proxy design",
  topic: "sleep hypothesis proxy workflow",
  goal: "Validate the bounded engineering workflow.",
  selectedHypotheses: [],
  hypothesisCandidateIds: [],
  experimentContract: {
    schemaVersion: 2,
    planId: "exp-plan-proxy-v2",
    revision: 2,
    teamId: "research-team",
    researchProfileId: "generic-research",
    researchMode: "hypothesis_and_plan",
    purpose: { primaryPurpose: "feasibility", secondaryPurposes: [] },
    experimentMethod: "model_training_inference",
    adapterSelection: {
      requestedAdapterId: "",
      resolvedAdapterId: "",
      resolvedAdapterVersion: "",
      selectionSource: "unresolved",
      unavailableReason: "",
    },
    researchQuestion: "Can the bounded reconstruction workflow beat its fixed baseline?",
    objective: "Validate the proxy workflow only.",
    hypothesisRefs: [],
    evidenceRefs: [],
    constraints: [],
    methodConfig: {
      dataset: "synthetic_structured_8x8_proxy",
      model: "iterative_visible_residual_correction",
      baseline: "one_shot_pca_reconstruction",
      seeds: [42],
      budget: "CPU-only",
      smokePlan: "predictive_coding_reconstruction_proxy; seed=42",
    },
    metricContract: {
      primaryMetric: "reconstruction_mse_delta",
      metrics: [{ name: "reconstruction_mse_delta", direction: "maximize" }],
    },
    decisionContract: {
      successCriteria: ["delta exceeds 0.001"],
      failureCriteria: ["delta is not positive"],
      inconclusiveCriteria: ["runner unavailable"],
    },
    artifactContract: {},
    reproducibilityContract: {},
    iterationContract: {},
    supersedesPlanId: "",
    status: "draft",
  },
  contractValidation: {
    valid: true,
    errors: [],
    missingFields: [],
    methodId: "model_training_inference",
    adapterAvailable: false,
    readyForExecution: false,
    adapterUnavailableReason: "",
  },
  designGate: {
    status: "draft",
    requiresExplicitFreeze: true,
    source: "native_v2_plan",
    sourceLoopId: "",
    sourceDecisionId: "",
    sourceProposalId: "",
    frozenAt: "",
    frozenByAgent: "",
  },
  experimentPlan: {
    dataset: "synthetic_structured_8x8_proxy",
    metric: "reconstruction_mse_delta",
    baseline: "one_shot_pca_reconstruction",
    smokePlan: "predictive_coding_reconstruction_proxy; seed=42",
  },
  baselineSelection: {
    baseline: "one_shot_pca_reconstruction",
    status: "missing",
    activeBaselineReady: false,
    reason: "baseline artifact missing",
  },
  readinessChecklist: [],
  readiness: {
    readyForPlanReview: false,
    readyForSmoke: false,
    readyForFullRun: false,
    blockers: ["algorithm_hypothesis"],
  },
  updatedAt: "2026-07-30T00:00:00Z",
} satisfies ExperimentPlanRecord;

const scientificCandidate = {
  candidateId: "H1",
  title: "Sleep homeostasis hypothesis",
  summary: "Scientific candidate awaiting evidence repair.",
  currentState: "hypothesis_needs_revision",
  qualityStatus: "needs_revision",
  valid: false,
  validationIssueCount: 3,
  hypothesis: "Sleep may restore synaptic homeostasis.",
  hypothesisKind: "scientific",
  sourcePlanId: "",
  researchProjectId: "",
  claimBoundary: "",
  reviewDecision: "unreviewed",
  reviewRecordId: "",
  reviewedAt: "",
  approvedForExperiment: false,
  baseline: "",
  expectedBenefit: "",
  expectedComputeCost: "",
  experimentPlan: { dataset: "", metric: "", baseline: "", smokePlan: "" },
  missingExperimentPlanFields: ["dataset", "metric", "baseline", "smokePlan"],
  sourceRefs: [],
  evidenceRefs: [],
  updatedAt: "2026-07-30T00:00:00Z",
} satisfies ExperimentHypothesisCandidateSummary;

const proxyCandidate = {
  ...scientificCandidate,
  candidateId: "H-MVP",
  title: "工程代理假设",
  summary: "Bounded proxy candidate.",
  currentState: "hypothesis_review_ready",
  qualityStatus: "needs_review",
  valid: true,
  validationIssueCount: 0,
  hypothesis: "The bounded reconstruction workflow beats its fixed baseline.",
  hypothesisKind: "engineering_proxy",
  sourcePlanId: activePlan.planId,
  claimBoundary: "仅验证实验编排、复现与门禁链路；不支持睡眠、生物神经机制或临床结论。",
  experimentPlan: activePlan.experimentPlan,
  missingExperimentPlanFields: [],
} satisfies ExperimentHypothesisCandidateSummary;

describe("TeamExperimentHypothesisGovernancePanel", () => {
  it("keeps scientific candidates pending and exposes the proxy review boundary", () => {
    const markup = renderToStaticMarkup(
      <TeamExperimentHypothesisGovernancePanel
        lang="zh"
        activePlan={activePlan}
        hypotheses={[scientificCandidate, proxyCandidate]}
        materializing={false}
        reviewingCandidateId=""
        revisingCandidateId=""
        onMaterialize={() => undefined}
        onReview={() => undefined}
        onCreateRevision={() => undefined}
      />,
    );

    expect(markup).toContain("Sleep homeostasis hypothesis");
    expect(markup).toContain("需修订");
    expect(markup).toContain("工程代理假设");
    expect(markup).toContain("待人工审核");
    expect(markup).toContain("仅验证实验编排、复现与门禁链路");
    expect(markup).toContain("人工批准用于设计");
    expect(markup).toContain("不自动批准");
    expect(panelSource).toContain("candidate.approvedForExperiment");
  });

  it("derives a bounded default draft from the active experiment contract", () => {
    const draft = createEngineeringProxyHypothesisDraft(activePlan);

    expect(draft.hypothesis).toContain("reconstruction_mse_delta");
    expect(draft.hypothesis).toContain("one_shot_pca_reconstruction");
    expect(draft.claimBoundary).toContain("不支持");
    expect(draft.claimBoundary).toContain("科学");
  });

  it("still offers a proxy draft when the legacy plan only references scientific candidates", () => {
    const markup = renderToStaticMarkup(
      <TeamExperimentHypothesisGovernancePanel
        lang="zh"
        activePlan={{
          ...activePlan,
          hypothesisCandidateIds: [scientificCandidate.candidateId],
        }}
        hypotheses={[scientificCandidate]}
        materializing={false}
        reviewingCandidateId=""
        revisingCandidateId=""
        onMaterialize={() => undefined}
        onReview={() => undefined}
        onCreateRevision={() => undefined}
      />,
    );

    expect(markup).toContain("生成工程代理候选");
    expect(markup).toContain("Sleep homeostasis hypothesis");
  });

  it("offers a new revision only after explicit approval", () => {
    const markup = renderToStaticMarkup(
      <TeamExperimentHypothesisGovernancePanel
        lang="zh"
        activePlan={activePlan}
        hypotheses={[
          {
            ...proxyCandidate,
            reviewDecision: "approve",
            reviewRecordId: "candidate-review-1",
            reviewedAt: "2026-07-30T01:00:00Z",
            approvedForExperiment: true,
          },
        ]}
        materializing={false}
        reviewingCandidateId=""
        revisingCandidateId=""
        onMaterialize={() => undefined}
        onReview={() => undefined}
        onCreateRevision={() => undefined}
      />,
    );

    expect(markup).toContain("已人工批准");
    expect(markup).toContain("创建新设计修订");
    expect(markup).toContain("不会自动冻结");
  });
});
