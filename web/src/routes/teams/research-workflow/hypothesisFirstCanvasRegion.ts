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
  CollectionRequestRecord,
  HypothesisFirstChainState,
  HypothesisSelectionRecord,
  MeetingRoundRecord,
  ReviewRoundLinkRecord,
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
export const HYPOTHESIS_FIRST_CONVERGENCE_NODE_ID = "hf_convergence_gate";
export const HYPOTHESIS_FIRST_STAGE1_EDGE_ID = "hf_e_m1_stage1";
export const HYPOTHESIS_FIRST_STAGE2_EDGE_ID = "hf_e_gate_stage2";

/** Review meetings of the hypothesis-first chain carry this meetingType. */
const HYPOTHESIS_REVIEW_MEETING_TYPE = "hypothesis_review";
/** Round-0 candidate-generation discussions carry this meetingType. */
const CANDIDATE_GENERATION_MEETING_TYPE = "hypothesis_candidate_generation";

export type HypothesisFirstCanvasRegionInput = {
  chainState: HypothesisFirstChainState | null;
  meetings: MeetingRoundRecord[];
  collectionRequests: CollectionRequestRecord[];
  reviewRoundLinks: ReviewRoundLinkRecord[];
  selection: HypothesisSelectionRecord | null;
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

function sameQuestion(left: string | undefined, right: string): boolean {
  return String(left ?? "").trim().toUpperCase() === right.trim().toUpperCase();
}

// The ledger writes `digestId`; `digestRef` only ever existed in this
// frontend's type and stayed undefined, which made every closed review round
// render as a blocked "missing digest" card.
function meetingHasDigest(meeting: MeetingRoundRecord): boolean {
  return Boolean(meeting.digestId || meeting.digestRef);
}

function meetingNodeStatus(meeting: MeetingRoundRecord): WorkflowNodeRunStatus {
  switch (meeting.status) {
    case "open":
      return "running";
    case "summarizing":
    case "awaiting_approval":
      return "waiting_human";
    case "closed":
      // fail-closed: a closed round without a digest is NOT a success.
      return meetingHasDigest(meeting) ? "succeeded" : "blocked";
    default:
      return "pending";
  }
}

function meetingNodeDescription(meeting: MeetingRoundRecord): string {
  switch (meeting.status) {
    case "open":
      return "讨论进行中";
    case "summarizing":
      return "正在整理本轮讨论结论";
    case "awaiting_approval":
      return "等待人工确认闭环";
    case "closed":
      return meetingHasDigest(meeting) ? "已闭环" : "已关闭但缺少纪要（fail-closed）";
    default:
      return "待开始";
  }
}

function collectionNodeStatus(request: CollectionRequestRecord): WorkflowNodeRunStatus {
  if (request.handoffRef || request.handedOffAt || request.status === "handed_off") {
    return "succeeded";
  }
  if (request.status === "failed") {
    return "failed";
  }
  if (request.status === "running" || request.status === "collecting" || request.status === "in_progress") {
    return "running";
  }
  // Record-level statuses are pending / handed_off; unknown values stay pending.
  return "pending";
}

function collectionNodeDescription(request: CollectionRequestRecord): string {
  const status = collectionNodeStatus(request);
  if (status === "succeeded") return "知识包已交接";
  if (status === "failed") return "搜集子运行失败";
  if (status === "running") return "搜集子运行在途";
  return request.collectionRunId ? "搜集子运行已触发，等待完成" : "等待搜集子运行";
}

function convergenceNodeStatus(chainState: HypothesisFirstChainState): WorkflowNodeRunStatus {
  if (chainState.hypothesisConverged) return "succeeded";
  if (chainState.budgetExhausted) return "blocked";
  return "pending";
}

function cardProgress(nodes: WorkflowCanvasNodeInput[]): { completed: number; total: number } {
  const total = nodes.length;
  const completed = nodes.filter((node) => node.status === "succeeded" || node.status === "skipped").length;
  return { completed, total };
}

function hasClosedReviewRound(meetings: MeetingRoundRecord[]): boolean {
  return meetings.some((meeting) => meeting.status === "closed");
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

function sortRequests(requests: CollectionRequestRecord[]): CollectionRequestRecord[] {
  return [...requests].sort((left, right) => {
    const byCreated = String(left.createdAt ?? "").localeCompare(String(right.createdAt ?? ""));
    if (byCreated !== 0) return byCreated;
    return left.requestId.localeCompare(right.requestId);
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
  const { chainState } = input;
  if (!chainState || !chainState.questionId) {
    return null;
  }
  const questionId = chainState.questionId;

  const generationMeetings = sortMeetings(
    input.meetings.filter(
      (meeting) =>
        meeting.meetingType === CANDIDATE_GENERATION_MEETING_TYPE
        && sameQuestion(meeting.question, questionId),
    ),
  );
  const meetings = sortMeetings(
    input.meetings.filter(
      (meeting) =>
        meeting.meetingType === HYPOTHESIS_REVIEW_MEETING_TYPE
        && sameQuestion(meeting.question, questionId),
    ),
  );
  const requests = sortRequests(
    input.collectionRequests.filter((request) => sameQuestion(request.questionId, questionId)),
  );
  const links = input.reviewRoundLinks.filter((link) => sameQuestion(link.questionId, questionId));
  const selection = input.selection && sameQuestion(input.selection.questionId, questionId)
    ? input.selection
    : null;

  const nodes: WorkflowCanvasNodeInput[] = [];
  const edges: Array<Omit<WorkflowCanvasEdgeInput, "pathState"> & { pathState?: WorkflowCanvasEdgeInput["pathState"] }> = [];

  // --- cards ---------------------------------------------------------------
  const candidateCount = chainState.candidateCount ?? 0;
  const generationMeeting = generationMeetings[generationMeetings.length - 1];
  const showGenerationCard = Boolean(
    generationMeeting || candidateCount > 0 || (!selection && meetings.length === 0),
  );
  if (showGenerationCard) {
    const generationStatus = generationMeeting
      ? meetingNodeStatus(generationMeeting)
      : candidateCount > 0
        ? "succeeded"
        : "waiting_human";
    nodes.push({
      nodeId: HYPOTHESIS_FIRST_GENERATION_NODE_ID,
      stageId: HYPOTHESIS_FIRST_STAGE_ID,
      label: "候选假说生成",
      actorKind: "agent",
      visualKind: "agent_task",
      status: generationStatus,
      description: generationMeeting
        ? generationMeeting.status === "closed"
          ? `已产出 ${candidateCount} 条候选假说`
          : meetingNodeDescription(generationMeeting)
        : candidateCount > 0
          ? `已产出 ${candidateCount} 条候选假说`
        : "尚未生成候选假说，点击卡片打开操作",
    });
  }
  nodes.push({
    nodeId: HYPOTHESIS_FIRST_SELECTION_NODE_ID,
    stageId: HYPOTHESIS_FIRST_STAGE_ID,
    label: "假说选择",
    actorKind: "human",
    visualKind: "human_gate",
    status: selection ? "succeeded" : candidateCount > 0 ? "waiting_human" : "pending",
    description: selection
      ? `已选 ${selection.selectedCandidateIds.length} 个候选假说`
      : candidateCount > 0
        ? `已产出 ${candidateCount} 条候选，等待人工选择`
        : generationMeeting
          ? "候选生成讨论进行中，产出后可选择"
          : "等待生成候选假说",
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

  const roundIndexByMeetingId = new Map<string, number>();
  meetings.forEach((meeting, position) => {
    roundIndexByMeetingId.set(meeting.meetingRoundId, meeting.roundIndex ?? position + 1);
  });
  const meetingNodeId = (meetingRoundId: string): string =>
    `hf_meeting_${roundIndexByMeetingId.get(meetingRoundId) ?? 0}`;

  // GitHub Actions / Temporal attempt pattern: a discussion round that never
  // produced a usable outcome — abandoned with zero completed speeches, or
  // closed without a digest — is a failed *attempt* of the review, not a peer
  // round. Fold such rounds into the next effective round's node as a retry
  // count instead of stacking error-state cards on the canvas.
  const isSupersededAttempt = (meeting: MeetingRoundRecord): boolean =>
    meeting.status === "closed"
    && (meeting.recoveryReason === "discussion_has_no_completed_messages" || !meetingHasDigest(meeting));
  const effectiveMeetings = meetings.filter((meeting) => !isSupersededAttempt(meeting));
  const lastEffectiveRound = effectiveMeetings.reduce(
    (max, meeting) => Math.max(max, roundIndexByMeetingId.get(meeting.meetingRoundId) ?? 0),
    0,
  );
  // A trailing superseded round (reopen failed / not yet run) stays visible so
  // the chain keeps a tail to act on; only rounds absorbed by a successor fold.
  const visibleMeetings = [
    ...effectiveMeetings,
    ...meetings.filter(
      (meeting) =>
        isSupersededAttempt(meeting)
        && (roundIndexByMeetingId.get(meeting.meetingRoundId) ?? 0) > lastEffectiveRound,
    ),
  ].sort(
    (left, right) =>
      (roundIndexByMeetingId.get(left.meetingRoundId) ?? 0)
      - (roundIndexByMeetingId.get(right.meetingRoundId) ?? 0),
  );
  const retryCountByMeetingId = new Map<string, number>();
  for (const meeting of visibleMeetings) {
    if (isSupersededAttempt(meeting)) continue;
    const roundIndex = roundIndexByMeetingId.get(meeting.meetingRoundId) ?? 0;
    const previousVisibleRound = Math.max(
      0,
      ...visibleMeetings
        .filter(
          (other) =>
            !isSupersededAttempt(other)
            && (roundIndexByMeetingId.get(other.meetingRoundId) ?? 0) < roundIndex,
        )
        .map((other) => roundIndexByMeetingId.get(other.meetingRoundId) ?? 0),
    );
    const absorbed = meetings.filter(
      (other) =>
        isSupersededAttempt(other)
        && (roundIndexByMeetingId.get(other.meetingRoundId) ?? 0) < roundIndex
        && (roundIndexByMeetingId.get(other.meetingRoundId) ?? 0) > previousVisibleRound,
    ).length;
    if (absorbed > 0) retryCountByMeetingId.set(meeting.meetingRoundId, absorbed);
  }

  for (const meeting of visibleMeetings) {
    const roundIndex = roundIndexByMeetingId.get(meeting.meetingRoundId)!;
    const retries = retryCountByMeetingId.get(meeting.meetingRoundId) ?? 0;
    const baseDescription = isSupersededAttempt(meeting)
      ? (meeting.recoveryReason === "discussion_has_no_completed_messages"
        ? "发言失败已跳过，等待重试"
        : "已关闭但缺少纪要，等待重试")
      : meetingNodeDescription(meeting);
    nodes.push({
      nodeId: `hf_meeting_${roundIndex}`,
      stageId: HYPOTHESIS_FIRST_STAGE_ID,
      label: `第 ${roundIndex} 轮讨论·评审`,
      actorKind: "agent",
      visualKind: "agent_task",
      status: isSupersededAttempt(meeting) ? "blocked" : meetingNodeStatus(meeting),
      description: retries > 0 ? `含 ${retries} 次失败重试 · ${baseDescription}` : baseDescription,
    });
  }

  const requestNodeId = (requestId: string): string => `hf_collection_${requestId}`;
  const requestIndexById = new Map<string, number>();
  requests.forEach((request, position) => {
    requestIndexById.set(request.requestId, position + 1);
  });
  // Only ledger-consistent requests get a card: the triggering meeting must be
  // a visible round in scope (superseded attempts never trigger collection),
  // otherwise the card would dangle without its decision edge.
  const cardedRequests = requests.filter((request) =>
    visibleMeetings.some((meeting) => meeting.meetingRoundId === request.meetingRoundId));
  for (const request of cardedRequests) {
    const gapIndex = requestIndexById.get(request.requestId)!;
    nodes.push({
      nodeId: requestNodeId(request.requestId),
      stageId: HYPOTHESIS_FIRST_STAGE_ID,
      label: `资料搜集 · 缺口 ${gapIndex}`,
      actorKind: "system",
      visualKind: "system_task",
      status: collectionNodeStatus(request),
      description: collectionNodeDescription(request),
    });
  }

  const showConvergence = chainState.hypothesisConverged
    || chainState.budgetExhausted
    || hasClosedReviewRound(meetings);
  const showDownstreamPipeline = chainState.firstMeetingClosed
    || chainState.collectionReady
    || chainState.hypothesisConverged
    || requests.length > 0
    || hasClosedReviewRound(meetings);

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
      status: convergenceNodeStatus(chainState),
      description: chainState.convergenceDetail
        || (chainState.hypothesisConverged
          ? "假说集已收敛"
          : chainState.budgetExhausted
            ? "轮次预算耗尽，等待人工决策"
            : "待收敛"),
    });
  }

  // --- edges (only associations that really exist in the ledger) -----------
  const firstMeeting = visibleMeetings[0];
  const lastMeeting = visibleMeetings[visibleMeetings.length - 1];
  if (selection && firstMeeting) {
    edges.push({
      edgeId: "hf_e_sel_m1",
      fromNodeId: HYPOTHESIS_FIRST_SELECTION_NODE_ID,
      toNodeId: meetingNodeId(firstMeeting.meetingRoundId),
      label: "选定假说",
      gateKind: "auto",
      // decision_branch (not main): the selection is the human's branch into
      // round 1, and the narrative kinds are the only ones whose labels stay
      // visible in serpentine mode (workflowEdgeKeepsNarrativeLabel).
      semanticKind: "decision_branch",
      labelAlwaysVisible: true,
    });
  }

  const cardedRequestIds = new Set(cardedRequests.map((request) => request.requestId));
  for (const request of cardedRequests) {
    edges.push({
      edgeId: `hf_e_m${roundIndexByMeetingId.get(request.meetingRoundId)}_c${request.requestId}`,
      fromNodeId: meetingNodeId(request.meetingRoundId),
      toNodeId: requestNodeId(request.requestId),
      label: "搜集决策",
      gateKind: "auto",
      semanticKind: "decision_branch",
      labelAlwaysVisible: true,
    });
  }

  const visibleMeetingIds = new Set(visibleMeetings.map((meeting) => meeting.meetingRoundId));
  const linkByTargetMeetingId = new Map<string, ReviewRoundLinkRecord>();
  for (const link of links) {
    linkByTargetMeetingId.set(link.meetingRoundId, link);
  }
  for (const link of links) {
    // A recorded link IS the handoff fact: draw collection → next meeting.
    if (!visibleMeetingIds.has(link.meetingRoundId) || !cardedRequestIds.has(link.collectionRequestId)) {
      continue;
    }
    edges.push({
      edgeId: `hf_e_c${link.collectionRequestId}_m${roundIndexByMeetingId.get(link.meetingRoundId)}`,
      fromNodeId: requestNodeId(link.collectionRequestId),
      toNodeId: meetingNodeId(link.meetingRoundId),
      label: "知识包交接",
      // knowledge_package gate: the handoff literally carries the knowledge
      // package, and the gate kind keeps the label visible in serpentine mode.
      gateKind: "knowledge_package",
      semanticKind: "main",
      labelAlwaysVisible: true,
    });
  }

  for (const meeting of visibleMeetings) {
    if (meeting.meetingRoundId === firstMeeting?.meetingRoundId) {
      continue;
    }
    if (linkByTargetMeetingId.has(meeting.meetingRoundId)) {
      continue; // collection-bridged continuation already drawn
    }
    // The lineage ref may point at a folded (superseded) attempt; hop over it
    // to the nearest visible predecessor so the edge always binds two cards.
    const previousId = meeting.previousMeetingRoundId && visibleMeetingIds.has(meeting.previousMeetingRoundId)
      ? meeting.previousMeetingRoundId
      : visibleMeetings[visibleMeetings.indexOf(meeting) - 1]?.meetingRoundId;
    if (!previousId) {
      continue;
    }
    edges.push({
      edgeId: `hf_e_m${roundIndexByMeetingId.get(previousId)}_m${roundIndexByMeetingId.get(meeting.meetingRoundId)}`,
      fromNodeId: meetingNodeId(previousId),
      toNodeId: meetingNodeId(meeting.meetingRoundId),
      label: "再讨论",
      gateKind: "auto",
      semanticKind: "main",
      labelAlwaysVisible: false,
    });
  }

  if (lastMeeting && showConvergence) {
    edges.push({
      edgeId: `hf_e_m${roundIndexByMeetingId.get(lastMeeting.meetingRoundId)}_gate`,
      fromNodeId: meetingNodeId(lastMeeting.meetingRoundId),
      toNodeId: HYPOTHESIS_FIRST_CONVERGENCE_NODE_ID,
      label: "",
      gateKind: "auto",
      semanticKind: "main",
      labelAlwaysVisible: false,
    });
  }
  if (lastMeeting && showDownstreamPipeline) {
    edges.push({
      edgeId: HYPOTHESIS_FIRST_STAGE1_EDGE_ID,
      fromNodeId: meetingNodeId(firstMeeting!.meetingRoundId),
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
