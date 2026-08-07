/**
 * ELK workflow canvas layout tests (T1).
 *
 * These tests exercise the T1 pipeline directly:
 *   - workflowElkPorts (semantic port allocation)
 *   - workflowElkGraphAdapter (public input -> ELK compound graph)
 *   - bundled ELK probe (elkjs 0.12 facts against a real engine)
 *   - workflowElkLayout.fromElkLayout (engine output -> public geometry)
 *
 * The three-stage fixture mirrors the backend authority definition
 * (`core/research/workflow/definition.py`, challenge-cup-research): the five
 * decision outcomes exist, but the current run has exactly FOUR real
 * decision edges (rerun/promote/rollback/stop) — `revise` stays a capability
 * with no fabricated current-run edge.
 *
 * No `.skip`/`.todo`; every active test must be green for T1 completion.
 */
import ELK from "elkjs/lib/elk.bundled.js";
import { describe, expect, it } from "vitest";

import { decisionSourceHandle } from "../../../product/workflow/workflowCanvasModel";
import type { WorkflowLayoutInput } from "../../../product/workflow/workflowCanvasTypes";
import { toElkGraph } from "./workflowElkGraphAdapter";
import {
  WORKFLOW_ELK_ROOT_OPTIONS,
  WORKFLOW_ELK_STAGE_OPTIONS,
  WORKFLOW_STAGE_TITLE_HEIGHT,
} from "./workflowElkOptions";
import { fromElkLayout, toEdgeSections } from "./workflowElkLayout";
import { DECISION_OUTCOME_IDS, resolveElkPorts } from "./workflowElkPorts";

function segmentInBounds(
  a: { x: number; y: number },
  b: { x: number; y: number },
  bounds: { x: number; y: number; width: number; height: number },
): boolean {
  const left = bounds.x;
  const top = bounds.y;
  const right = bounds.x + bounds.width;
  const bottom = bounds.y + bounds.height;
  const segMinX = Math.min(a.x, b.x);
  const segMaxX = Math.max(a.x, b.x);
  const segMinY = Math.min(a.y, b.y);
  const segMaxY = Math.max(a.y, b.y);
  if (segMaxX < left || segMinX > right || segMaxY < top || segMinY > bottom) {
    return false;
  }
  if (a.x === b.x) {
    return true;
  }
  if (a.y === b.y) {
    return true;
  }
  return true;
}

/* ------------------------------------------------------------------ */
/* fixtures                                                            */
/* ------------------------------------------------------------------ */

function twoStageInput(): WorkflowLayoutInput {
  return {
    stages: [
      { stageId: "knowledge_collection", label: "知识搜集", nodeIds: ["source_finding", "protocol_design"] },
      { stageId: "execution_iteration", label: "执行迭代", nodeIds: ["controlled_run", "iteration_decision"] },
    ],
    nodes: [
      { nodeId: "source_finding", stageId: "knowledge_collection", label: "线索搜集", actorKind: "agent", visualKind: "start", status: "pending" },
      { nodeId: "protocol_design", stageId: "knowledge_collection", label: "协议设计", actorKind: "system", visualKind: "system_task", status: "pending" },
      { nodeId: "controlled_run", stageId: "execution_iteration", label: "受控执行", actorKind: "agent", visualKind: "agent_task", status: "pending" },
      { nodeId: "iteration_decision", stageId: "execution_iteration", label: "迭代决策", actorKind: "agent", visualKind: "decision", status: "pending" },
    ],
    edges: [
      { edgeId: "e_handoff", fromNodeId: "protocol_design", toNodeId: "controlled_run", label: "进入执行", gateKind: "human", semanticKind: "main", pathState: "idle", labelAlwaysVisible: false },
      { edgeId: "e_rerun", fromNodeId: "iteration_decision", toNodeId: "controlled_run", label: "同协议重跑", gateKind: "auto", semanticKind: "rerun", pathState: "idle", labelAlwaysVisible: true, sourceHandle: "rerun" },
    ],
  };
}

