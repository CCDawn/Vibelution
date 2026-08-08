/**
 * Structural hash tests for the workflow canvas auto-layout.
 *
 * The hash must be stable for identical topology (order-sensitive), ignore
 * runtime-only fields (status/pathState/stageTone/attempt/isRuntimeCurrent/
 * primaryAgentId/blockedReason/edge label text), and change when topology or
 * node sizes change (sizes change `full` only, not `structure`).
 */
import { describe, expect, it } from "vitest";

import type {
  WorkflowCanvasEdgeInput,
  WorkflowCanvasNodeInput,
  WorkflowCanvasStageInput,
  WorkflowLayoutInput,
} from "../../../product/workflow/workflowCanvasTypes";
import { structuralWorkflowLayoutHash } from "./workflowLayoutHash";

function makeNode(overrides: Partial<WorkflowCanvasNodeInput>): WorkflowCanvasNodeInput {
  return {
    nodeId: "knowledge_collection",
    stageId: "knowledge_collection",
    label: "文献调研",
    actorKind: "agent",
    visualKind: "agent_task",
    status: "pending",
    ...overrides,
  };
}

function makeEdge(overrides: Partial<WorkflowCanvasEdgeInput>): WorkflowCanvasEdgeInput {
  return {
    edgeId: "e1",
    fromNodeId: "knowledge_collection",
    toNodeId: "experiment_design",
    label: "交接",
    gateKind: "auto",
    semanticKind: "main",
    pathState: "idle",
    labelAlwaysVisible: false,
    ...overrides,
  };
}

function makeInput(overrides: Partial<WorkflowLayoutInput>): WorkflowLayoutInput {
  const stages: WorkflowCanvasStageInput[] = [
    { stageId: "knowledge_collection", label: "调研", nodeIds: ["knowledge_collection"] },
    { stageId: "experiment_design", label: "设计", nodeIds: ["experiment_design"] },
  ];
  const nodes = [
    makeNode({ nodeId: "knowledge_collection", stageId: "knowledge_collection" }),
    makeNode({ nodeId: "experiment_design", stageId: "experiment_design" }),
  ];
  const edges = [makeEdge({})];
  return { stages, nodes, edges, run: null, ...overrides };
}

