import { describe, expect, it } from "vitest";

import { layoutWorkflowCanvas } from "./workflowCanvasLayout";

describe("workflowCanvasLayout", () => {
  it("lays out three stages with task nodes and edges", () => {
    const layout = layoutWorkflowCanvas({
      stages: [
        { stageId: "knowledge_collection", label: "知识搜集", nodeIds: ["a", "b"] },
        { stageId: "experiment_design", label: "实验设计", nodeIds: ["c"] },
        { stageId: "execution_iteration", label: "执行迭代", nodeIds: ["d"] },
      ],
      nodes: [
        { nodeId: "a", stageId: "knowledge_collection", label: "A", actorKind: "agent" },
        { nodeId: "b", stageId: "knowledge_collection", label: "B", actorKind: "human" },
        { nodeId: "c", stageId: "experiment_design", label: "C", actorKind: "agent" },
        { nodeId: "d", stageId: "execution_iteration", label: "D", actorKind: "system" },
      ],
      edges: [{ edgeId: "e1", fromNodeId: "b", toNodeId: "c", label: "handoff" }],
    });
    expect(layout.nodes.filter((n) => n.kind === "stage")).toHaveLength(3);
    expect(layout.nodes.filter((n) => n.kind === "task")).toHaveLength(4);
    expect(layout.edges).toHaveLength(1);
    expect(layout.width).toBeGreaterThan(900);
  });
});
