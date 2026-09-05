/**
 * Hypothesis-first canvas region (display layer only, design contract §3.2/§3.3).
 *
 * Pure functions — no React, no xyflow. Synthesizes a "假说先行" stage fragment
 * (WorkflowLayoutInput slice) from the hypothesis-first chain ledger: selection
 * record, review meetings, collection requests and review-round links. The
 * region never changes execution topology; it only projects ledger facts onto
 * the canvas. Gate edges point at the main graph (`source_finding` /
 * `hypothesis_design`) and are re-resolved by `composeHypothesisFirstGraph`.
 */
import type {
  HypothesisFirstStateV2,
  PhaseState,
  MeetingRoundRecord,
} from "../../../api/types/hypothesisFirst";
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

export const HYPOTHESIS_FIRST_NODE_PREFIX = "hf_";
export const HYPOTHESIS_FIRST_STAGE_ID = "hypothesis_first";
export const HYPOTHESIS_FIRST_STAGE_LABEL = "假说先行";
export const HYPOTHESIS_FIRST_GENERATION_NODE_ID = "hf_generation";
export const HYPOTHESIS_FIRST_SELECTION_NODE_ID = "hf_selection";
export const HYPOTHESIS_FIRST_REVIEW_NODE_ID = "hf_review";
export const HYPOTHESIS_FIRST_COLLECTION_NODE_ID = "hf_collection";
export const HYPOTHESIS_FIRST_CONVERGENCE_NODE_ID = "hf_convergence_gate";
export const HYPOTHESIS_FIRST_STAGE1_EDGE_ID = "hf_e_m1_stage1";
export const HYPOTHESIS_FIRST_STAGE2_EDGE_ID = "hf_e_gate_stage2";

/** Review meetings of the hypothesis-first chain carry this meetingType. */
const HYPOTHESIS_REVIEW_MEETING_TYPE = "hypothesis_review";

export type HypothesisFirstCanvasRegionInput = {
  stateV2: HypothesisFirstStateV2 | null;
  meetings: MeetingRoundRecord[];

};

export type HypothesisFirstCanvasRegion = {
  stage: WorkflowCanvasStageInput;
  nodes: WorkflowCanvasNodeInput[];
  edges: WorkflowCanvasEdgeInput[];
  /**
   * Downstream 16-node pipeline is noise until the first review round has
   * actually closed or a collection request exists. Compose hides it until then.
   */
  showDownstreamPipeline: boolean;
};

/** Canvas node ids of the hypothesis-first region always carry the `hf_` prefix. */
export function isHypothesisFirstCanvasNode(nodeId: string | null | undefined): boolean {
  return Boolean(nodeId) && String(nodeId).startsWith(HYPOTHESIS_FIRST_NODE_PREFIX);
}

/** Maps ledger-instance ids to the stable semantic cards shown on the canvas. */
export function hypothesisFirstSemanticNodeId(nodeId: string | null | undefined): string | null {
  const normalized = String(nodeId ?? "").trim();
  if (!normalized) return null;
  if (normalized.startsWith("hf_meeting_")) return HYPOTHESIS_FIRST_REVIEW_NODE_ID;
  if (normalized.startsWith("hf_collection_") || normalized === "source_finding") {
    return HYPOTHESIS_FIRST_COLLECTION_NODE_ID;
  }
  return normalized;
}

function sameQuestion(left: string | undefined, right: string): boolean {
  return String(left ?? "").trim().toUpperCase() === right.trim().toUpperCase();
}

// The ledger writes `digestId`; `digestRef` only ever existed in this
// frontend's type and stayed undefined, which made every closed review round
// render as a blocked "missing digest" card.
function meetingHasDigest(meeting: MeetingRoundRecord): boolean {
  return Boolean(meeting.digestId || meeting.digestRef);
}

/** Display the canonical phase without deriving lifecycle from auxiliary records. */
function phaseCanvasStatus(phase: PhaseState): WorkflowNodeRunStatus {
  if (phase.lifecycle === "cancelled" || phase.lifecycle === "superseded") return "cancelled";
  if (phase.lifecycle === "failed") return "failed";
  if (phase.actionability === "blocked" || phase.outcome === "exhausted") return "blocked";
  if (phase.lifecycle === "completed" && phase.outcome === "succeeded") return "succeeded";
  if (phase.lifecycle === "waiting_human" || phase.actionability === "waiting_user") return "waiting_human";
  if (phase.lifecycle === "running") return "running";
  return "pending";
}

