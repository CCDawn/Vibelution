import { describe, expect, it } from "vitest";

import {
  buildResearchRunInput,
  type ResearchRunLaunchDraft,
} from "./researchRunLaunchContract";

const CONTRACT = {
  metricContract: { primary: "score" },
  constraintSnapshot: { offline: true },
  trackAndRubricSnapshot: { track: "challenge-cup" },
  researchObjectiveContract: { question: "q" },
  sourcePolicy: { minimumPrimarySources: 3 },
  budgetPolicy: { toolCalls: 20 },
  stopPolicy: { maxNoImprovementRounds: 2 },
  modelRoutingPolicy: {
    source_discovery: "model-a",
    extraction: "model-a",
    reasoning: "model-a",
    review: "model-a",
    governance: "model-a",
  },
  evaluationContract: { requiredSeeds: [11, 29, 47] },
};

function draft(overrides: Partial<ResearchRunLaunchDraft> = {}): ResearchRunLaunchDraft {
  return {
    questionId: "question-1",
    researchBriefHash: "sha256:brief",
    datasetRefs: "dataset:a\ndataset:b, dataset:c",
    competitionRuleRef: "rules/challenge-cup-2026",
    competitionRuleVersion: "2026.1",
    environmentSnapshotRef: "env:2026-08-09",
    contractJson: JSON.stringify(CONTRACT),
    ...overrides,
  };
}

describe("buildResearchRunInput", () => {
  it("builds the complete immutable run contract with canonical teamId", () => {
    const input = buildResearchRunInput({
      teamId: " team-1 ",
      projectId: " project-1 ",
      draft: draft(),
    });
    expect(input).toMatchObject({
      teamId: "team-1",
      projectId: "project-1",
      questionId: "question-1",
      researchBriefHash: "sha256:brief",
      datasetRefs: ["dataset:a", "dataset:b", "dataset:c"],
      competitionRuleRef: "rules/challenge-cup-2026",
      competitionRuleVersion: "2026.1",
      environmentSnapshotRef: "env:2026-08-09",
      ...CONTRACT,
    });
    expect(input.idempotencyKey).toMatch(/^create:v2:[0-9a-f]{16}$/);
  });

  it("keeps retries stable but distinguishes changed run contracts", () => {
    const base = buildResearchRunInput({
      teamId: "team-1",
      projectId: "project-1",
      draft: draft(),
    });
    const retry = buildResearchRunInput({
      teamId: "team-1",
      projectId: "project-1",
      draft: draft(),
    });
    const changedBudget = buildResearchRunInput({
      teamId: "team-1",
      projectId: "project-1",
      draft: draft({
        contractJson: JSON.stringify({
          ...CONTRACT,
          budgetPolicy: { toolCalls: 120 },
        }),
      }),
    });

    expect(retry.idempotencyKey).toBe(base.idempotencyKey);
    expect(changedBudget.idempotencyKey).not.toBe(base.idempotencyKey);
  });

  it.each([
    ["teamId", { teamId: "", projectId: "project-1", draft: draft() }],
    ["projectId", { teamId: "team-1", projectId: "", draft: draft() }],
    ["questionId", { teamId: "team-1", projectId: "project-1", draft: draft({ questionId: "" }) }],
  ])("rejects a missing %s instead of inventing a fallback", (field, options) => {
    expect(() => buildResearchRunInput(options)).toThrow(`${field} 不能为空`);
  });

  it("rejects malformed and incomplete run contracts", () => {
    expect(() =>
      buildResearchRunInput({
        teamId: "team-1",
        projectId: "project-1",
        draft: draft({ contractJson: "{" }),
      }),
    ).toThrow("运行合同 JSON 无效");

    expect(() =>
      buildResearchRunInput({
        teamId: "team-1",
        projectId: "project-1",
        draft: draft({ contractJson: JSON.stringify({ ...CONTRACT, budgetPolicy: null }) }),
      }),
    ).toThrow("运行合同缺少 budgetPolicy");

    expect(() =>
      buildResearchRunInput({
        teamId: "team-1",
        projectId: "project-1",
        draft: draft({
          contractJson: JSON.stringify({
            ...CONTRACT,
            modelRoutingPolicy: { ...CONTRACT.modelRoutingPolicy, source_discovery: "" },
          }),
        }),
      }),
    ).toThrow("运行合同缺少 modelRoutingPolicy.source_discovery");
  });
});
