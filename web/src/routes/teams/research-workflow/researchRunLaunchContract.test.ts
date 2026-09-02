import { describe, expect, it } from "vitest";

import { createResearchRunSafetyBudget } from "./researchRunSafetyBudget";
import { buildResearchRunInput } from "./researchRunLaunchContract";

describe("buildResearchRunInput", () => {
  it("submits only the selected question and operator safety ceilings", () => {
    const input = buildResearchRunInput({
      teamId: " team-1 ",
      questionId: " SCI-096 ",
      safetyBudget: createResearchRunSafetyBudget(),
    });

    expect(input).toEqual({
      teamId: "team-1",
      questionId: "SCI-096",
      safetyLimits: {
        stageTokens: {
          knowledge_collection: 1000000,
          experiment_design: 1000000,
          execution_iteration: 1000000,
        },
        toolCalls: 300,
        wallClockSeconds: 21600,
        maxRetries: 2,
      },
      idempotencyKey: expect.stringMatching(/^create:v3:[0-9a-f]{16}$/),
    });
    expect(input).not.toHaveProperty("projectId");
    expect(input).not.toHaveProperty("researchBriefHash");
    expect(input).not.toHaveProperty("modelRoutingPolicy");
  });

  it("keeps retries stable and changes identity only for an allowed safety change", () => {
    const base = buildResearchRunInput({
      teamId: "team-1",
      questionId: "SCI-096",
      safetyBudget: createResearchRunSafetyBudget(),
    });
    const retry = buildResearchRunInput({
      teamId: "team-1",
      questionId: "SCI-096",
      safetyBudget: createResearchRunSafetyBudget(),
    });
    const extended = buildResearchRunInput({
      teamId: "team-1",
      questionId: "SCI-096",
      safetyBudget: createResearchRunSafetyBudget("extended"),
    });

    expect(retry.idempotencyKey).toBe(base.idempotencyKey);
    expect(extended.idempotencyKey).not.toBe(base.idempotencyKey);
  });

  it.each([
    ["teamId", { teamId: "", questionId: "SCI-096" }],
    ["questionId", { teamId: "team-1", questionId: "" }],
  ])("rejects a missing %s", (field, values) => {
    expect(() => buildResearchRunInput({ ...values, safetyBudget: createResearchRunSafetyBudget() }))
      .toThrow(`${field} 不能为空`);
  });
});
