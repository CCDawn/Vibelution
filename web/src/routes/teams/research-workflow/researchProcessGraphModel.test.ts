import { describe, expect, it } from "vitest";

import type { WorkflowCanvasProjection, WorkflowDefinition } from "../../../api/types/researchWorkflow";
import {
  definitionToCanvasGraph,
  mergeSelectionAndRuntime,
  projectionToCanvasGraph,
} from "./researchProcessGraphModel";

const definition: WorkflowDefinition = {
  workflowId: "challenge-cup-research",
  schemaVersion: "1",
  label: "挑战杯",
  structureHash: "h",
  stages: [
    {
      stageId: "knowledge_collection",
      index: 0,
      label: "知识搜集",
      nodeIds: ["source_finding", "knowledge_handoff"],
    },
    {
      stageId: "experiment_design",
      index: 1,
      label: "实验设计",
      nodeIds: ["hypothesis_design"],
    },
    {
      stageId: "execution_iteration",
      index: 2,
      label: "执行迭代",
      nodeIds: ["iteration_decision", "result_package"],
    },
  ],
  nodes: [
    {
      nodeId: "source_finding",
      stageId: "knowledge_collection",
      label: "资料寻找",
      actorKind: "agent",
      primaryRoleKey: "finder",
      description: "find sources",
      producesArtifactKinds: ["source_candidate_batch"],
    },
    {
      nodeId: "knowledge_handoff",
      stageId: "knowledge_collection",
      label: "知识包交接",
      actorKind: "human",
      primaryRoleKey: "human",
      acceptsGateKinds: ["human"],
    },
    {
      nodeId: "hypothesis_design",
      stageId: "experiment_design",
      label: "假设设计",
      actorKind: "agent",
      primaryRoleKey: "scientist",
    },
    {
      nodeId: "iteration_decision",
      stageId: "execution_iteration",
      label: "迭代决策",
      actorKind: "agent",
      primaryRoleKey: "decider",
    },
    {
      nodeId: "result_package",
      stageId: "execution_iteration",
      label: "结果打包",
      actorKind: "system",
      primaryRoleKey: "package_builder",
    },
  ],
  edges: [
    {
      edgeId: "e_find_handoff",
      fromNodeId: "source_finding",
      toNodeId: "knowledge_handoff",
      label: "候选",
      gateKind: "auto",
    },
    {
      edgeId: "e_kc_hypothesis",
      fromNodeId: "knowledge_handoff",
      toNodeId: "hypothesis_design",
      label: "Knowledge Package",
      gateKind: "knowledge_package",
      requiresHumanAccept: true,
      requiredArtifactKinds: ["knowledge_package"],
    },
    {
      edgeId: "e_decision_rerun",
      fromNodeId: "iteration_decision",
      toNodeId: "result_package",
      label: "同协议重跑",
      gateKind: "auto",
    },
    {
      edgeId: "e_decision_promo",
      fromNodeId: "iteration_decision",
      toNodeId: "result_package",
      label: "晋升提案",
      gateKind: "promotion",
      requiresHumanAccept: true,
    },
  ],
};

describe("researchProcessGraphModel", () => {
  it("definition maps visual kinds and edge gate metadata", () => {
    const graph = definitionToCanvasGraph(definition);
    expect(graph.nodes.find((n) => n.nodeId === "source_finding")?.visualKind).toBe("start");
    expect(graph.nodes.find((n) => n.nodeId === "knowledge_handoff")?.visualKind).toBe("human_gate");
    expect(graph.nodes.find((n) => n.nodeId === "iteration_decision")?.visualKind).toBe("decision");
    expect(graph.nodes.find((n) => n.nodeId === "result_package")?.visualKind).toBe("end");
    const handoff = graph.edges.find((e) => e.edgeId === "e_kc_hypothesis");
    expect(handoff?.gateKind).toBe("knowledge_package");
    expect(handoff?.requiresHumanAccept).toBe(true);
    expect(handoff?.requiredArtifactKinds).toEqual(["knowledge_package"]);
    expect(handoff?.semanticKind).toBe("human_gate");
    expect(handoff?.labelAlwaysVisible).toBe(true);
    const rerun = graph.edges.find((e) => e.edgeId === "e_decision_rerun");
    expect(rerun?.semanticKind).toBe("rerun");
    expect(rerun?.sourceHandle).toBe("rerun");
  });

  it("projection keeps nodeRuns status, attempt, agent and human tasks", () => {
    const projection: WorkflowCanvasProjection = {
      definition,
      run: {
        runId: "run-1",
        status: "waiting_human",
        runtimeCurrentNodeIds: ["knowledge_handoff"],
        nodeRuns: {
          source_finding: {
            nodeId: "source_finding",
            status: "succeeded",
            attempt: 1,
            primaryAgentId: "agent-finder",
            actorKind: "agent",
          },
          knowledge_handoff: {
            nodeId: "knowledge_handoff",
            status: "waiting_human",
            attempt: 1,
            actorKind: "human",
          },
          hypothesis_design: {
            nodeId: "hypothesis_design",
            status: "pending",
            attempt: 0,
          },
        },
        pendingHumanTasks: [{ taskId: "t1", nodeId: "knowledge_handoff", status: "pending" }],
        blockedReason: null,
        completionKind: "",
        parentRunId: null,
        childRunIds: [],
        iterationBudgetMax: 3,
      },
    };
    const graph = projectionToCanvasGraph(projection);
    const finding = graph.nodes.find((n) => n.nodeId === "source_finding");
    const handoff = graph.nodes.find((n) => n.nodeId === "knowledge_handoff");
    expect(finding?.status).toBe("succeeded");
    expect(finding?.attempt).toBe(1);
    expect(finding?.primaryAgentId).toBe("agent-finder");
    expect(finding?.description).toBe("find sources");
    expect(handoff?.status).toBe("waiting_human");
    expect(handoff?.isRuntimeCurrent).toBe(true);
    expect(handoff?.hasPendingHumanTask).toBe(true);
    expect(graph.run?.runId).toBe("run-1");
    expect(graph.run?.iterationBudgetMax).toBe(3);
    expect(graph.run?.runtimeCurrentNodeIds).toEqual(["knowledge_handoff"]);
    // selected never on graph
    expect(JSON.stringify(graph)).not.toContain("selectedNodeId");
  });

  it("maps blocked and failed without collapsing them", () => {
    const projection: WorkflowCanvasProjection = {
      definition,
      run: {
        runId: "run-2",
        status: "blocked",
        runtimeCurrentNodeIds: ["hypothesis_design"],
        nodeRuns: {
          hypothesis_design: {
            nodeId: "hypothesis_design",
            status: "blocked",
            attempt: 2,
          },
        },
        pendingHumanTasks: [],
        blockedReason: "缺少 Knowledge Package",
      },
    };
    const graph = projectionToCanvasGraph(projection);
    const node = graph.nodes.find((n) => n.nodeId === "hypothesis_design");
    expect(node?.status).toBe("blocked");
    expect(node?.blockedReason).toContain("Knowledge Package");
    expect(node?.attempt).toBe(2);
  });

  it("keeps selection and runtime independent", () => {
    const merged = mergeSelectionAndRuntime({
      selectedNodeId: "hypothesis_design",
      runtimeCurrentNodeIds: ["knowledge_handoff"],
    });
    expect(merged.selectedNodeId).toBe("hypothesis_design");
    expect(merged.runtimeCurrentNodeIds).toEqual(["knowledge_handoff"]);
    expect(merged.selectedNodeId).not.toBe(merged.runtimeCurrentNodeIds[0]);
  });
});
