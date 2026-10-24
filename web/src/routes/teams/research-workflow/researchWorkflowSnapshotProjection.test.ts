import { describe, expect, it } from "vitest";

import type { ResearchWorkflowSnapshot } from "../../../api/types/research-workflow/core";
import { projectionToCanvasGraph } from "./researchProcessGraphModel";
import {
  snapshotToCanvasProjection,
  snapshotToRunRecord,
} from "./researchWorkflowSnapshotProjection";

const snapshot: ResearchWorkflowSnapshot = {
  run: {
    runId: "run-1",
    teamId: "research-team",
    workflowId: "challenge-cup-research",
    workflowVersionId: "challenge-cup-research@3.0.0",
    threadId: "thread-1",
    projectId: "challenge-sci-096",
    questionId: "SCI-096",
    status: "running",
    runVersion: 2,
    inputSnapshotHash: "a".repeat(64),
    bindingSnapshotSetId: "binding-set-1",
    activeNodeId: "source_finding",
    parentRunId: null,
    forkedFromCheckpointId: null,
    completionKind: null,
    terminalReason: null,
    createdAtMs: 1,
    updatedAtMs: 1,
    completedAtMs: null,
  },
  definition: { workflowId: "challenge-cup-research" },
  nodeAttempts: {
    source_finding: [
      {
        nodeRunId: "nr-1",
        nodeId: "source_finding",
        attempt: 1,
        actorKind: "agent",
        status: "starting",
        commandId: "cmd-1",
        bindingSnapshotId: "snap:run-1:source_finding",
        inputSnapshotHash: "a".repeat(64),
        executionAnchorId: null,
        startedAtMs: 1,
        updatedAtMs: 1,
        finishedAtMs: null,
      },
    ],
  },
  activeNodeIds: ["source_finding"],
  pendingHumanTasks: [],
  commandOffers: [],
  handoffSummary: { countsByStatus: {}, refs: [], count: 0 },
  agentBindingSummary: {
    bindingSnapshotSetId: "binding-set-1",
    bindingSnapshotIds: ["snap:run-1:source_finding"],
    count: 1,
    bindings: [
      {
        nodeId: "source_finding",
        agentId: "agent-finder",
        roleKey: "source_finder",
        resolvedFrom: "workflow_default",
        snapshotId: "snap:run-1:source_finding",
      },
    ],
  },
  budgetSummary: { safetyLimits: {}, receiptRefs: [], receiptCount: 0 },
  latestEventSequence: 3,
  generatedAt: "2026-08-12T14:00:00.000Z",
};

describe("researchWorkflowSnapshotProjection", () => {
  it.each(["starting", "dispatching"])("keeps a %s attempt active on the canvas", (status) => {
    const formal: ResearchWorkflowSnapshot = {
      ...snapshot,
      definition: {
        nodes: [{ nodeId: "source_finding", actorKind: "agent", label: "资料寻找", stageId: "knowledge_collection" }],
        stages: [{ stageId: "knowledge_collection", nodeIds: ["source_finding"], index: 0, label: "资料搜集" }],
        edges: [],
      },
      nodeAttempts: {
        source_finding: [{ ...snapshot.nodeAttempts.source_finding[0], status }],
      },
    };
    const projection = snapshotToCanvasProjection(formal);
    const graph = projectionToCanvasGraph(projection);

    expect(projection.formalSnapshot.nodeAttempts.source_finding[0].status).toBe(status);
    expect(graph.nodes[0]).toMatchObject({ status: "running", isRuntimeCurrent: true });
    expect(graph.stages[0].stageTone).toBe("active");
  });

  it("copies frozen Agent bindings onto canvas nodeRuns and the run record", () => {
    const projection = snapshotToCanvasProjection(snapshot);
    expect(projection.run.nodeRuns.source_finding.primaryAgentId).toBe("agent-finder");
    const record = snapshotToRunRecord(snapshot, []);
    expect(record.bindingSnapshots).toEqual([
      {
        nodeId: "source_finding",
        agentId: "agent-finder",
        roleKey: "source_finder",
        resolvedFrom: "workflow_default",
        snapshotId: "snap:run-1:source_finding",
      },
    ]);
  });
});
