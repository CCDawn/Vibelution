/**
 * Knowledge-sideflow canvas region (display layer only).
 *
 * Pure functions — no React, no xyflow. For a run whose pinned definition
 * carries no in-graph knowledge nodes (main 3.0.0), synthesizes the fixed
 * five-node knowledge sideflow as an extra stage band driven only by the
 * snapshot's invocationBadges aggregates. The region never edits execution
 * topology and draws NO permanent main-chain↔sideflow edges: the only
 * relation shown is the single selection-driven temporary line from
 * `knowledgeSideflowRelationEdge` (request out, or write-back into the
 * invocation's own parentNodeId).
 *
 * Precedent: hypothesisFirstCanvasRegion (hf_ prefix → ksf_ prefix).
 */
import type { KnowledgeInvocationBadge, KnowledgeInvocationRecentSummary } from "../../../api/types/research-workflow/core";
import { KNOWLEDGE_SIDEFLOW_NODE_IDS } from "../../../api/types/researchWorkflow";
import type {
  WorkflowCanvasEdgeInput,
  WorkflowCanvasNodeInput,
  WorkflowCanvasStageInput,
  WorkflowNodeRunStatus,
} from "../../../components/vui";
import {
  buildEdgePathStates,
  stageToneFromNodes,
} from "../../../components/vui/product/workflow/workflowCanvasModel";

export const KNOWLEDGE_SIDEFLOW_NODE_PREFIX = "ksf_";
export const KNOWLEDGE_SIDEFLOW_STAGE_ID = "knowledge_sideflow";
export const KNOWLEDGE_SIDEFLOW_STAGE_LABEL = "知识搜集 · 子流程";

/** Fixed display labels mirroring the server sideflow definition order. */
const SIDEFLOW_NODE_LABELS: Record<(typeof KNOWLEDGE_SIDEFLOW_NODE_IDS)[number], string> = {
  source_finding: "资料寻找",
  source_extraction: "资料提炼",
  evidence_relations: "证据关系",
  knowledge_ingestion: "知识入库",
  knowledge_handoff: "知识包交接",
};

const SIDEFLOW_ACTOR_KINDS: Record<(typeof KNOWLEDGE_SIDEFLOW_NODE_IDS)[number], "agent" | "human"> = {
  source_finding: "agent",
  source_extraction: "agent",
  evidence_relations: "agent",
  knowledge_ingestion: "agent",
  knowledge_handoff: "human",
};

/** Canvas node id of one sideflow card (always `ksf_` prefixed). */
export function knowledgeSideflowCanvasNodeId(sideflowNodeId: string): string {
  return `${KNOWLEDGE_SIDEFLOW_NODE_PREFIX}${sideflowNodeId}`;
}

export function isKnowledgeSideflowCanvasNode(nodeId: string | null | undefined): boolean {
  return Boolean(nodeId) && String(nodeId).startsWith(KNOWLEDGE_SIDEFLOW_NODE_PREFIX);
}

/** ksf_<id> → the real sideflow node id; other values pass through untouched. */
export function knowledgeSideflowSemanticNodeId(nodeId: string | null | undefined): string | null {
  const normalized = String(nodeId ?? "").trim();
  if (!normalized.startsWith(KNOWLEDGE_SIDEFLOW_NODE_PREFIX)) return null;
  return normalized.slice(KNOWLEDGE_SIDEFLOW_NODE_PREFIX.length) || null;
}

/** True when the pinned definition carries no in-graph knowledge chain. */
export function definitionNeedsSideflowRegion(definition: {
  nodes: Array<{ nodeId: string }>;
  schemaVersion?: string;
} | null | undefined): boolean {
  if (!definition) return false;
  return !definition.nodes.some((node) => node.nodeId === "knowledge_handoff");
}

export type KnowledgeSideflowCanvasRegion = {
  stage: WorkflowCanvasStageInput;
  nodes: WorkflowCanvasNodeInput[];
  edges: WorkflowCanvasEdgeInput[];
};

/** Maps a raw child-run node attempt status to a canvas card status. */
export function sideflowStatusFromChildNodeState(
  raw: string | undefined,
): WorkflowNodeRunStatus | null {
  const status = String(raw ?? "").trim().toLowerCase();
  if (!status) return null;
  if (status === "succeeded" || status === "completed") return "succeeded";
  if (status === "running" || status === "in_flight") return "running";
  if (status === "failed") return "failed";
  if (status === "blocked") return "blocked";
  return null;
}

