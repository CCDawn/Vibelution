import { describe, expect, it } from "vitest";

import type { WorkflowLayoutInput } from "../../../product/workflow/workflowCanvasTypes";
import { boxesOverlap, layoutWorkflowCanvas } from "./workflowCanvasLayout";

function sampleGraph(): WorkflowLayoutInput {
  return {
    stages: [
      { stageId: "knowledge_collection", label: "知识搜集", nodeIds: ["a", "b"] },
      { stageId: "experiment_design", label: "实验设计", nodeIds: ["c"] },
      { stageId: "execution_iteration", label: "执行迭代", nodeIds: ["d", "decision"] },
    ],
    nodes: [
      {
        nodeId: "a",
        stageId: "knowledge_collection",
        label: "A",
        actorKind: "agent",
        visualKind: "start",
        status: "succeeded",
      },
      {
        nodeId: "b",
        stageId: "knowledge_collection",
        label: "B",
        actorKind: "human",
        visualKind: "human_gate",
        status: "waiting_human",
        isRuntimeCurrent: true,
      },
      {
        nodeId: "c",
        stageId: "experiment_design",
        label: "C",
        actorKind: "agent",
        visualKind: "agent_task",
        status: "pending",
      },
      {
        nodeId: "d",
        stageId: "execution_iteration",
        label: "D",
        actorKind: "system",
        visualKind: "system_task",
        status: "pending",
      },
      {
        nodeId: "decision",
        stageId: "execution_iteration",
        label: "决策",
        actorKind: "agent",
        visualKind: "decision",
        status: "pending",
      },
    ],
    edges: [
      {
        edgeId: "e1",
        fromNodeId: "b",
        toNodeId: "c",
        label: "handoff",
        gateKind: "human",
        semanticKind: "human_gate",
        pathState: "attention",
        labelAlwaysVisible: true,
      },
      {
        edgeId: "e_decision_rerun",
        fromNodeId: "decision",
        toNodeId: "d",
        label: "同协议重跑",
        gateKind: "auto",
        semanticKind: "rerun",
        pathState: "idle",
        labelAlwaysVisible: true,
        sourceHandle: "rerun",
      },
    ],
  };
}

describe("workflowCanvasLayout", () => {
  it("lays out three stages with task nodes parented to stage groups", () => {
    const layout = layoutWorkflowCanvas(sampleGraph());
    const stages = layout.nodes.filter((n) => n.kind === "stage");
    const tasks = layout.nodes.filter((n) => n.kind === "task");
    expect(stages).toHaveLength(3);
    expect(tasks).toHaveLength(5);
    expect(layout.edges).toHaveLength(2);
    expect(layout.width).toBeGreaterThan(900);
    for (const task of tasks) {
      expect(task.parentStageId).toMatch(/^stage:/);
      expect(task.relativeX).toBeTypeOf("number");
      expect(task.relativeY).toBeTypeOf("number");
      expect(task.stageId).toBeTruthy();
    }
  });

  it("keeps stage order and node membership stable", () => {
    const layout = layoutWorkflowCanvas(sampleGraph());
    const stageIds = layout.nodes.filter((n) => n.kind === "stage").map((n) => n.stageId);
    expect(stageIds).toEqual(["knowledge_collection", "experiment_design", "execution_iteration"]);
    const knowledgeTasks = layout.nodes.filter(
      (n) => n.kind === "task" && n.stageId === "knowledge_collection",
    );
    expect(knowledgeTasks.map((n) => n.id)).toEqual(["a", "b"]);
  });

  it("does not overlap task nodes within a stage", () => {
    const layout = layoutWorkflowCanvas(sampleGraph());
    const tasks = layout.nodes.filter((n) => n.kind === "task");
    for (let i = 0; i < tasks.length; i += 1) {
      for (let j = i + 1; j < tasks.length; j += 1) {
        if (tasks[i].stageId !== tasks[j].stageId) continue;
        expect(
          boxesOverlap(
            { x: tasks[i].relativeX ?? 0, y: tasks[i].relativeY ?? 0, width: tasks[i].width, height: tasks[i].height },
            { x: tasks[j].relativeX ?? 0, y: tasks[j].relativeY ?? 0, width: tasks[j].width, height: tasks[j].height },
          ),
        ).toBe(false);
      }
    }
  });

  it("is deterministic for the same input", () => {
    const a = layoutWorkflowCanvas(sampleGraph());
    const b = layoutWorkflowCanvas(sampleGraph());
    expect(a).toEqual(b);
  });

  it("gives decision nodes multi-handle metadata", () => {
    const layout = layoutWorkflowCanvas(sampleGraph());
    const decision = layout.nodes.find((n) => n.id === "decision");
    expect(decision?.sourceHandleIds).toEqual(["rerun", "promote", "rollback", "stop"]);
    expect(decision?.height).toBeGreaterThan(88);
  });

  it("preserves decision branch sourceHandle on edges", () => {
    const layout = layoutWorkflowCanvas(sampleGraph());
    const rerun = layout.edges.find((e) => e.id === "e_decision_rerun");
    expect(rerun?.sourceHandle).toBe("rerun");
    expect(rerun?.semanticKind).toBe("rerun");
  });
});