function phaseDescription(phase: PhaseState): string {
  const problem = phase.problems[0]?.message;
  if (problem) return problem;
  switch (phaseCanvasStatus(phase)) {
    case "running": return "正在执行";
    case "waiting_human": return "等待人工确认";
    case "blocked": return "当前步骤已阻塞";
    case "failed": return "当前步骤执行失败";
    case "cancelled": return "当前步骤已停止";
    case "succeeded": return "当前步骤已完成";
    default: return "等待开始";
  }
}

export function isHypothesisReviewRetryAttempt(meeting: MeetingRoundRecord): boolean {
  return meeting.status === "closed"
    && (meeting.recoveryReason === "discussion_has_no_completed_messages" || !meetingHasDigest(meeting));
}

export type HypothesisReviewSummary = {
  effectiveRounds: number;
  retryAttempts: number;
  /** Max known logical round; 0 means the round number is unknown (legacy data). */
  latestRound: number;
  /**
   * False when effective review meetings exist but none carries a readable
   * roundIndex (legacy data), so the effective count would be an undercount.
   */
  effectiveRoundsKnown: boolean;
};

/** Only a positive finite roundIndex counts as a known logical round. */
function readableRoundIndex(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) && value >= 1 ? value : 0;
}

/**
 * Round numbers come only from real roundIndex values (review-round links /
 * the V2 snapshot). Legacy meetings without one must not fabricate rounds from
 * list position: one logical round fans out into several physical meetings, so
 * position-based numbers inflate both counts. `canonicalRound`
 * (V2 review.activeRoundIndex) anchors both numbers when present — effective
 * rounds can never exceed the current canonical round, which also absorbs
 * legacy per-candidate roundIndex writes.
 */
export function summarizeHypothesisReviewMeetings(
  meetings: readonly MeetingRoundRecord[],
  canonicalRound?: number | null,
): HypothesisReviewSummary {
  const reviewMeetings = sortMeetings(
    meetings.filter((meeting) => meeting.meetingType === HYPOTHESIS_REVIEW_MEETING_TYPE),
  );
  const canonical = readableRoundIndex(canonicalRound);
  const effectiveMeetings = reviewMeetings.filter(
    (meeting) => !isHypothesisReviewRetryAttempt(meeting),
  );
  const effectiveRoundIndexes = new Set(
    effectiveMeetings
      .map((meeting) => readableRoundIndex(meeting.roundIndex))
      .filter((round) => round > 0),
  );
  const maxKnownRound = reviewMeetings.reduce(
    (max, meeting) => Math.max(max, readableRoundIndex(meeting.roundIndex)),
    0,
  );
  return {
    effectiveRounds: canonical > 0
      ? Math.min(effectiveRoundIndexes.size, canonical)
      : effectiveRoundIndexes.size,
    retryAttempts: reviewMeetings.filter(isHypothesisReviewRetryAttempt).length,
    // The canonical round is the server-owned upper bound; meeting roundIndex
    // values above it are legacy per-candidate inflation, never displayed.
    latestRound: canonical > 0 ? canonical : maxKnownRound,
    // Zero effective meetings is a real zero; effective meetings without any
    // readable roundIndex leave the count unknowable.
    effectiveRoundsKnown: effectiveMeetings.length === 0 || effectiveRoundIndexes.size > 0,
  };
}

function cardProgress(nodes: WorkflowCanvasNodeInput[]): { completed: number; total: number } {
  const total = nodes.length;
  const completed = nodes.filter((node) => node.status === "succeeded" || node.status === "skipped").length;
  return { completed, total };
}

function sortMeetings(meetings: MeetingRoundRecord[]): MeetingRoundRecord[] {
  return [...meetings].sort((left, right) => {
    const leftIndex = left.roundIndex ?? Number.MAX_SAFE_INTEGER;
    const rightIndex = right.roundIndex ?? Number.MAX_SAFE_INTEGER;
    if (leftIndex !== rightIndex) return leftIndex - rightIndex;
    const byStarted = String(left.startedAt ?? "").localeCompare(String(right.startedAt ?? ""));
    if (byStarted !== 0) return byStarted;
    return left.meetingRoundId.localeCompare(right.meetingRoundId);
  });
}

/**
 * Builds the hypothesis-first stage fragment.  The region renders whenever the
 * question has a chain state (i.e. a catalog question is in view).  Before
 * any ledger activity exists, the candidate-generation card is the first
 * card, so the canvas states the real first action instead of asking a user
 * to infer it from a pending selection card.  Later states keep their compact
 * historical shape.
 */
