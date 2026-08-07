import { describe, expect, it } from "vitest";

import {
  buildEdgePathStates,
  decisionSourceHandle,
  edgeLabelAlwaysVisible,
  resolveEdgePathState,
  resolveEdgeSemanticKind,
  resolveNodeVisualKind,
  stageToneFromNodes,
} from "./workflowCanvasModel";

describe("workflowCanvasModel", () => {
  it("classifies node visual kinds", () => {
    expect(resolveNodeVisualKind({ nodeId: "source_finding", actorKind: "agent" })).toBe("start");
    expect(resolveNodeVisualKind({ nodeId: "result_package", actorKind: "system" })).toBe("end");
    expect(resolveNodeVisualKind({ nodeId: "iteration_decision", actorKind: "agent" })).toBe("decision");
    expect(resolveNodeVisualKind({ nodeId: "knowledge_handoff", actorKind: "human" })).toBe("human_gate");
    expect(resolveNodeVisualKind({ nodeId: "controlled_run", actorKind: "system" })).toBe("system_task");
    expect(resolveNodeVisualKind({ nodeId: "protocol_design", actorKind: "agent" })).toBe("agent_task");
  });

  it("classifies edge semantic kinds", () => {
    expect(
      resolveEdgeSemanticKind({
        edgeId: "e_decision_rerun",
        label: "同协议重跑",
        gateKind: "auto",
        fromNodeId: "iteration_decision",
        toNodeId: "controlled_run",
      }),
    ).toBe("rerun");
    expect(
      resolveEdgeSemanticKind({
        edgeId: "e_decision_promo",
        label: "晋升提案",
        gateKind: "promotion",
        requiresHumanAccept: true,
        fromNodeId: "iteration_decision",
        toNodeId: "candidate_promotion",
      }),
    ).toBe("promote");
    expect(
      resolveEdgeSemanticKind({
        edgeId: "e_decision_rollback",
        label: "回滚提案",
        gateKind: "promotion",
        fromNodeId: "iteration_decision",
        toNodeId: "candidate_promotion",
      }),
    ).toBe("rollback");
    expect(
      resolveEdgeSemanticKind({
        edgeId: "e_decision_stop",
        label: "停止并打包",
        gateKind: "auto",
        fromNodeId: "iteration_decision",
        toNodeId: "result_package",
      }),
    ).toBe("stop");
    expect(
      resolveEdgeSemanticKind({
        edgeId: "e_ingest_handoff",
        label: "入库草稿",
        gateKind: "human",
        requiresHumanAccept: true,
        fromNodeId: "a",
        toNodeId: "b",
      }),
    ).toBe("human_gate");
  });

  it("shows critical labels always and hides plain auto", () => {
    expect(edgeLabelAlwaysVisible("rerun", "auto")).toBe(true);
    expect(edgeLabelAlwaysVisible("human_gate", "human")).toBe(true);
    expect(edgeLabelAlwaysVisible("main", "auto")).toBe(false);
  });

  it("assigns decision source handles", () => {
    expect(decisionSourceHandle("rerun", "e_decision_rerun")).toBe("rerun");
    expect(decisionSourceHandle("promote", "e_decision_promo")).toBe("promote");
    expect(decisionSourceHandle("rollback", "e_decision_rollback")).toBe("rollback");
    expect(decisionSourceHandle("stop", "e_decision_stop")).toBe("stop");
  });

  it("derives path state without inventing decision branch selection", () => {
    expect(
      resolveEdgePathState({
        sourceStatus: "succeeded",
        targetStatus: "pending",
        sourceIsCurrent: false,
        targetIsCurrent: false,
        semanticKind: "rerun",
      }),
    ).toBe("idle");
    expect(
      resolveEdgePathState({
        sourceStatus: "succeeded",
        targetStatus: "running",
        sourceIsCurrent: false,
        targetIsCurrent: true,
        semanticKind: "main",
      }),
    ).toBe("active");
    expect(
      resolveEdgePathState({
        sourceStatus: "waiting_human",
        targetStatus: "pending",
        sourceIsCurrent: true,
        targetIsCurrent: false,
        semanticKind: "human_gate",
      }),
    ).toBe("attention");
  });

  it("does not mark UI selection as runtime in path builder inputs", () => {
    const edges = buildEdgePathStates(
      [
        {
          edgeId: "e1",
          fromNodeId: "a",
          toNodeId: "b",
          label: "x",
          gateKind: "auto",
          semanticKind: "main",
          labelAlwaysVisible: false,
        },
      ],
      new Map([
        [
          "a",
          {
            nodeId: "a",
            stageId: "s",
            label: "A",
            actorKind: "agent",
            visualKind: "agent_task",
            status: "succeeded",
          },
        ],
        [
          "b",
          {
            nodeId: "b",
            stageId: "s",
            label: "B",
            actorKind: "agent",
            visualKind: "agent_task",
            status: "ready",
          },
        ],
      ]),
      new Set(), // no runtime current — selected is not passed here
    );
    // target ready → active path (not idle; selection is not involved)
    expect(edges[0].pathState).toBe("active");
  });

  it("computes stage tone", () => {
    expect(stageToneFromNodes([{ status: "succeeded" }, { status: "succeeded" }])).toBe("done");
    expect(stageToneFromNodes([{ status: "running", isRuntimeCurrent: true }])).toBe("active");
    expect(stageToneFromNodes([{ status: "waiting_human" }])).toBe("attention");
    expect(stageToneFromNodes([{ status: "pending" }])).toBe("idle");
  });
});
