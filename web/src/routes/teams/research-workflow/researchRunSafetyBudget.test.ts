import { describe, expect, it } from "vitest";

import {
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

describe("research run safety budget", () => {
  it("defaults to a roomy phase safety limit instead of an Agent quota", () => {
    const budget = createResearchRunSafetyBudget();

    expect(budget.stageTokens).toEqual({
      knowledge_collection: 250000,
      experiment_design: 250000,
      execution_iteration: 250000,
    });
    expect(totalResearchRunSafetyTokens(budget)).toBe(750000);
    expect(budget).toMatchObject({ toolCalls: 300, wallClockSeconds: 21600, maxRetries: 2 });
  });

  it("writes explicit per-stage ledgers while preserving non-safety run controls", () => {
    const contractJson = writeResearchRunSafetyBudget(
      JSON.stringify(CONTRACT),
      createResearchRunSafetyBudget("extended"),
    );
    const policy = (JSON.parse(contractJson) as { budgetPolicy: Record<string, unknown> }).budgetPolicy;
    const stages = policy.stageBudgets as Record<string, Record<string, number>>;

    expect(policy).toMatchObject({
      tokens: 400000,
      toolCalls: 480,
      wallClockSeconds: 28800,
      maxRetries: 2,
      experiments: 12,
      computeUnits: 100,
      maxParallelTasks: 3,
    });
    expect(stages.knowledge_collection).toMatchObject({ tokens: 400000, toolCalls: 480, wallClockSeconds: 28800 });
    expect(stages.experiment_design).toMatchObject({ tokens: 400000, toolCalls: 480, wallClockSeconds: 28800 });
    expect(stages.execution_iteration).toMatchObject({ tokens: 400000, toolCalls: 480, wallClockSeconds: 28800 });
  });

  it("does not silently invent a safety policy from malformed contracts", () => {
    expect(() => readResearchRunSafetyBudget("{")).toThrow("运行合同 JSON 无效");
  });
});