function fourDecisionEdges(): WorkflowLayoutInput {
  const graph = twoStageInput();
  graph.nodes.push(
    { nodeId: "candidate_promotion", stageId: "execution_iteration", label: "候选晋级", actorKind: "agent", visualKind: "agent_task", status: "pending" },
    { nodeId: "result_package", stageId: "execution_iteration", label: "结果汇总", actorKind: "system", visualKind: "end", status: "pending" },
  );
  graph.stages[1] = {
    ...graph.stages[1]!,
    nodeIds: ["controlled_run", "iteration_decision", "candidate_promotion", "result_package"],
  };
  graph.edges.push(
    { edgeId: "e_promote", fromNodeId: "iteration_decision", toNodeId: "candidate_promotion", label: "晋级", gateKind: "auto", semanticKind: "promote", pathState: "idle", labelAlwaysVisible: true, sourceHandle: "promote" },
    { edgeId: "e_rollback", fromNodeId: "iteration_decision", toNodeId: "candidate_promotion", label: "回退", gateKind: "auto", semanticKind: "rollback", pathState: "idle", labelAlwaysVisible: true, sourceHandle: "rollback" },
    { edgeId: "e_decision_stop", fromNodeId: "iteration_decision", toNodeId: "result_package", label: "停止", gateKind: "auto", semanticKind: "stop", pathState: "idle", labelAlwaysVisible: true, sourceHandle: "stop" },
  );
  return graph;
}

/**
 * Challenge-cup three-stage fixture mirroring the authoritative backend
 * definition (core/research/workflow/definition.py): the real current-run
 * decision edges for `iteration_decision` are exactly the four definition
 * edges (rerun/promote/rollback/stop); `revise` never receives one here.
 */
function challengeCupDefinition(): WorkflowLayoutInput {
  const node = (
    nodeId: string,
    stageId: string,
    label: string,
    actorKind: "agent" | "system" | "human",
    visualKind: "agent_task" | "system_task" | "human_gate" | "decision" | "start" | "end",
  ) => ({ nodeId, stageId, label, actorKind, visualKind, status: "pending" as const });

  const edge = (
    edgeId: string,
    fromNodeId: string,
    toNodeId: string,
    label: string,
    semanticKind: "main" | "rerun" | "promote" | "rollback" | "stop" = "main",
    sourceHandle?: string,
  ) => ({
    edgeId,
    fromNodeId,
    toNodeId,
    label,
    gateKind: "auto",
    semanticKind,
    pathState: "idle" as const,
    labelAlwaysVisible: semanticKind !== "main",
    sourceHandle,
  });

  const stages = [
    { stageId: "knowledge_collection", label: "知识搜集", nodeIds: ["source_finding", "source_extraction", "evidence_relations", "knowledge_ingestion", "knowledge_handoff"] },
    { stageId: "experiment_design", label: "实验设计", nodeIds: ["hypothesis_design", "protocol_design", "protocol_review", "protocol_freeze", "smoke_gate"] },
    { stageId: "execution_iteration", label: "执行迭代", nodeIds: ["controlled_run", "result_evaluation", "iteration_decision", "candidate_promotion", "result_package"] },
  ];

  const nodes = [
    node("source_finding", "knowledge_collection", "资料寻找", "agent", "start"),
    node("source_extraction", "knowledge_collection", "资料提炼", "agent", "agent_task"),
    node("evidence_relations", "knowledge_collection", "证据关系", "agent", "agent_task"),
    node("knowledge_ingestion", "knowledge_collection", "知识入库", "agent", "agent_task"),
    node("knowledge_handoff", "knowledge_collection", "知识包交接", "human", "human_gate"),
    node("hypothesis_design", "experiment_design", "假设设计", "agent", "agent_task"),
    node("protocol_design", "experiment_design", "协议设计", "agent", "agent_task"),
    node("protocol_review", "experiment_design", "协议评审", "agent", "agent_task"),
    node("protocol_freeze", "experiment_design", "协议冻结", "human", "human_gate"),
    node("smoke_gate", "experiment_design", "Smoke 放行", "human", "human_gate"),
    node("controlled_run", "execution_iteration", "受控运行", "system", "system_task"),
    node("result_evaluation", "execution_iteration", "结果评价", "agent", "agent_task"),
    node("iteration_decision", "execution_iteration", "迭代决策", "agent", "decision"),
    node("candidate_promotion", "execution_iteration", "候选晋升", "human", "human_gate"),
    node("result_package", "execution_iteration", "结果打包", "system", "system_task"),
  ];

  const edges = [
    edge("e_find_extract", "source_finding", "source_extraction", "候选资料"),
    edge("e_extract_rel", "source_extraction", "evidence_relations", "证据卡"),
    edge("e_rel_ingest", "evidence_relations", "knowledge_ingestion", "关系图"),
    edge("e_ingest_handoff", "knowledge_ingestion", "knowledge_handoff", "入库草稿"),
    edge("e_kc_hypothesis", "knowledge_handoff", "hypothesis_design", "Knowledge Package"),
    edge("e_hyp_proto", "hypothesis_design", "protocol_design", "假设集"),
    edge("e_proto_review", "protocol_design", "protocol_review", "协议草稿"),
    edge("e_review_freeze", "protocol_review", "protocol_freeze", "评审通过"),
    edge("e_freeze_smoke", "protocol_freeze", "smoke_gate", "冻结协议"),
    edge("e_smoke_run", "smoke_gate", "controlled_run", "Smoke 放行"),
    edge("e_run_eval", "controlled_run", "result_evaluation", "运行产物"),
    edge("e_eval_decision", "result_evaluation", "iteration_decision", "评价报告"),
    edge("e_decision_rerun", "iteration_decision", "controlled_run", "同协议重跑", "rerun", "rerun"),
    edge("e_decision_promo", "iteration_decision", "candidate_promotion", "晋升提案", "promote", "promote"),
    edge("e_decision_rollback", "iteration_decision", "candidate_promotion", "回滚提案", "rollback", "rollback"),
    edge("e_decision_stop", "iteration_decision", "result_package", "停止并打包", "stop", "stop"),
    edge("e_promo_package", "candidate_promotion", "result_package", "确认晋升/回滚"),
  ];

  return { stages, nodes, edges };
}

