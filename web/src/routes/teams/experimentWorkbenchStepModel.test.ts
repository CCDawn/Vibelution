import { describe, expect, it } from "vitest";
import {
  isExperimentWorkbenchStepUnlocked,
  resolveExperimentWorkbenchStep,
  shortProtocolLabel,
} from "./experimentWorkbenchStepModel";

describe("experimentWorkbenchStepModel", () => {
  it("lands on setup until a plan exists", () => {
    expect(resolveExperimentWorkbenchStep({
      hasActivePlan: false,
      hasApprovedHypothesis: false,
      designFrozen: false,
      readyForBoundedSmoke: false,
    })).toBe("setup");
  });

  it("moves plan → review → freeze → execute", () => {
    expect(resolveExperimentWorkbenchStep({
      hasActivePlan: true,
      hasApprovedHypothesis: false,
      designFrozen: false,
      readyForBoundedSmoke: false,
    })).toBe("review");
    expect(resolveExperimentWorkbenchStep({
      hasActivePlan: true,
      hasApprovedHypothesis: true,
      designFrozen: false,
      readyForBoundedSmoke: false,
    })).toBe("protocol");
    expect(resolveExperimentWorkbenchStep({
      hasActivePlan: true,
      hasApprovedHypothesis: true,
      designFrozen: true,
      readyForBoundedSmoke: true,
    })).toBe("execute");
  });

  it("unlocks later steps only after prerequisites", () => {
    const bare = {
      hasActivePlan: false,
      hasApprovedHypothesis: false,
      designFrozen: false,
      readyForBoundedSmoke: false,
    };
    expect(isExperimentWorkbenchStepUnlocked("setup", bare)).toBe(true);
    expect(isExperimentWorkbenchStepUnlocked("review", bare)).toBe(false);
    expect(isExperimentWorkbenchStepUnlocked("execute", bare)).toBe(false);

    const withPlan = { ...bare, hasActivePlan: true };
    expect(isExperimentWorkbenchStepUnlocked("review", withPlan)).toBe(true);
    expect(isExperimentWorkbenchStepUnlocked("protocol", withPlan)).toBe(false);

    const approved = { ...withPlan, hasApprovedHypothesis: true };
    expect(isExperimentWorkbenchStepUnlocked("protocol", approved)).toBe(true);
    expect(isExperimentWorkbenchStepUnlocked("execute", approved)).toBe(false);

    const frozen = { ...approved, designFrozen: true };
    expect(isExperimentWorkbenchStepUnlocked("execute", frozen)).toBe(true);
  });

  it("shortens protocol labels for UI", () => {
    expect(shortProtocolLabel("short")).toBe("short");
    expect(shortProtocolLabel("a".repeat(50), 10).endsWith("…")).toBe(true);
    expect(shortProtocolLabel("a".repeat(50), 10).length).toBe(10);
  });
});
