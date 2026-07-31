import { describe, expect, it } from "vitest";

import {
  buildBoundedSmokeEvidenceDraft,
  mergeBoundedSmokeEvidenceDraft,
} from "./TeamResearchLoopPanel";
import type {
  ExperimentPlanRecord,
  ResearchLoopEvidenceDraft,
} from "./teams/experimentLoopModel";

function planWithSmoke(): ExperimentPlanRecord {
  return {
    planId: "plan-sci-098",
    stageRoundId: "round-sci-098",
    status: "smoke_needs_review",
    title: "SCI-098",
    topic: "Why do we need sleep?",
    goal: "Validate the bounded workflow.",
    selectedHypotheses: [],
    hypothesisCandidateIds: [],
    experimentPlan: {
      dataset: "synthetic_structured_8x8_proxy",
      metric: "reconstruction_mse_delta",
      baseline: "one_shot_pca_reconstruction",
      smokePlan: "predictive_coding_reconstruction_proxy",
    },
    baselineSelection: {
      baseline: "one_shot_pca_reconstruction",
      status: "missing",
      activeBaselineReady: false,
      reason: "",
    },
    activeSmokeRunId: "smokerun-sci-098",
    activeSmokeRun: {
      smokeRunId: "smokerun-sci-098",
      adapter: "predictive_coding_reconstruction_proxy",
      seed: 42,
      runnerMode: "v1_cpu_smoke",
      status: "needs_review",
      decisionHint: "accept",
      metrics: {
        baseline: { reconstruction_mse: 0.025838 },
        variant: { reconstruction_mse: 0.007935 },
        delta: { mse_improvement: 0.017903 },
      },
      artifactHash: "sha256:artifact",
      logs: "bounded log",
      proxyOnly: true,
      boundaries: ["does_not_validate_neural_realism"],
      recordedByAgent: "agent-experiment",
      recordedAt: "2026-08-01T02:28:17+08:00",
    },
    readinessChecklist: [],
    readiness: {
      readyForPlanReview: true,
      readyForSmoke: true,
      readyForFullRun: false,
      blockers: [],
    },
    updatedAt: "2026-08-01T02:28:17+08:00",
  };
}

describe("bounded Smoke iteration evidence prefill", () => {
  it("prefills the review form with the real run evidence and proxy boundary", () => {
    const draft = buildBoundedSmokeEvidenceDraft(planWithSmoke(), "zh");

    expect(draft).toMatchObject({
      evidenceType: "metric_report",
      status: "needs_review",
      metricName: "reconstruction_mse_delta",
      metricValue: "0.017903",
      baselineMetricValue: "0.025838",
      delta: "0.017903",
      artifactRef: "sha256:artifact",
      datasetRefs: "synthetic_structured_8x8_proxy",
      environmentRefs: "v1_cpu_smoke, seed=42, proxy-only",
      logRefs: "smokerun-sci-098",
      commandPreview: "predictive_coding_reconstruction_proxy",
    });
    expect(draft?.summary).toContain("不得据此声称睡眠机制或神经真实性");
  });

  it("does not fabricate evidence when no bounded Smoke exists", () => {
    const plan = planWithSmoke();
    delete plan.activeSmokeRun;
    delete plan.activeSmokeRunId;

    expect(buildBoundedSmokeEvidenceDraft(plan, "zh")).toBeNull();
  });

  it("fills a system-seeded empty draft but preserves actual user review input", () => {
    const prefill = buildBoundedSmokeEvidenceDraft(planWithSmoke(), "zh");
    expect(prefill).not.toBeNull();
    const systemSeededDraft: ResearchLoopEvidenceDraft = {
      evidenceType: "baseline_artifact",
      status: "needs_review",
      summary: "",
      metricName: "reconstruction_mse_delta",
      metricValue: "",
      baselineMetricValue: "",
      delta: "",
      artifactRef: "",
      datasetRefs: "",
      environmentRefs: "",
      logRefs: "",
      commandPreview: "",
    };
    expect(mergeBoundedSmokeEvidenceDraft(systemSeededDraft, prefill!)).toBe(prefill);

    const userDraft = { ...systemSeededDraft, summary: "人工复核备注" };
    expect(mergeBoundedSmokeEvidenceDraft(userDraft, prefill!)).toBe(userDraft);
  });
});
