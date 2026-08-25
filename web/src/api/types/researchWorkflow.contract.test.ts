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
  it("exposes seventeen fixed challenge-cup nodes", () => {
    expect(CHALLENGE_CUP_NODE_IDS).toHaveLength(17);
    expect(CHALLENGE_CUP_NODE_IDS[0]).toBe("problem_understanding");
    expect(CHALLENGE_CUP_NODE_IDS[16]).toBe("result_package");
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

  it("aligns WorkflowRunStatus with blocked for rejected human gates", () => {
    // Contract: server may project run.status = "blocked"; TS must accept it.
    const statuses: Array<import("./researchWorkflow").WorkflowRunStatus> = [
      "queued",
      "running",
      "waiting_human",
      "blocked",
      "succeeded",
      "failed",
      "cancelled",
    ];
    expect(statuses).toContain("blocked");
    expect(typeSource).toMatch(/WorkflowRunStatus[\s\S]*?\| "blocked"/);
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
        runId: "run-blocked",
        status: "blocked",
        runtimeCurrentNodeIds: ["knowledge_handoff"],
        nodeRuns: {},
        pendingHumanTasks: [],
      },
    };
    expect(sample.run.status).toBe("blocked");
  });

  it("exposes five iteration decision kinds and fork/completion fields", () => {
    const kinds: Array<import("./researchWorkflow").IterationDecisionKind> = [
      "rerun_same_protocol",
      "revise_protocol",
      "promote_candidate",
      "rollback_candidate",
      "stop",
    ];
    expect(kinds).toHaveLength(5);
    expect(typeSource).toContain("IterationDecisionKind");
    expect(typeSource).toContain("branched_revision");
    expect(typeSource).toContain("PromotionOperation");
    expect(typeSource).toContain("parentRunId");
    expect(typeSource).toContain("childRunIds");
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
        runId: "run-parent",
        status: "succeeded",
        runtimeCurrentNodeIds: [],
        nodeRuns: {
          controlled_run: {
            nodeId: "controlled_run",
            status: "succeeded",
            attempt: 2,
            nodeRunId: "nr-controlled_run-a2",
          },
        },
        pendingHumanTasks: [],
        completionKind: "branched_revision",
        childRunIds: ["run-child"],
        blockedReason: null,
        iterationBudgetMax: 3,
      },
    };
    expect(sample.run.completionKind).toBe("branched_revision");
    expect(sample.run.childRunIds).toEqual(["run-child"]);
    expect(sample.run.nodeRuns.controlled_run.attempt).toBe(2);
  });
});