/* ------------------------------------------------------------------ */
/* probe · elkjs 0.12 API facts (bundled engine)                       */
/* ------------------------------------------------------------------ */
describe("probe · elkjs 0.12 API facts (bundled engine)", () => {
  const elk = new ELK();

  it("accepts the candidate layout option keys", async () => {
    const known = await elk.knownLayoutOptions();
    const ids = known.map((o) => o.id ?? "");
    // elkjs accepts short names (elk.algorithm) as aliases of the long names
    // (org.eclipse.elk.algorithm) reported by knownLayoutOptions. Assert the
    // long forms exist; the compound test below proves the short forms are
    // honored at layout time.
    for (const key of Object.keys(WORKFLOW_ELK_ROOT_OPTIONS)) {
      expect(ids).toContain(key.replace(/^elk\./, "org.eclipse.elk."));
    }
    for (const key of Object.keys(WORKFLOW_ELK_STAGE_OPTIONS)) {
      expect(ids).toContain(key.replace(/^elk\./, "org.eclipse.elk."));
    }
    expect(ids).toContain("org.eclipse.elk.port.side");
  });

  it("outputs compound stage/child coordinates and ORTHOGONAL sections", async () => {
    const input = fourDecisionEdges();
    const { root } = toElkGraph(input);
    const out = await elk.layout(root);

    const stages = out.children ?? [];
    expect(stages.length).toBeGreaterThanOrEqual(2);
    for (const stage of stages) {
      expect(stage.x).toBeGreaterThanOrEqual(0);
      expect(stage.y).toBeGreaterThanOrEqual(0);
      for (const child of stage.children ?? []) {
        expect(child.x).toBeGreaterThanOrEqual(0);
        expect(child.y).toBeGreaterThanOrEqual(0);
      }
    }

    const allEdges = [...(out.edges ?? []), ...stages.flatMap((s) => s.edges ?? [])];
    expect(allEdges.length).toBe(input.edges.length);
    for (const edge of allEdges) {
      const section = edge.sections?.[0];
      expect(section?.startPoint).toBeDefined();
      expect(section?.endPoint).toBeDefined();
    }
  });

  it("keeps FIXED_ORDER port declaration order in the output graph", async () => {
    const input = fourDecisionEdges();
    const { root } = toElkGraph(input);
    const out = await elk.layout(root);

    const { byNodeId } = resolveElkPorts({ nodes: input.nodes, edges: input.edges });
    const declared = byNodeId.get("iteration_decision")!.map((p) => p.id);

    const stage = out.children?.find((s) => s.id === "stage:execution_iteration");
    const decision = stage?.children?.find((n) => n.id === "iteration_decision");
    const outputPortIds = (decision?.ports ?? []).map((p) => p.id);
    expect(outputPortIds).toEqual(declared);
    expect(outputPortIds).toHaveLength(4);
    expect(new Set(outputPortIds).size).toBe(outputPortIds.length);
  });

  it("reports edge label coordinates from the engine (no 50% estimate needed)", async () => {
    const input = fourDecisionEdges();
    const { root } = toElkGraph(input);
    const out = await elk.layout(root);

    const allEdges = [
      ...(out.edges ?? []),
      ...(out.children ?? []).flatMap((s) => s.edges ?? []),
    ];
    const withLabel = allEdges.filter((e) => (e.labels?.length ?? 0) > 0);
    expect(withLabel.length).toBeGreaterThan(0);
    for (const edge of withLabel) {
      expect(edge.labels![0].x).toBeDefined();
      expect(edge.labels![0].y).toBeDefined();
    }
  });

  it("normalizes stage-internal and cross-stage sections into one coordinate space", async () => {
    const input = fourDecisionEdges();
    const { root } = toElkGraph(input);
    const out = await elk.layout(root);
    const result = fromElkLayout(out, input);

    expect(result.nodes.filter((n) => n.kind === "stage")).toHaveLength(2);
    expect(result.edges).toHaveLength(input.edges.length);
    for (const edge of result.edges) {
      expect(edge.sections.length).toBeGreaterThan(0);
    }
    const rerun = result.edges.find((e) => e.id === "e_rerun");
    const controlled = result.nodes.find((n) => n.id === "controlled_run");
    expect(controlled).toBeDefined();
    expect(rerun!.sections[0].start.x).toBeGreaterThanOrEqual(0);
    expect(rerun!.sections[0].start.y).toBeGreaterThanOrEqual(0);
  });

  it("keeps fromElkLayout deterministic for identical input", async () => {
    const input = fourDecisionEdges();
    const a = fromElkLayout(await elk.layout(toElkGraph(input).root), input);
    const b = fromElkLayout(await elk.layout(toElkGraph(input).root), input);
    expect(a).toEqual(b);
  });
});

