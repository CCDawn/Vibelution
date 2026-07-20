import { describe, expect, it } from "vitest";

import {
  EXPERIMENT_SMOKE_RESULT_STATUSES,
  RESEARCH_LOOP_DECISION_VALUES,
  experimentPlanningStatusQueryKey,
  researchDiagnosticStatusLabel,
  researchIterationLifecycleStatusLabel,
  researchLoopStatusQueryKey,
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
    expect(researchDiagnosticStatusLabel("smoke_passed", "zh")).toContain("Smoke");
    expect(researchDiagnosticStatusLabel("", "en")).toBe("none");
  });

  it("exposes smoke and decision enum lists for draft selects", () => {
    expect(EXPERIMENT_SMOKE_RESULT_STATUSES).toContain("needs_review");
    expect(RESEARCH_LOOP_DECISION_VALUES).toContain("promote_to_iteration");
  });
});
