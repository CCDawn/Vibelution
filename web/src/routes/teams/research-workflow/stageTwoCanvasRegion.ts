/**
 * Stage-two inactive canvas region (display layer only).
 *
 * New challenge-cup runs pin the truncated stage-one definition
 * (`challenge-cup-research@2.2.0-stage-one`): seven nodes ending at
 * `hypothesis_design`; the ten protocol/experiment nodes are absent from the
 * run graph. Stage two never auto-activates (allowPhaseTwoAdvance=false), so
 * this region renders those ten nodes as one grayed "研究计划与实验 · 未激活"
 * group so the two-stage split stays visible. Data source is the frontend
 * contract copy CHALLENGE_CUP_NODE_IDS plus a static mirror of
 * core/research/workflow/definition.py node labels — no runtime state, no
 * activation action, and clicking only explains the inactive semantics.
 */
import type { WorkflowLayoutInput } from "../../../components/vui";
import type {
  WorkflowCanvasEdgeInput,
  WorkflowCanvasNodeInput,
  WorkflowCanvasStageInput,
  WorkflowNodeRunStatus,
} from "../../../components/vui";
import {
  buildEdgePathStates,
  decisionSourceHandle,
  edgeLabelAlwaysVisible,
  resolveEdgeSemanticKind,
  resolveNodeVisualKind,
  stageToneFromNodes,
} from "../../../components/vui/product/workflow/workflowCanvasModel";
import { CHALLENGE_CUP_NODE_IDS } from "../../../api/types/researchWorkflow";

export const STAGE_TWO_INACTIVE_STAGE_ID = "stage_two_inactive";
export const STAGE_TWO_INACTIVE_STAGE_LABEL = "研究计划与实验 · 未激活";
/** Boundary edge: stage-one terminal → stage-two head, explains activation. */
export const STAGE_TWO_BOUNDARY_EDGE_ID = "e_stage_two_inactive_boundary";

/** Stage-one node ids (truncated definition); everything after is stage two. */
const STAGE_ONE_NODE_SET: ReadonlySet<string> = new Set([
  "problem_understanding",
  "source_finding",
  "source_extraction",
  "evidence_relations",
  "knowledge_ingestion",
  "knowledge_handoff",
  "hypothesis_design",
]);

/** The ten stage-two nodes in canonical order (subset of the contract copy). */
export const STAGE_TWO_INACTIVE_NODE_IDS: readonly string[] = CHALLENGE_CUP_NODE_IDS.filter(
  (nodeId) => !STAGE_ONE_NODE_SET.has(nodeId),
);

const STAGE_TWO_INACTIVE_NODE_SET: ReadonlySet<string> = new Set(STAGE_TWO_INACTIVE_NODE_IDS);

/**
 * Static mirror of core/research/workflow/definition.py (actorKind + label).
 * Labels/actors stay hand-copied like CHALLENGE_CUP_NODE_IDS itself; the
 * definition-sync contract tests pin the id list, and this region renders only
 * when the run definition does NOT contain these nodes.
 */
const STAGE_TWO_NODE_SPECS: ReadonlyArray<{
  nodeId: string;
  label: string;
  actorKind: "agent" | "human" | "system";
}> = [
  { nodeId: "protocol_design", label: "协议设计", actorKind: "agent" },
  { nodeId: "protocol_review", label: "协议评审", actorKind: "agent" },
  { nodeId: "protocol_freeze", label: "协议冻结", actorKind: "human" },
  { nodeId: "smoke_gate", label: "试跑放行", actorKind: "human" },
  { nodeId: "controlled_run", label: "受控运行", actorKind: "system" },
  { nodeId: "result_evaluation", label: "结果评价", actorKind: "agent" },
  { nodeId: "iteration_decision", label: "迭代决策", actorKind: "agent" },
  { nodeId: "version_governance", label: "版本治理", actorKind: "agent" },
  { nodeId: "candidate_promotion", label: "候选晋升", actorKind: "human" },
  { nodeId: "result_package", label: "结果打包", actorKind: "system" },
];