function sideflowStatusFor(
  position: number,
  current: KnowledgeInvocationRecentSummary | null,
): WorkflowNodeRunStatus {
  const nodeId = KNOWLEDGE_SIDEFLOW_NODE_IDS[position];
  // Real per-node fact from the child run's latest attempt wins; the
  // invocation-level derivation is only the legacy fallback.
  const fromChild = sideflowStatusFromChildNodeState(current?.childNodeStates?.[nodeId]);
  if (fromChild !== null) {
    if (
      nodeId === "knowledge_handoff"
      && fromChild === "succeeded"
      && String(current?.status ?? "") === "awaiting_handoff"
    ) {
      return "waiting_human";
    }
    return fromChild;
  }
  if (!current?.currentKnowledgeNodeId) return "pending";
  const currentIndex = KNOWLEDGE_SIDEFLOW_NODE_IDS.indexOf(
    current.currentKnowledgeNodeId as (typeof KNOWLEDGE_SIDEFLOW_NODE_IDS)[number],
  );
  if (currentIndex < 0) return "pending";
  if (position < currentIndex) return "succeeded";
  if (position > currentIndex) return "pending";
  const status = String(current.status ?? "");
  if (status === "awaiting_handoff") return "waiting_human";
  if (status === "failed" || status === "cancelled") return "failed";
  if (status === "completed") return "succeeded";
  return "running";
}

function sideflowDescription(
  position: number,
  current: KnowledgeInvocationRecentSummary | null,
): string {
  if (!current) return "尚未发起知识请求";
  const status = String(current.status ?? "");
  if (status === "awaiting_handoff") {
    return position === KNOWLEDGE_SIDEFLOW_NODE_IDS.length - 1
      ? "知识包就绪，等待人工确认交接"
      : "前置步骤已完成，等待交接";
  }
  if (status === "failed") return "知识搜集失败，可在 Inspector 恢复";
  if (status === "completed") return "知识包已回写父运行";
  return "知识搜集进行中";
}

/**
 * Derives the five sideflow card statuses from the latest invocation per
 * parent node. No invocation → all-pending cards (still a truthful statement:
 * the sideflow exists, nothing has been requested yet).
 */
export function sideflowNodeStatesFromBadges(
  badges: Record<string, KnowledgeInvocationBadge> | null | undefined,
): Array<{
  sideflowNodeId: (typeof KNOWLEDGE_SIDEFLOW_NODE_IDS)[number];
  status: WorkflowNodeRunStatus;
  description: string;
  latest: KnowledgeInvocationRecentSummary | null;
}> {
  const latestByRecency = Object.values(badges ?? {})
    .map((badge) => badge.latest)
    .filter((item): item is KnowledgeInvocationRecentSummary => Boolean(item))
    .sort((left, right) => (right.updatedAtMs ?? 0) - (left.updatedAtMs ?? 0));
  const current = latestByRecency[0] ?? null;
  return KNOWLEDGE_SIDEFLOW_NODE_IDS.map((sideflowNodeId, position) => ({
    sideflowNodeId,
    status: sideflowStatusFor(position, current),
    description: sideflowDescription(position, current),
    latest: current,
  }));
}

/** The five card statuses for ONE parent node's badge (inspector progress). */
export function sideflowCardStatesForBadge(
  badge: KnowledgeInvocationBadge | null | undefined,
): Array<{
  sideflowNodeId: (typeof KNOWLEDGE_SIDEFLOW_NODE_IDS)[number];
  status: WorkflowNodeRunStatus;
}> {
  return KNOWLEDGE_SIDEFLOW_NODE_IDS.map((sideflowNodeId, position) => ({
    sideflowNodeId,
    status: sideflowStatusFor(position, badge?.latest ?? null),
  }));
}

export function buildKnowledgeSideflowCanvasRegion(
  badges: Record<string, KnowledgeInvocationBadge> | null | undefined,
): KnowledgeSideflowCanvasRegion | null {
  const states = sideflowNodeStatesFromBadges(badges);
  const hasActivity = states.some(
    (state) => state.latest !== null,
  );
  if (!hasActivity) return null;

  const nodes: WorkflowCanvasNodeInput[] = states.map((state) => ({
    nodeId: knowledgeSideflowCanvasNodeId(state.sideflowNodeId),
    stageId: KNOWLEDGE_SIDEFLOW_STAGE_ID,
    label: SIDEFLOW_NODE_LABELS[state.sideflowNodeId],
    actorKind: SIDEFLOW_ACTOR_KINDS[state.sideflowNodeId],
    visualKind: state.sideflowNodeId === "knowledge_handoff" ? "human_gate" : "agent_task",
    status: state.status,
    description: state.description,
  }));

  // Only the four intra-chain edges.  No permanent main-chain↔sideflow
  // edges: the relation to the main chain is the selection-driven temporary
  // line from `knowledgeSideflowRelationEdge`.
  const edges: Array<WorkflowCanvasEdgeInput> = [];
  for (let index = 0; index < KNOWLEDGE_SIDEFLOW_NODE_IDS.length - 1; index += 1) {
    const from = KNOWLEDGE_SIDEFLOW_NODE_IDS[index];
    const to = KNOWLEDGE_SIDEFLOW_NODE_IDS[index + 1];
    edges.push({
      edgeId: `ksf_e_${from}_${to}`,
      fromNodeId: knowledgeSideflowCanvasNodeId(from),
      toNodeId: knowledgeSideflowCanvasNodeId(to),
      label: "",
      gateKind: "auto",
      semanticKind: "main",
      pathState: "idle",
      labelAlwaysVisible: false,
    });
  }

  const stage: WorkflowCanvasStageInput = {
    stageId: KNOWLEDGE_SIDEFLOW_STAGE_ID,
    label: KNOWLEDGE_SIDEFLOW_STAGE_LABEL,
    nodeIds: nodes.map((node) => node.nodeId),
    index: Number.MAX_SAFE_INTEGER,
    stageTone: stageToneFromNodes(nodes),
  };
  return { stage, nodes, edges };
}