/* ------------------------------------------------------------------ */
/* ports contract                                                      */
/* ------------------------------------------------------------------ */
describe("workflowElkPorts · semantic port contract", () => {
  it("assigns globally-unique port ids with resolvable endpoints", () => {
    const input = fourDecisionEdges();
    const { byEdgeId, byNodeId } = resolveElkPorts({ nodes: input.nodes, edges: input.edges });

    const allPortIds = [...byNodeId.values()].flatMap((p) => p.map((x) => x.id));
    expect(new Set(allPortIds).size).toBe(allPortIds.length);

    for (const edge of input.edges) {
      const assignment = byEdgeId.get(edge.edgeId);
      expect(assignment).toBeDefined();
      expect(byNodeId.get(edge.fromNodeId)?.some((p) => p.id === assignment!.sourcePortId)).toBe(true);
      expect(byNodeId.get(edge.toNodeId)?.some((p) => p.id === assignment!.targetPortId)).toBe(true);
    }
  });

  it("rerun uses decision:rerun (WEST) -> feedback:in (EAST)", () => {
    const input = fourDecisionEdges();
    const { byEdgeId, byNodeId } = resolveElkPorts({ nodes: input.nodes, edges: input.edges });
    const rerun = byEdgeId.get("e_rerun");
    expect(rerun?.sourcePortId).toBe("decision:rerun:iteration_decision");
    expect(rerun?.targetPortId).toBe("feedback:in:controlled_run");
    const sourceSide = byNodeId.get("iteration_decision")?.find((p) => p.id === rerun?.sourcePortId)?.side;
    const targetSide = byNodeId.get("controlled_run")?.find((p) => p.id === rerun?.targetPortId)?.side;
    expect(sourceSide).toBe("WEST");
    expect(targetSide).toBe("EAST");
  });

  it("promote and rollback use distinct source/target ports and stay two independent edges", () => {
    const input = fourDecisionEdges();
    const { byEdgeId, byNodeId } = resolveElkPorts({ nodes: input.nodes, edges: input.edges });
    const promote = byEdgeId.get("e_promote")!;
    const rollback = byEdgeId.get("e_rollback")!;
    expect(promote.sourcePortId).not.toBe(rollback.sourcePortId);
    expect(promote.targetPortId).not.toBe(rollback.targetPortId);
    expect(promote.sourcePortId).toBe("decision:promote:iteration_decision");
    expect(rollback.sourcePortId).toBe("decision:rollback:iteration_decision");
    expect(byNodeId.get("candidate_promotion")?.filter((p) => p.id.includes("in:")).length).toBe(2);

    const { root } = toElkGraph(input);
    const allElkEdges = [...(root.edges ?? []), ...(root.children ?? []).flatMap((s) => s.edges ?? [])];
    expect(allElkEdges.filter((e) => e.id === "e_promote")).toHaveLength(1);
    expect(allElkEdges.filter((e) => e.id === "e_rollback")).toHaveLength(1);
  });

  it("stop connects decision:stop to the result_package real port", () => {
    const input = fourDecisionEdges();
    const { byEdgeId } = resolveElkPorts({ nodes: input.nodes, edges: input.edges });
    const stop = byEdgeId.get("e_decision_stop");
    expect(stop?.sourcePortId).toBe("decision:stop:iteration_decision");
    expect(stop?.targetPortId).toBe("in:north:result_package");
  });

  it("exposes exactly five decision outcomes", () => {
    expect(DECISION_OUTCOME_IDS).toEqual(["rerun", "revise", "promote", "rollback", "stop"]);
  });

  it("revise gets no current-run port; fabricated revise edges throw a diagnosable error", () => {
    const input = fourDecisionEdges();
    const { byNodeId } = resolveElkPorts({ nodes: input.nodes, edges: input.edges });
    const decisionPorts = byNodeId.get("iteration_decision") ?? [];
    expect(decisionPorts.some((p) => p.id.includes("revise"))).toBe(false);

    const fabricated = {
      ...input,
      edges: [
        ...input.edges,
        {
          edgeId: "e_revise_fake",
          fromNodeId: "iteration_decision",
          toNodeId: "protocol_design",
          label: "revise",
          gateKind: "auto",
          semanticKind: "revise" as const,
          pathState: "idle" as const,
          labelAlwaysVisible: true,
          sourceHandle: "revise",
        },
      ],
    };
    expect(() => resolveElkPorts({ nodes: fabricated.nodes, edges: fabricated.edges })).toThrow(/revise/);
  });
});

