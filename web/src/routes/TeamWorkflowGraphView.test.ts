import { describe, expect, it } from "vitest";

import { workflowGraphEdgePath, workflowGraphLayout } from "./TeamWorkflowGraphView";
import type { TeamWorkflowCandidateGraphPayload } from "../api/types";

const sampleGraph = {
  nodes: [
    { candidateId: "a", title: "A", candidateType: "paper_note", currentState: "ready", valid: true, qualityStatus: "ready", requiresReview: false, currentWorkflowNode: "n1" },
    { candidateId: "b", title: "B", candidateType: "paper_note", currentState: "ready", valid: true, qualityStatus: "ready", requiresReview: false, currentWorkflowNode: "n2" },
    { candidateId: "c", title: "C", candidateType: "algorithm_hypothesis", currentState: "ready", valid: true, qualityStatus: "ready", requiresReview: false, currentWorkflowNode: "n3" },
  ],
  edges: [
    { sourceCandidateId: "a", targetCandidateId: "b", relation: "related_to" },
    { sourceCandidateId: "b", targetCandidateId: "c", relation: "inspired_by_mapping" },
  ],
  summary: { nodeCount: 3, edgeCount: 2 },
} as unknown as TeamWorkflowCandidateGraphPayload;

describe("TeamWorkflowGraphView geometry", () => {
  it("fans edge control points so parallel strokes do not collapse", () => {
    const layout = workflowGraphLayout(sampleGraph);
    const path0 = workflowGraphEdgePath(sampleGraph.edges[0], layout.nodes, 0);
    const path1 = workflowGraphEdgePath(sampleGraph.edges[0], layout.nodes, 4);
    expect(path0).toBeTruthy();
    expect(path1).toBeTruthy();
    expect(path0).not.toEqual(path1);
    expect(path0).toContain("Q ");
  });

  it("returns null when an endpoint is missing from layout", () => {
    const layout = workflowGraphLayout(sampleGraph);
    expect(workflowGraphEdgePath(
      { sourceCandidateId: "missing", targetCandidateId: "b", relation: "related_to" } as any,
      layout.nodes,
      0,
    )).toBeNull();
  });
});
