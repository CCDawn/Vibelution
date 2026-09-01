import { describe, expect, it } from "vitest";

import type { ResearchWorkflowSnapshot } from "../../../api/types/research-workflow/core";
import {
  snapshotToCanvasProjection,
  snapshotToRunRecord,
} from "./researchWorkflowSnapshotProjection";

const snapshot: ResearchWorkflowSnapshot = {
  run: {
    runId: "run-1",
    teamId: "research-team",
    workflowId: "challenge-cup-research",
    workflowVersionId: "challenge-cup-research-v2.1.0",
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
  stageOne: {
    authority: "challenge_program",
    completionState: "pending",
    formalTopology: {
      workflowId: "challenge-cup-research",
      workflowVersionId: "challenge-cup-research-v2.1.0",
      definitionResolution: "pinned",
      role: "execution_authority",
    },
    hypothesisView: { nodePrefix: "hf_", role: "operator_projection" },
    knowledgeFlow: {
      topology: "embedded",
      rolloutMode: "off",
      role: "formal_graph_nodes",
    },
  },
};

describe("researchWorkflowSnapshotProjection", () => {
  it("copies frozen Agent bindings onto canvas nodeRuns and the run record", () => {
    const projection = snapshotToCanvasProjection(snapshot);
    expect(projection.run.nodeRuns.source_finding.primaryAgentId).toBe("agent-finder");
    expect(projection.stageOne).toBe(snapshot.stageOne);
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
