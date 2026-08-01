import { describe, expect, it } from "vitest";

import {
  EXPERIMENT_SMOKE_RESULT_STATUSES,
  RESEARCH_LOOP_DECISION_VALUES,
  experimentPlanningStatusQueryKey,
  researchDiagnosticStatusLabel,
  researchIterationLifecycleStatusLabel,
  researchKnowledgeLifecycleStatusLabel,
  researchLoopEvidenceReadinessPresentation,
  researchLoopStatusQueryKey,
  selectBoundedSmokeAdapter,
} from "./experimentLoopModel";

describe("experimentLoopModel", () => {
  it("keeps stable query keys for experiment and research-loop status", () => {
    expect(experimentPlanningStatusQueryKey("team-1")).toEqual([
      "teams",
      "team-1",
      "workflow-orchestration",
      "experiments",
      "status",
    ]);
    expect(researchLoopStatusQueryKey("team-1")).toContain("research-loop");
  });

  it("labels iteration lifecycle and diagnostic statuses", () => {
    expect(researchIterationLifecycleStatusLabel("accepted_for_writeup", "zh")).toContain("晋升");
    expect(researchIterationLifecycleStatusLabel("not_started", "en")).toBe("not started");
    expect(researchIterationLifecycleStatusLabel("needs_more_evidence", "zh")).toBe("待补证据");
    expect(researchKnowledgeLifecycleStatusLabel("ready_for_hypothesis", "未开始", "zh")).toBe("已完成");
    expect(researchKnowledgeLifecycleStatusLabel("collecting", "搜集中", "zh")).toBe("搜集中");
    expect(researchDiagnosticStatusLabel("smoke_passed", "zh")).toContain("Smoke");
    expect(researchDiagnosticStatusLabel("", "en")).toBe("none");
  });

  it("exposes smoke and decision enum lists for draft selects", () => {
    expect(EXPERIMENT_SMOKE_RESULT_STATUSES).toContain("needs_review");
    expect(RESEARCH_LOOP_DECISION_VALUES).toContain("promote_to_iteration");
  });

  it("distinguishes registered evidence types from evidence awaiting review", () => {
    const presentation = researchLoopEvidenceReadinessPresentation({
      readiness: {
        requiredEvidenceTypes: ["baseline_artifact", "dataset_benchmark", "metric_report"],
        presentEvidenceTypes: ["baseline_artifact", "dataset_benchmark", "metric_report"],
        missingEvidenceTypes: [],
        evidenceRecordCount: 3,
        readyForDecision: true,
        readyForIteration: false,
        blockers: [],
      },
      evidenceRecords: [
        { status: "needs_review" },
        { status: "needs_review" },
        { status: "needs_review" },
      ] as never,
    }, "zh");

    expect(presentation.typeComplete).toBe(true);
    expect(presentation.statusLabel).toBe("3 条待复核");
    expect(presentation.gapItems).toEqual(["3 条已登记证据待人工复核"]);
  });

  it("honors the adapter declared by a legacy string smoke plan", () => {
    const adapters = [
      { adapterId: "synthetic_classification_baseline_vs_variant" },
      { adapterId: "predictive_coding_reconstruction_proxy" },
    ];

    expect(
      selectBoundedSmokeAdapter(adapters, {
        experimentContract: {
          adapterSelection: {
            requestedAdapterId: "",
            resolvedAdapterId: "",
          },
        },
        experimentPlan: {
          smokePlan: "predictive_coding_reconstruction_proxy；seed=42；successThreshold=0.001",
        },
      }),
    ).toEqual(adapters[1]);
  });

  it("does not silently replace an unavailable declared adapter", () => {
    const adapters = [
      { adapterId: "synthetic_classification_baseline_vs_variant" },
    ];

    expect(
      selectBoundedSmokeAdapter(adapters, {
        experimentContract: {
          adapterSelection: {
            requestedAdapterId: "predictive_coding_reconstruction_proxy",
            resolvedAdapterId: "",
          },
        },
        experimentPlan: {
          smokePlan: "predictive_coding_reconstruction_proxy; seed=42",
        },
      }),
    ).toBeNull();
  });
});