/* ------------------------------------------------------------------ */
/* adapter contract                                                    */
/* ------------------------------------------------------------------ */
describe("workflowElkGraphAdapter · three-stage challenge-cup definition", () => {
  it("keeps every node in exactly one stage", () => {
    const input = challengeCupDefinition();
    const seen = new Set<string>();
    for (const stage of input.stages) {
      for (const nodeId of stage.nodeIds) {
        expect(seen.has(nodeId)).toBe(false);
        seen.add(nodeId);
      }
    }
    expect(input.nodes.length).toBe(seen.size);
  });

  it("produces the same ELK graph twice (deterministic input shape)", () => {
    const a = toElkGraph(challengeCupDefinition());
    const b = toElkGraph(challengeCupDefinition());
    expect(JSON.stringify(a.root)).toBe(JSON.stringify(b.root));
  });

  it("keeps every edge endpoint resolvable to a real node port", () => {
    const { root } = toElkGraph(challengeCupDefinition());
    const portIds = new Set<string>();
    for (const stage of root.children ?? []) {
      for (const child of stage.children ?? []) {
        for (const port of child.ports ?? []) portIds.add(port.id);
      }
    }
    const allEdges = [...(root.edges ?? []), ...(root.children ?? []).flatMap((s) => s.edges ?? [])];
    expect(allEdges.length).toBe(challengeCupDefinition().edges.length);
    for (const edge of allEdges) {
      expect(edge.sources?.every((s) => portIds.has(s))).toBe(true);
      expect(edge.targets?.every((t) => portIds.has(t))).toBe(true);
    }
  });
});