/** Stable edge id of the selection-driven temporary relation line. */
export const KNOWLEDGE_SIDEFLOW_RELATION_EDGE_ID = "ksf_rel_temp";

/**
 * The single temporary relation between the sideflow and the main chain,
 * shown only while a `ksf_` card is selected:
 *
 * - selecting the handoff gate draws the write-back line
 *   `ksf_knowledge_handoff → <parentNodeId>` (label 写回节点) — the
 *   write-back target is the invocation's own parentNodeId, never a fixed
 *   downstream node;
 * - selecting any other sideflow card draws the request line
 *   `<parentNodeId> → <selected ksf node>` (label 知识请求).
 *
 * Endpoint validation is the composer's job (it knows the base+region node
 * set); this helper only derives the edge from the invocation facts.
 */
export function knowledgeSideflowRelationEdge(
  badges: Record<string, KnowledgeInvocationBadge> | null | undefined,
  selectedNodeId: string | null | undefined,
): WorkflowCanvasEdgeInput | null {
  if (!isKnowledgeSideflowCanvasNode(selectedNodeId)) return null;
  const latest = sideflowNodeStatesFromBadges(badges)
    .map((state) => state.latest)
    .filter((item): item is KnowledgeInvocationRecentSummary => Boolean(item))
    .sort((left, right) => (right.updatedAtMs ?? 0) - (left.updatedAtMs ?? 0))[0];
  if (!latest?.parentNodeId) return null;
  const selected = String(selectedNodeId);
  const parentNodeId = latest.parentNodeId;
  if (knowledgeSideflowSemanticNodeId(selected) === "knowledge_handoff") {
    return {
      edgeId: KNOWLEDGE_SIDEFLOW_RELATION_EDGE_ID,
      fromNodeId: knowledgeSideflowCanvasNodeId("knowledge_handoff"),
      toNodeId: parentNodeId,
      label: "写回节点",
      gateKind: "knowledge_package",
      semanticKind: "main",
      pathState: "idle",
      labelAlwaysVisible: true,
    };
  }
  return {
    edgeId: KNOWLEDGE_SIDEFLOW_RELATION_EDGE_ID,
    fromNodeId: parentNodeId,
    toNodeId: selected,
    label: "知识请求",
    gateKind: "auto",
    semanticKind: "main",
    pathState: "idle",
    labelAlwaysVisible: true,
  };
}

/**
 * Appends the sideflow region after the base graph's own stages. Boundary
 * edges only survive when both endpoints exist (e.g. the hypothesis-first
 * compose may have hidden the downstream pipeline). Null region is a no-op
 * that returns the base graph field-for-field identical. When
 * `relationEdge` is given (the selection-driven temporary line), it joins
 * the region edges for path-state resolution and is dropped when either
 * endpoint is missing.
 */
export function composeKnowledgeSideflowGraph(
  base: import("../../../components/vui").WorkflowLayoutInput,
  region: KnowledgeSideflowCanvasRegion | null,
  relationEdge?: WorkflowCanvasEdgeInput | null,
): import("../../../components/vui").WorkflowLayoutInput {
  if (!region) {
    return base;
  }
  const nodeById = new Map(
    [...base.nodes, ...region.nodes].map((node) => [node.nodeId, node] as const),
  );
  const runtimeCurrent = new Set(base.run?.runtimeCurrentNodeIds ?? []);
  const regionEdges = buildEdgePathStates(
    [...(relationEdge ? [relationEdge] : []), ...region.edges]
      .filter((edge) => nodeById.has(edge.fromNodeId) && nodeById.has(edge.toNodeId))
      .map((edge) => ({ ...edge, pathState: undefined })),
    nodeById,
    runtimeCurrent,
  );
  const existingStageIds = new Set(base.stages.map((stage) => stage.stageId));
  const regionStage = existingStageIds.has(region.stage.stageId)
    ? region.stage
    : { ...region.stage, index: base.stages.length };
  return {
    ...base,
    stages: existingStageIds.has(region.stage.stageId)
      ? base.stages
      : [...base.stages, regionStage],
    nodes: [...base.nodes, ...region.nodes],
    edges: [...base.edges, ...regionEdges],
  };
}