export function buildHypothesisFirstCanvasRegion(
  input: HypothesisFirstCanvasRegionInput,
): HypothesisFirstCanvasRegion | null {
  const { stateV2 } = input;
  if (!stateV2 || !stateV2.questionId) {
    return null;
  }
  const questionId = stateV2.questionId;

  const meetings = sortMeetings(
    input.meetings.filter(
      (meeting) =>
        meeting.meetingType === HYPOTHESIS_REVIEW_MEETING_TYPE
        && sameQuestion(meeting.question, questionId),
    ),
  );
  const selection = stateV2.selection.selectionId ? stateV2.selection : null;

  const nodes: WorkflowCanvasNodeInput[] = [];
  const edges: Array<Omit<WorkflowCanvasEdgeInput, "pathState"> & { pathState?: WorkflowCanvasEdgeInput["pathState"] }> = [];

  // --- cards ---------------------------------------------------------------
  const candidateCount = stateV2.generation.candidateCount ?? 0;
  const showGenerationCard = Boolean(
    stateV2.generation.generationMeetingId || candidateCount > 0 || !selection,
  );
  if (showGenerationCard) {
    nodes.push({
      nodeId: HYPOTHESIS_FIRST_GENERATION_NODE_ID,
      stageId: HYPOTHESIS_FIRST_STAGE_ID,
      label: "候选假说生成",
      actorKind: "agent",
      visualKind: "agent_task",
      status: phaseCanvasStatus(stateV2.generation),
      description: stateV2.generation.lifecycle === "completed" && candidateCount > 0
        ? `已产出 ${candidateCount} 条候选假说` : phaseDescription(stateV2.generation),
    });
  }
  nodes.push({
    nodeId: HYPOTHESIS_FIRST_SELECTION_NODE_ID,
    stageId: HYPOTHESIS_FIRST_STAGE_ID,
    label: "假说选择",
    actorKind: "human",
    visualKind: "human_gate",
    status: phaseCanvasStatus(stateV2.selection),
    description: selection
      ? `已选 ${selection.selectedCandidateIds.length} 个候选假说`
      : phaseDescription(stateV2.selection),
  });

  if (showGenerationCard) {
    edges.push({
      edgeId: "hf_e_gen_sel",
      fromNodeId: HYPOTHESIS_FIRST_GENERATION_NODE_ID,
      toNodeId: HYPOTHESIS_FIRST_SELECTION_NODE_ID,
      label: "产出候选",
      gateKind: "auto",
      semanticKind: "main",
      labelAlwaysVisible: true,
    });
  }

  const reviewSummary = summarizeHypothesisReviewMeetings(meetings, stateV2.review.activeRoundIndex);
  const latestReview = meetings[meetings.length - 1];
  const showReview = Boolean(selection || stateV2.review.lifecycle !== "not_started" || stateV2.review.candidates.length);
  if (showReview) {
    // latestRound > 0 iff any real round number (roundIndex / canonical) is
    // known; effectiveRoundsKnown is false when legacy meetings leave the
    // effective count unknowable — degrade to "unknown" over fabricated numbers.
    const summaryParts = latestReview
      ? [
          reviewSummary.effectiveRoundsKnown
            ? `${reviewSummary.effectiveRounds} 轮有效评审`
            : "有效轮数未知",
          `${reviewSummary.retryAttempts} 次失败重试`,
          reviewSummary.latestRound > 0
            ? `最近第 ${reviewSummary.latestRound} 轮`
            : "最近轮次未知",
        ]
      : [phaseDescription(stateV2.review)];
    nodes.push({
      nodeId: HYPOTHESIS_FIRST_REVIEW_NODE_ID,
      stageId: HYPOTHESIS_FIRST_STAGE_ID,
      label: "假说评审",
      actorKind: "agent",
      visualKind: "agent_task",
      status: phaseCanvasStatus(stateV2.review),
      description: summaryParts.join(" · "),
    });
  }

  const latestRequest = stateV2.collection.requests[0];
  const showCollection = Boolean(latestRequest || stateV2.collection.lifecycle !== "not_started");
  if (showCollection) {
    nodes.push({
      nodeId: HYPOTHESIS_FIRST_COLLECTION_NODE_ID,
      stageId: HYPOTHESIS_FIRST_STAGE_ID,
      label: "资料补充",
      actorKind: "system",
      visualKind: "system_task",
      status: phaseCanvasStatus(stateV2.collection),
      description: `${stateV2.collection.aggregate.total} 个资料请求 · ${phaseDescription(stateV2.collection)}`,
    });
  }

  const showConvergence = stateV2.convergence.lifecycle !== "not_started"
    || stateV2.convergence.accepted || stateV2.convergence.outcome === "exhausted"
    || stateV2.review.lifecycle === "completed";
  const showDownstreamPipeline = stateV2.review.lifecycle === "completed"
    || showCollection || stateV2.convergence.accepted || Boolean(stateV2.formalRuntime.runId);

  if (showConvergence) {
    nodes.push({
      nodeId: HYPOTHESIS_FIRST_CONVERGENCE_NODE_ID,
      stageId: HYPOTHESIS_FIRST_STAGE_ID,
      label: "假说收敛门",
      actorKind: "human",
      // human_gate, not decision: the VUI decision kind is hardwired to the
      // iteration decision's five-outcome port/handle contract (workflowElkPorts
      // fail-fast), while this gate has a single proceed exit and a human
      // decision semantic when blocked — same shape as candidate_promotion.
      visualKind: "human_gate",
      status: phaseCanvasStatus(stateV2.convergence),
      description: stateV2.convergence.problems[0]?.message
        || (stateV2.convergence.accepted
          ? "假说集已收敛"
          : (stateV2.convergence.outcome === "exhausted")
            ? "轮次预算耗尽，等待人工决策"
            : "待收敛"),
    });
  }

  // --- semantic task edges -------------------------------------------------
  // Attempt/round/request lineage remains in the read-only Inspector history;
  // the canvas communicates stable work categories instead of ledger rows.
  if (selection && showReview) {
    edges.push({
      edgeId: "hf_e_sel_review",
      fromNodeId: HYPOTHESIS_FIRST_SELECTION_NODE_ID,
      toNodeId: HYPOTHESIS_FIRST_REVIEW_NODE_ID,
      label: "选定假说",
      gateKind: "auto",
      semanticKind: "decision_branch",
      labelAlwaysVisible: true,
    });
  }
  if (showReview && showCollection) {
    edges.push({
      edgeId: "hf_e_review_collection",
      fromNodeId: HYPOTHESIS_FIRST_REVIEW_NODE_ID,
      toNodeId: HYPOTHESIS_FIRST_COLLECTION_NODE_ID,
      label: "补充证据",
      gateKind: "knowledge_package",
      semanticKind: "main",
      labelAlwaysVisible: true,
    });
  }
  const semanticTailNodeId = showCollection
    ? HYPOTHESIS_FIRST_COLLECTION_NODE_ID
    : showReview
      ? HYPOTHESIS_FIRST_REVIEW_NODE_ID
      : null;
  if (semanticTailNodeId && showConvergence) {
    edges.push({
      edgeId: "hf_e_semantic_tail_gate",
      fromNodeId: semanticTailNodeId,
      toNodeId: HYPOTHESIS_FIRST_CONVERGENCE_NODE_ID,
      label: "",
      gateKind: "auto",
      semanticKind: "main",
      labelAlwaysVisible: false,
    });
  }
  if (showReview && showDownstreamPipeline) {
    edges.push({
      edgeId: HYPOTHESIS_FIRST_STAGE1_EDGE_ID,
      fromNodeId: HYPOTHESIS_FIRST_REVIEW_NODE_ID,
      toNodeId: "source_finding",
      label: "首轮搜集范围就绪",
      gateKind: "knowledge_package",
      semanticKind: "human_gate",
      labelAlwaysVisible: true,
    });
  }
  if (showConvergence) {
    edges.push({
      edgeId: HYPOTHESIS_FIRST_STAGE2_EDGE_ID,
      fromNodeId: HYPOTHESIS_FIRST_CONVERGENCE_NODE_ID,
      toNodeId: "hypothesis_design",
      label: "假说集就绪",
      gateKind: "knowledge_package",
      semanticKind: "human_gate",
      labelAlwaysVisible: true,
    });
  }

  const nodeById = new Map(nodes.map((node) => [node.nodeId, node] as const));
  const resolvedEdges = buildEdgePathStates(edges, nodeById, new Set());

  const stage: WorkflowCanvasStageInput = {
    stageId: HYPOTHESIS_FIRST_STAGE_ID,
    label: HYPOTHESIS_FIRST_STAGE_LABEL,
    nodeIds: nodes.map((node) => node.nodeId),
    index: 0,
    stageTone: stageToneFromNodes(nodes),
    progress: cardProgress(nodes),
  };

  return { stage, nodes, edges: resolvedEdges, showDownstreamPipeline };
}
