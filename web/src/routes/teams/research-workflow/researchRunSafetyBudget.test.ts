import { describe, expect, it } from "vitest";

import {
  RESEARCH_RUN_SAFETY_PRESETS,
  RESEARCH_RUN_SAFETY_STAGES,
  createResearchRunSafetyBudget,
  readResearchRunSafetyBudget,
  totalResearchRunSafetyTokens,
  writeResearchRunSafetyBudget,
} from "./researchRunSafetyBudget";

const CONTRACT = {
  budgetPolicy: {
    experiments: 12,
    computeUnits: 100,
    maxParallelTasks: 3,
    maxRetries: 2,
  },
  metricContract: { primary: "score" },
};

// Production observation (SCI-091 formal run): one source_finding attempt
// settled ~407K tokens with metering overrun to 460K+.  Every preset stage
// limit must stay above that scale or the stage deadlocks after the first
// real attempt settles.
const OBSERVED_MAX_ATTEMPT_TOKENS = 460000;
const CALIBRATION_FLOOR_TOKENS = 800000;

describe("research run safety budget", () => {
  it("defaults to a roomy phase safety limit instead of an Agent quota", () => {
    const budget = createResearchRunSafetyBudget();

    expect(budget.stageTokens).toEqual({
      knowledge_collection: 1000000,
      experiment_design: 1000000,
      execution_iteration: 1000000,
    });
    expect(totalResearchRunSafetyTokens(budget)).toBe(3000000);
    expect(budget).toMatchObject({ toolCalls: 300, wallClockSeconds: 21600, maxRetries: 2 });
  });

  it("calibrates every preset stage above the observed worst single attempt", () => {
    for (const presetId of Object.keys(RESEARCH_RUN_SAFETY_PRESETS) as Array<keyof typeof RESEARCH_RUN_SAFETY_PRESETS>) {
      const preset = RESEARCH_RUN_SAFETY_PRESETS[presetId];
      expect(preset.tokens).toBeGreaterThanOrEqual(CALIBRATION_FLOOR_TOKENS);
      expect(preset.tokens).toBeGreaterThan(OBSERVED_MAX_ATTEMPT_TOKENS);
      const budget = createResearchRunSafetyBudget(presetId);
      for (const stageId of RESEARCH_RUN_SAFETY_STAGES) {
        expect(budget.stageTokens[stageId]).toBe(preset.tokens);
      }
    }
  });

  it("writes explicit per-stage ledgers while preserving non-safety run controls", () => {
    const contractJson = writeResearchRunSafetyBudget(
      JSON.stringify(CONTRACT),
      createResearchRunSafetyBudget("extended"),
    );
    const policy = (JSON.parse(contractJson) as { budgetPolicy: Record<string, unknown> }).budgetPolicy;
    const stages = policy.stageBudgets as Record<string, Record<string, number>>;

    expect(policy).toMatchObject({
      tokens: 1500000,
      toolCalls: 480,
      wallClockSeconds: 28800,
      maxRetries: 2,
      experiments: 12,
      computeUnits: 100,
      maxParallelTasks: 3,
    });
    expect(stages.knowledge_collection).toMatchObject({ tokens: 1500000, toolCalls: 480, wallClockSeconds: 28800 });
    expect(stages.experiment_design).toMatchObject({ tokens: 1500000, toolCalls: 480, wallClockSeconds: 28800 });
    expect(stages.execution_iteration).toMatchObject({ tokens: 1500000, toolCalls: 480, wallClockSeconds: 28800 });
  });

  it("does not silently invent a safety policy from malformed contracts", () => {
    expect(() => readResearchRunSafetyBudget("{")).toThrow("运行合同 JSON 无效");
  });
});