/** True when the id belongs to the grayed stage-two preview group. */
export function isStageTwoInactiveCanvasNode(nodeId: string | null | undefined): boolean {
  return Boolean(nodeId) && STAGE_TWO_INACTIVE_NODE_SET.has(String(nodeId));
}

/**
 * Static display label for an inactive stage-two node. Looked up from the
 * mirror, never from the run definition — a truncated definition by definition
 * does not contain these nodes.
 */
export function stageTwoInactiveNodeLabel(nodeId: string | null | undefined): string | undefined {
  if (!nodeId) return undefined;
  return STAGE_TWO_NODE_SPECS.find((spec) => spec.nodeId === String(nodeId))?.label;
}

/** Stage-two region composes only for definitions truncated before stage two. */
export function definitionNeedsStageTwoInactiveRegion(definition: {
  nodes: Array<{ nodeId: string }>;
} | null | undefined): boolean {
  if (!definition) return false;
  return !definition.nodes.some((node) => node.nodeId === "protocol_design");
}

export type StageTwoInactiveCanvasRegion = {
  stage: WorkflowCanvasStageInput;
  nodes: WorkflowCanvasNodeInput[];
  edges: WorkflowCanvasEdgeInput[];
};

const INACTIVE_STATUS: WorkflowNodeRunStatus = "pending";
const INACTIVE_DESCRIPTION = "第二阶段未激活，需按题显式开启";

/**
 * Static mirror of the stage-two edges in core/research/workflow/definition.py.
 * `revise` is intentionally absent: it forks a child run and therefore has no
 * current-run edge. Decision semantics and handles reuse the public workflow
 * model helpers used by active workflow projections.
 */
const STAGE_TWO_EDGE_SPECS: ReadonlyArray<{
  edgeId: string;
  fromNodeId: string;
  toNodeId: string;
  label: string;
  gateKind: string;
  requiresHumanAccept?: boolean;
}> = [
  { edgeId: "e_proto_review", fromNodeId: "protocol_design", toNodeId: "protocol_review", label: "协议草稿", gateKind: "auto" },
  { edgeId: "e_review_freeze", fromNodeId: "protocol_review", toNodeId: "protocol_freeze", label: "评审通过", gateKind: "human", requiresHumanAccept: true },
  { edgeId: "e_freeze_smoke", fromNodeId: "protocol_freeze", toNodeId: "smoke_gate", label: "冻结协议", gateKind: "frozen_protocol" },
  { edgeId: "e_smoke_run", fromNodeId: "smoke_gate", toNodeId: "controlled_run", label: "试跑放行", gateKind: "smoke", requiresHumanAccept: true },
  { edgeId: "e_run_eval", fromNodeId: "controlled_run", toNodeId: "result_evaluation", label: "运行产物", gateKind: "auto" },
  { edgeId: "e_eval_decision", fromNodeId: "result_evaluation", toNodeId: "iteration_decision", label: "评价报告", gateKind: "auto" },
  { edgeId: "e_decision_rerun", fromNodeId: "iteration_decision", toNodeId: "controlled_run", label: "同协议重跑", gateKind: "auto" },
  { edgeId: "e_decision_promote", fromNodeId: "iteration_decision", toNodeId: "version_governance", label: "晋升版本", gateKind: "auto" },
  { edgeId: "e_decision_rollback", fromNodeId: "iteration_decision", toNodeId: "version_governance", label: "回滚版本", gateKind: "auto" },
  { edgeId: "e_decision_stop", fromNodeId: "iteration_decision", toNodeId: "version_governance", label: "停止迭代", gateKind: "auto" },
  { edgeId: "e_version_promotion", fromNodeId: "version_governance", toNodeId: "candidate_promotion", label: "晋升提案", gateKind: "promotion", requiresHumanAccept: true },
  { edgeId: "e_version_package", fromNodeId: "version_governance", toNodeId: "result_package", label: "停止并打包", gateKind: "auto" },
  { edgeId: "e_promo_package", fromNodeId: "candidate_promotion", toNodeId: "result_package", label: "确认晋升/回滚", gateKind: "human", requiresHumanAccept: true },
];