/* ------------------------------------------------------------------ */
/* geometry consumption                                                */
/* ------------------------------------------------------------------ */
describe("workflowElkLayout.fromElkLayout · geometry consumption", () => {
  it("keeps a discontiguous multi-section chain without synthesizing a link", () => {
    const sections = [
      {
        id: "e:0",
        startPoint: { x: 0, y: 0 },
        endPoint: { x: 30, y: 0 },
        bendPoints: [],
        incomingSections: [],
        outgoingSections: ["e:1"],
      },
      {
        id: "e:1",
        startPoint: { x: 31, y: 5 },
        endPoint: { x: 60, y: 5 },
        bendPoints: [],
        incomingSections: ["e:0"],
        outgoingSections: [],
      },
    ];
    const out = toEdgeSections(sections as never);
    expect(out).toHaveLength(2);
    expect(out[0].end).toEqual({ x: 30, y: 0 });
    expect(out[1].start).toEqual({ x: 31, y: 5 });
    // No new segment is appended between 30,0 and 31,5: both sections are
    // preserved as-is; a later SVG builder will emit two `M` subpaths.
    expect(out[0].outgoingSectionIds).toEqual(["e:1"]);
  });

  it("delivers engine-owned label bounds and sections for every edge", async () => {
    const elk = new ELK();
    const input = challengeCupDefinition();
    const out = await elk.layout(toElkGraph(input).root);
    const result = fromElkLayout(out, input);

    expect(result.edges).toHaveLength(input.edges.length);
    for (const edge of result.edges) {
      expect(edge.sections.length).toBeGreaterThan(0);
    }
    const rerun = result.edges.find((e) => e.id === "e_decision_rerun");
    expect(rerun?.labelBounds).toBeDefined();
    expect(typeof rerun?.labelBounds?.x).toBe("number");
    expect(typeof rerun?.labelBounds?.y).toBe("number");
  });

  it("derives sourceHandleIds from real outgoing edges, not a hardcoded capability list", async () => {
    const elk = new ELK();
    const input = challengeCupDefinition();
    const out = await elk.layout(toElkGraph(input).root);
    const result = fromElkLayout(out, input);

    const decision = result.nodes.find((n) => n.id === "iteration_decision")!;
    expect(decision.sourceHandleIds).toEqual(["rerun", "promote", "rollback", "stop"]);
    expect(decision.decisionOutcomeIds).toEqual([...DECISION_OUTCOME_IDS]);
    const regular = result.nodes.find((n) => n.id === "source_finding");
    expect(regular?.decisionOutcomeIds).toBeUndefined();
  });

  it("keeps promote/rollback distinguishable through their ELK sections", async () => {
    const elk = new ELK();
    const input = fourDecisionEdges();
    const out = await elk.layout(toElkGraph(input).root);
    const result = fromElkLayout(out, input);
    const promote = result.edges.find((e) => e.id === "e_promote")!;
    const rollback = result.edges.find((e) => e.id === "e_rollback")!;
    expect(JSON.stringify(promote.sections)).not.toBe(JSON.stringify(rollback.sections));
  });

  it("model: decisionSourceHandle(revise) yields a distinct 'revise' handle", () => {
    expect(decisionSourceHandle("revise", "edge_revise")).toBe("revise");
  });
});