describe("structuralWorkflowLayoutHash", () => {
  it("is identical for identical content even with different object identity", () => {
    const a = makeInput({});
    const b = makeInput({});
    const ha = structuralWorkflowLayoutHash(a);
    const hb = structuralWorkflowLayoutHash(b);
    expect(ha.full).toBe(hb.full);
    expect(ha.structure).toBe(hb.structure);
  });

  it("ignores runtime-only fields (status, pathState, tone, attempt, runtime flags)", () => {
    const base = makeInput({});
    const runtimeChanged = makeInput({
      nodes: [
        makeNode({
          nodeId: "knowledge_collection",
          stageId: "knowledge_collection",
          status: "running",
          attempt: 3,
          isRuntimeCurrent: true,
          primaryAgentId: "agent-x",
          blockedReason: "waiting",
        }),
        makeNode({ nodeId: "experiment_design", stageId: "experiment_design" }),
      ],
      edges: [makeEdge({ pathState: "active" })],
      stages: [
        { stageId: "knowledge_collection", label: "调研", nodeIds: ["knowledge_collection"], stageTone: "active" },
        { stageId: "experiment_design", label: "设计", nodeIds: ["experiment_design"] },
      ],
    });
    expect(structuralWorkflowLayoutHash(base).full).toBe(structuralWorkflowLayoutHash(runtimeChanged).full);
  });

  it("ignores edge label text while the resolved label geometry is unchanged, and run meta", () => {
    const base = makeInput({});
    const relabeled = makeInput({
      // Same character count -> same resolveEdgeLabelSpec width/height.
      edges: [makeEdge({ label: "交汇" })],
      run: { runId: "run-1", status: "running", runtimeCurrentNodeIds: ["knowledge_collection"] },
    });
    expect(structuralWorkflowLayoutHash(base).full).toBe(structuralWorkflowLayoutHash(relabeled).full);
    expect(structuralWorkflowLayoutHash(base).structure).toBe(structuralWorkflowLayoutHash(relabeled).structure);
  });

  it("is sensitive to edge label geometry changes (wider label forces relayout)", () => {
    const base = makeInput({});
    const wider = makeInput({
      edges: [makeEdge({ label: "知识包跨阶段正式交接" })],
    });
    const shorter = makeInput({
      edges: [makeEdge({ label: "A" })],
    });
    expect(structuralWorkflowLayoutHash(base).structure).not.toBe(structuralWorkflowLayoutHash(wider).structure);
    expect(structuralWorkflowLayoutHash(base).full).not.toBe(structuralWorkflowLayoutHash(wider).full);
    expect(structuralWorkflowLayoutHash(base).structure).not.toBe(structuralWorkflowLayoutHash(shorter).structure);
  });

  it("is sensitive to stage order", () => {
    const base = makeInput({});
    const reordered = makeInput({
      stages: [
        { stageId: "experiment_design", label: "设计", nodeIds: ["experiment_design"] },
        { stageId: "knowledge_collection", label: "调研", nodeIds: ["knowledge_collection"] },
      ],
    });
    expect(structuralWorkflowLayoutHash(base).full).not.toBe(structuralWorkflowLayoutHash(reordered).full);
  });

  it("is sensitive to node order inside a stage", () => {
    const base = makeInput({
      stages: [
        { stageId: "knowledge_collection", label: "调研", nodeIds: ["knowledge_collection", "experiment_design"] },
        { stageId: "execution_iteration", label: "执行", nodeIds: [] },
      ],
    });
    const swapped = makeInput({
      stages: [
        { stageId: "knowledge_collection", label: "调研", nodeIds: ["experiment_design", "knowledge_collection"] },
        { stageId: "execution_iteration", label: "执行", nodeIds: [] },
      ],
    });
    expect(structuralWorkflowLayoutHash(base).full).not.toBe(structuralWorkflowLayoutHash(swapped).full);
  });

  it("is sensitive to edge topology and sourceHandle", () => {
    const base = makeInput({});
    const extraEdge = makeInput({
      edges: [makeEdge({}), makeEdge({ edgeId: "e2", toNodeId: "knowledge_collection" })],
    });
    const handleChanged = makeInput({
      edges: [makeEdge({ sourceHandle: "rerun", semanticKind: "rerun" })],
    });
    expect(structuralWorkflowLayoutHash(base).full).not.toBe(structuralWorkflowLayoutHash(extraEdge).full);
    expect(structuralWorkflowLayoutHash(base).full).not.toBe(structuralWorkflowLayoutHash(handleChanged).full);
  });

  it("is sensitive to visualKind changes", () => {
    const base = makeInput({});
    const decision = makeInput({
      nodes: [
        makeNode({
          nodeId: "knowledge_collection",
          stageId: "knowledge_collection",
          visualKind: "decision",
        }),
        makeNode({ nodeId: "experiment_design", stageId: "experiment_design" }),
      ],
    });
    expect(structuralWorkflowLayoutHash(base).full).not.toBe(structuralWorkflowLayoutHash(decision).full);
  });

  it("tracks measured sizes in full hash but not in structure hash", () => {
    const base = makeInput({});
    const sized = makeInput({});
    const ha = structuralWorkflowLayoutHash(base);
    const hb = structuralWorkflowLayoutHash(sized, new Map([["knowledge_collection", { width: 300, height: 120 }]]));
    expect(hb.structure).toBe(ha.structure);
    expect(hb.full).not.toBe(ha.full);
  });

  it("is sensitive to cross-stage membership moves", () => {
    const base = makeInput({
      stages: [
        { stageId: "knowledge_collection", label: "调研", nodeIds: ["knowledge_collection"] },
        { stageId: "experiment_design", label: "设计", nodeIds: ["experiment_design"] },
      ],
    });
    const moved = makeInput({
      stages: [
        { stageId: "knowledge_collection", label: "调研", nodeIds: ["experiment_design"] },
        { stageId: "experiment_design", label: "设计", nodeIds: ["knowledge_collection"] },
      ],
    });
    expect(structuralWorkflowLayoutHash(base).full).not.toBe(structuralWorkflowLayoutHash(moved).full);
  });
});