/**
 * Builds the static grayed fragment. Pure display: every node is pending, the
 * stage tone is idle, and no actionable state is ever rendered.
 */
export function buildStageTwoInactiveCanvasRegion(): StageTwoInactiveCanvasRegion {
  const nodes: WorkflowCanvasNodeInput[] = STAGE_TWO_NODE_SPECS.map((spec) => ({
    nodeId: spec.nodeId,
    stageId: STAGE_TWO_INACTIVE_STAGE_ID,
    label: spec.label,
    actorKind: spec.actorKind,
    visualKind: resolveNodeVisualKind({
      nodeId: spec.nodeId,
      actorKind: spec.actorKind,
      isFirstInWorkflow: false,
      isTerminalPackage: spec.nodeId === "result_package",
    }),
    status: INACTIVE_STATUS,
    description: INACTIVE_DESCRIPTION,
  }));

  const edges: Array<Omit<WorkflowCanvasEdgeInput, "pathState">> = STAGE_TWO_EDGE_SPECS.map(
    (edge) => {
      const semanticKind = resolveEdgeSemanticKind(edge);
      return {
        ...edge,
        semanticKind,
        sourceHandle: edge.fromNodeId === "iteration_decision"
          ? decisionSourceHandle(semanticKind, edge.edgeId)
          : undefined,
        labelAlwaysVisible: edgeLabelAlwaysVisible(semanticKind, edge.gateKind),
      };
    },
  );

  const stage: WorkflowCanvasStageInput = {
    stageId: STAGE_TWO_INACTIVE_STAGE_ID,
    label: STAGE_TWO_INACTIVE_STAGE_LABEL,
    nodeIds: nodes.map((node) => node.nodeId),
    index: Number.MAX_SAFE_INTEGER,
    stageTone: stageToneFromNodes(nodes),
    progress: { completed: 0, total: nodes.length },
  };

  const nodeById = new Map(nodes.map((node) => [node.nodeId, node] as const));
  return { stage, nodes, edges: buildEdgePathStates(edges, nodeById, new Set()) };
}

/**
 * Appends the inactive region after the base graph. The boundary edge
 * (hypothesis_design → protocol_design) carries the activation semantics as a
 * display-only relation; it triggers nothing. A null region returns the base
 * graph untouched (field-for-field identical).
 */
export function composeStageTwoInactiveGraph(
  base: WorkflowLayoutInput,
  region: StageTwoInactiveCanvasRegion | null,
): WorkflowLayoutInput {
  if (!region) {
    return base;
  }
  const nodeById = new Map(
    [...base.nodes, ...region.nodes].map((node) => [node.nodeId, node] as const),
  );
  const boundaryEdge = nodeById.has("hypothesis_design") && nodeById.has("protocol_design")
    ? buildEdgePathStates(
        [{
          edgeId: STAGE_TWO_BOUNDARY_EDGE_ID,
          fromNodeId: "hypothesis_design",
          toNodeId: "protocol_design",
          label: "需按题显式开启",
          gateKind: "knowledge_package",
          semanticKind: "human_gate" as const,
          labelAlwaysVisible: true,
        }],
        nodeById,
        new Set<string>(),
      )
    : [];
  return {
    ...base,
    stages: [
      ...base.stages.map((stage, position) => ({ ...stage, index: position })),
      { ...region.stage, index: base.stages.length },
    ],
    nodes: [...base.nodes, ...region.nodes],
    edges: [...base.edges, ...boundaryEdge, ...region.edges],
  };
}