/* ------------------------------------------------------------------ */
/* geometry invariants (engine results)                                */
/* ------------------------------------------------------------------ */
describe("probe · geometry invariants (engine results)", () => {
  const elk = new ELK();

  it("orders the three real stages along RIGHT 1→2→3", async () => {
    const input = challengeCupDefinition();
    const out = await elk.layout(toElkGraph(input).root);
    const children = out.children ?? [];
    const byId = (id: string) => children.find((s) => s.id === id)!;
    const knowledge = byId("stage:knowledge_collection");
    const experiment = byId("stage:experiment_design");
    const execution = byId("stage:execution_iteration");

    for (const stage of [knowledge, experiment, execution]) {
      expect(Number.isFinite(stage.x)).toBe(true);
      expect(Number.isFinite(stage.y)).toBe(true);
      expect(Number.isFinite(stage.width)).toBe(true);
      expect(Number.isFinite(stage.height)).toBe(true);
    }

    // Layering along RIGHT must advance the explicit x extent of each stage,
    // regardless of stage y (a vertical pile-up with identical x must fail).
    expect((knowledge.x as number) + (knowledge.width as number)).toBeLessThan(
      experiment.x as number,
    );
    expect((experiment.x as number) + (experiment.width as number)).toBeLessThan(
      execution.x as number,
    );

    // Stage bounds must not overlap in canvas space.
    const stages = [knowledge, experiment, execution];
    for (let i = 0; i < stages.length; i += 1) {
      for (let j = i + 1; j < stages.length; j += 1) {
        const a = stages[i];
        const b = stages[j];
        const overlapX = (a.x as number) < (b.x as number) + (b.width as number)
          && (b.x as number) < (a.x as number) + (a.width as number);
        const overlapY = (a.y as number) < (b.y as number) + (b.height as number)
          && (b.y as number) < (a.y as number) + (a.height as number);
        expect(overlapX && overlapY).toBe(false);
      }
    }
  });

  it("normalizes cross-stage (root) edge sections into absolute canvas space", async () => {
    const input = challengeCupDefinition();
    const out = await elk.layout(toElkGraph(input).root);
    const result = fromElkLayout(out, input);

    const handoff = result.edges.find((e) => e.id === "e_kc_hypothesis")!;
    const knowledgeStage = result.nodes.find((n) => n.id === "stage:knowledge_collection")!;
    // Root-level sections are already absolute; fromElkLayout must not double
    // offset them. The start point sits on the handoff node (inside the first
    // stage), i.e. inside the knowledge stage bounds.
    const start = handoff.sections[0].start;
    expect(start.x).toBeGreaterThanOrEqual(knowledgeStage.x);
    expect(start.x).toBeLessThanOrEqual(knowledgeStage.x + knowledgeStage.width);
    expect(start.y).toBeGreaterThanOrEqual(knowledgeStage.y);
    expect(start.y).toBeLessThanOrEqual(knowledgeStage.y + knowledgeStage.height);
  });

  it("routes the rerun feedback edge outside ordinary nodes and the stage title band", async () => {
    const input = challengeCupDefinition();
    const out = await elk.layout(toElkGraph(input).root);
    const result = fromElkLayout(out, input);

    const rerun = result.edges.find((e) => e.id === "e_decision_rerun")!;
    const stage = result.nodes.find((n) => n.id === "stage:execution_iteration")!;
    const nodes = result.nodes.filter(
      (n) => n.parentStageId === stage.id && n.id !== "iteration_decision" && n.id !== "controlled_run",
    );
    const titleBandBottom = stage.y + WORKFLOW_STAGE_TITLE_HEIGHT;

    const points = rerun.sections.flatMap((s) => [s.start, s.end, ...s.bendPoints]);
    // The feedback route must stay below the stage title band.
    for (const point of points) {
      expect(point.y).toBeGreaterThanOrEqual(titleBandBottom - 0.5);
    }
    // The feedback route must not intersect any non-endpoint node bounds.
    for (const section of rerun.sections) {
      const polyline = [
        section.start,
        ...section.bendPoints,
        section.end,
      ];
      for (let i = 0; i + 1 < polyline.length; i += 1) {
        const a = polyline[i]!;
        const b = polyline[i + 1]!;
        for (const node of nodes) {
          expect(segmentInBounds(a, b, node)).toBe(false);
        }
      }
    }
  });

  it("keeps the rerun feedback edge inside its own stage region", async () => {
    const input = challengeCupDefinition();
    const out = await elk.layout(toElkGraph(input).root);
    const result = fromElkLayout(out, input);
    const rerun = result.edges.find((e) => e.id === "e_decision_rerun")!;
    const load = result.nodes.find((n) => n.id === "stage:execution_iteration")!;
    const rect = {
      left: load.x,
      top: load.y,
      right: load.x + load.width,
      bottom: load.y + load.height,
    };
    for (const section of rerun.sections) {
      for (const point of [section.start, section.end, ...section.bendPoints]) {
        expect(point.x).toBeGreaterThanOrEqual(rect.left - 0.5);
        expect(point.x).toBeLessThanOrEqual(rect.right + 0.5);
        expect(point.y).toBeGreaterThanOrEqual(rect.top - 0.5);
        expect(point.y).toBeLessThanOrEqual(rect.bottom + 0.5);
      }
    }
  });

  it("same input -> same public layout twice (fresh graphs, no reused laid-out root)", async () => {
    const input = challengeCupDefinition();
    // ELK's raw output carries an internal `$H` layout counter that advances
    // across runs; the PUBLIC contract is the fromElkLayout result, which is
    // canonical geometry only. Each run starts from a brand-new graph.
    const first = fromElkLayout(await elk.layout(toElkGraph(input).root), input);
    const second = fromElkLayout(await elk.layout(toElkGraph(input).root), input);
    expect(JSON.stringify(first)).toBe(JSON.stringify(second));
  });
});
