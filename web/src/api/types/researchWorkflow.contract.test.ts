import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import {
  CHALLENGE_CUP_NODE_IDS,
  CHALLENGE_CUP_WORKFLOW_ID,
  type WorkflowCanvasProjection,
} from "./researchWorkflow";

const typeSource = readFileSync(resolve(import.meta.dirname, "researchWorkflow.ts"), "utf8");

describe("researchWorkflow TS domain contract (Task 1)", () => {
  it("exposes fifteen fixed challenge-cup nodes", () => {
    expect(CHALLENGE_CUP_NODE_IDS).toHaveLength(15);
    expect(CHALLENGE_CUP_NODE_IDS[0]).toBe("source_finding");
    expect(CHALLENGE_CUP_NODE_IDS[14]).toBe("result_package");
    expect(CHALLENGE_CUP_WORKFLOW_ID).toBe("challenge-cup-research");
  });

  it("documents selectedNodeId as UI-only (not on server projection type text)", () => {
    expect(typeSource).toContain("never includes selectedNodeId");
    expect(typeSource).not.toMatch(/selectedNodeId\s*:/);
    const sample: WorkflowCanvasProjection = {
      definition: {
        workflowId: CHALLENGE_CUP_WORKFLOW_ID,
        schemaVersion: "1.0.0",
        label: "挑战杯科研流程",
        structureHash: "x",
        stages: [],
        nodes: [],
        edges: [],
      },
      run: {
        runId: null,
        status: null,
        runtimeCurrentNodeIds: [],
        nodeRuns: {},
        pendingHumanTasks: [],
      },
    };
    expect(sample.run).not.toHaveProperty("selectedNodeId");
  });

  it("includes handoff and session binding DTO names", () => {
    expect(typeSource).toContain("NodeHandoffRecord");
    expect(typeSource).toContain("NodeAgentSessionBinding");
    expect(typeSource).toContain("RunAgentBindingSnapshot");
    expect(typeSource).toContain("runtimeCurrentNodeIds");
  });
});
