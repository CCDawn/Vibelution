import { describe, expect, it } from "vitest";

import type { WorkflowRunRecord } from "../../../api/researchWorkflow";
import { buildResearchRunOptions, researchRunStatusLabel } from "./researchRunPresentation";

function run(overrides: Partial<WorkflowRunRecord>): WorkflowRunRecord {
  return {
    runId: "run-internal-id",
    workflowId: "challenge-cup-research",
    workflowVersionId: "v1",
    teamId: "team-1",
    projectId: "project-1",
    questionId: "question-1",
    runVersion: 1,
    status: "running",
    ...overrides,
  };
}

describe("research run presentation", () => {
  it("uses user-facing ordinal, node and Chinese state without exposing the run id", () => {
    const [option] = buildResearchRunOptions([
      run({
        runId: "run-5e4fbe6e18f2",
        status: "blocked",
        runtimeCurrentNodeIds: ["source_finding"],
        createdAt: "2026-08-10T03:12:00Z",
      }),
    ]);

    expect(option.runId).toBe("run-5e4fbe6e18f2");
    expect(option.label).toContain("第 1 次运行");
    expect(option.label).toContain("资料寻找");
    expect(option.label).toContain("等待处理");
    expect(option.label).not.toContain("run-");
    expect(option.label).not.toContain("blocked");
  });

  it("orders newest runs first while preserving a stable chronological number", () => {
    const options = buildResearchRunOptions([
      run({ runId: "run-old", createdAt: "2026-08-09T03:12:00Z", status: "cancelled" }),
      run({ runId: "run-new", createdAt: "2026-08-10T03:12:00Z", status: "succeeded" }),
    ]);

    expect(options.map((option) => option.runId)).toEqual(["run-new", "run-old"]);
    expect(options[0].label).toContain("第 2 次运行");
    expect(options[0].label).toContain("已完成");
    expect(options[1].label).toContain("第 1 次运行");
    expect(options[1].label).toContain("已取消");
  });

  it("does not leak an unknown backend enum", () => {
    expect(researchRunStatusLabel("future_internal_state")).toBe("状态待确认");
  });
});
