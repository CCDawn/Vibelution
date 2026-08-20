/**
 * Typed next-step model for the hypothesis-first canvas.
 *
 * Toolbar consumes navigation fields only. Inspector consumes command fields.
 * The two surfaces must never share the same button copy for navigate vs write.
 */
import type {
  CollectionRequestRecord,
  HypothesisFirstChainState,
  HypothesisSelectionRecord,
  MeetingDigestDraft,
  MeetingEvidenceRequestDraft,
  MeetingRoundRecord,
} from "../../../api/types/hypothesisFirst";
import {
  HYPOTHESIS_FIRST_CONVERGENCE_NODE_ID,
  HYPOTHESIS_FIRST_GENERATION_NODE_ID,
  HYPOTHESIS_FIRST_SELECTION_NODE_ID,
} from "./hypothesisFirstCanvasRegion";
import { getNodeAdapter } from "./nodeAdapterModel";

export type HypothesisFirstStage =
  | "no_run"
  | "generation_missing"
  | "generation_running"
  | "generation_ready_to_summarize"
  | "generation_summarizing"
  | "generation_awaiting_approval"
  | "selection_required"
  | "review_running"
  | "review_ready_to_summarize"
  | "review_summarizing"
  | "review_awaiting_approval"
  | "collecting"
  | "collection_recovery"
  | "handoff_pending"
  | "next_review"
  | "converged"
  | "budget_exhausted"
  | "blocked";

export type HypothesisFirstCommand =
  | "create_run"
  | "open_generation"
  | "reopen_review"
  | "draft_summary"
  | "retry_draft_summary"
  | "approve_generation_digest"
  | "record_selection"
  | "approve_review_digest"
  | "retry_collection"
  | "continue_collection"
  | "retry_handoff"
  | "human_adjudication";

export type HypothesisFirstRecovery = {
  command: HypothesisFirstCommand;
  label: string;
  reason: string;
};

export type HypothesisFirstNextAction = {
  stage: HypothesisFirstStage;
  targetNodeId: string | null;
  navigationLabel: string;
  command?: HypothesisFirstCommand;
  commandLabel?: string;
  /** Consequence line rendered beside the command label (Stripe-style
   *  action + reason + expectation) so users know what clicking does. */
  commandDetail?: string;
  disabledReason?: string;
  recovery?: HypothesisFirstRecovery | null;
  statusMessage?: string;
  meetingRoundId?: string;
  collectionRequestId?: string;
  collectionRunId?: string;
};

export type HypothesisFirstNextActionInput = {
  run?: {
    runId?: string | null;
    runtimeCurrentNodeIds?: readonly string[] | null;
  } | null;
  chainState?: HypothesisFirstChainState | null;
  meetings?: readonly MeetingRoundRecord[] | null;
  selection?: HypothesisSelectionRecord | null;
  collectionRequests?: readonly CollectionRequestRecord[] | null;
  boundChatRoundsTerminal?: boolean;
  collectionChildStatus?: string | null;
  selectedNodeId?: string | null;
};

const GENERATION_TYPE = "hypothesis_candidate_generation";
const REVIEW_TYPE = "hypothesis_review";

const COLLECTING_CHILD = new Set(["queued", "pending", "running", "collecting", "starting", "dispatching"]);
const RECOVERY_CHILD = new Set(["failed", "needs_continue", "error", "blocked"]);
const COMPLETED_CHILD = new Set(["completed", "succeeded"]);
const CHAT_TERMINAL = new Set([
  "completed",
  "finished",
  "failed",
  "cancelled",
  "canceled",
  "succeeded",
  "stopped",
]);

function action(partial: HypothesisFirstNextAction): HypothesisFirstNextAction {
  return {
    recovery: null,
    ...partial,
  };
}

function isGenerationMeeting(meeting: MeetingRoundRecord): boolean {
  return meeting.meetingType === GENERATION_TYPE;
}

function isReviewMeeting(meeting: MeetingRoundRecord): boolean {
  return meeting.meetingType === REVIEW_TYPE;
}

function sortMeetings(meetings: readonly MeetingRoundRecord[]): MeetingRoundRecord[] {
  return [...meetings].sort((left, right) => {
    const leftIndex = left.roundIndex ?? 0;
    const rightIndex = right.roundIndex ?? 0;
    if (leftIndex !== rightIndex) return leftIndex - rightIndex;
    return String(left.startedAt ?? "").localeCompare(String(right.startedAt ?? ""));
  });
}

function latestOf(
  meetings: readonly MeetingRoundRecord[],
  predicate: (meeting: MeetingRoundRecord) => boolean,
): MeetingRoundRecord | null {
  const matched = sortMeetings(meetings.filter(predicate));
  return matched[matched.length - 1] ?? null;
}

function reviewMeetingNodeId(meeting: MeetingRoundRecord | null): string {
  if (!meeting) return "hf_meeting_1";
  return `hf_meeting_${meeting.roundIndex ?? 1}`;
}

function collectionNodeId(request: CollectionRequestRecord | null): string {
  if (!request?.requestId) return "source_finding";
  return `hf_collection_${request.requestId}`;
}

function candidateCount(input: HypothesisFirstNextActionInput): number {
  return Number(input.chainState?.candidateCount ?? 0);
}

function hasSelection(input: HypothesisFirstNextActionInput): boolean {
  return Boolean(input.selection?.selectionId || input.chainState?.selectionId);
}

function meetingSummaryFailed(meeting: MeetingRoundRecord): boolean {
  return Boolean(meeting.summaryError?.trim())
    || Boolean(meeting.digestDraft?.validationErrors?.length);
}

function formalRuntimeNode(input: HypothesisFirstNextActionInput) {
  for (const nodeId of input.run?.runtimeCurrentNodeIds ?? []) {
    const adapter = getNodeAdapter(String(nodeId || "").trim());
    if (adapter) return adapter;
  }
  return null;
}

export function chatRoundIsTerminal(status: string | null | undefined): boolean {
  return CHAT_TERMINAL.has(String(status || "").trim().toLowerCase());
}

export function boundChatRoundsAreTerminal(input: {
  meeting?: MeetingRoundRecord | null;
  chatRounds?: ReadonlyArray<{ roundId: string; status: string }> | null;
}): boolean {
  if (typeof input.meeting?.boundChatRoundsTerminal === "boolean") {
    return input.meeting.boundChatRoundsTerminal;
  }
  const boundIds = (input.meeting?.chatRoomRoundIds ?? []).map((id) => id.trim()).filter(Boolean);
  const rounds = input.chatRounds ?? [];
  if (!boundIds.length) {
    if (!rounds.length) return false;
    return rounds.every((round) => chatRoundIsTerminal(round.status));
  }
  const byId = new Map(rounds.map((round) => [round.roundId, round]));
  if (boundIds.some((id) => !byId.has(id))) return false;
  return boundIds.every((id) => chatRoundIsTerminal(byId.get(id)?.status));
}

export function evidenceRequestKeywords(request: MeetingEvidenceRequestDraft): string[] {
  return (request.searchEnvelope?.keywords ?? [])
    .map((keyword) => String(keyword || "").trim())
    .filter(Boolean);
}

export function hasValidEvidenceRequestKeywords(
  requests: readonly MeetingEvidenceRequestDraft[] | null | undefined,
): boolean {
  return (requests ?? []).some((request) => evidenceRequestKeywords(request).length > 0);
}

export function reviewDigestConfirmBlocker(draft: MeetingDigestDraft | null | undefined): string | undefined {
  if (!draft) return "还没有可确认的评审结论";
  if (!hasValidEvidenceRequestKeywords(draft.evidenceRequests)) {
    return "本轮结论没有有效搜集关键词，请退回后重新整理";
  }
  return undefined;
}

function childStatus(
  request: CollectionRequestRecord | null,
  override?: string | null,
): string {
  return String(override || request?.status || "").trim().toLowerCase();
}

function latestRequest(
  requests: readonly CollectionRequestRecord[] | null | undefined,
): CollectionRequestRecord | null {
  const list = [...(requests ?? [])].sort((left, right) =>
    String(left.createdAt ?? "").localeCompare(String(right.createdAt ?? "")),
  );
  return list[list.length - 1] ?? null;
}

function openReviewAfterHandoff(
  meetings: readonly MeetingRoundRecord[],
  request: CollectionRequestRecord,
): MeetingRoundRecord | null {
  const reviews = sortMeetings(meetings.filter(isReviewMeeting));
  return reviews.find((meeting) => {
    if (meeting.previousMeetingRoundId && meeting.previousMeetingRoundId === request.meetingRoundId) {
      return true;
    }
    return meeting.status !== "closed" && String(meeting.startedAt ?? "") >= String(request.handedOffAt ?? request.createdAt ?? "");
  }) ?? reviews[reviews.length - 1] ?? null;
}

function meetingStage(
  kind: "generation" | "review",
  meeting: MeetingRoundRecord,
  terminal: boolean,
): HypothesisFirstNextAction {
  const generation = kind === "generation";
  const nodeId = generation ? HYPOTHESIS_FIRST_GENERATION_NODE_ID : reviewMeetingNodeId(meeting);
  const roundId = meeting.meetingRoundId;
  if (meeting.status === "open") {
    if (!terminal) {
      return action({
        stage: generation ? "generation_running" : "review_running",
        targetNodeId: nodeId,
        navigationLabel: generation ? "查看候选生成讨论" : "查看评审讨论",
        statusMessage: "讨论进行中",
        meetingRoundId: roundId,
      });
    }
    return action({
      stage: generation ? "generation_ready_to_summarize" : "review_ready_to_summarize",
      targetNodeId: nodeId,
      navigationLabel: generation ? "前往候选生成" : "前往评审讨论",
      command: "draft_summary",
      commandLabel: generation ? "整理候选清单" : "整理本轮结论",
      statusMessage: generation
        ? "团队讨论已结束，系统正在整理候选清单"
        : "本轮评审已结束，系统正在整理结论",
      meetingRoundId: roundId,
    });
  }
  if (meeting.status === "summarizing") {
    if (meetingSummaryFailed(meeting)) {
      return action({
        stage: generation ? "generation_summarizing" : "review_summarizing",
        targetNodeId: nodeId,
        navigationLabel: generation ? "前往候选生成" : "前往评审讨论",
        recovery: {
          command: "retry_draft_summary",
          label: generation ? "重试整理候选清单" : "重试整理本轮结论",
          reason: "自动整理未完成",
        },
        statusMessage: "自动整理失败，可手动重试",
        meetingRoundId: roundId,
      });
    }
    return action({
      stage: generation ? "generation_summarizing" : "review_summarizing",
      targetNodeId: nodeId,
      navigationLabel: generation ? "查看候选生成" : "查看评审讨论",
      statusMessage: generation
        ? "团队讨论已结束，系统正在整理候选清单"
        : "本轮评审已结束，系统正在整理结论",
      meetingRoundId: roundId,
    });
  }
  if (meeting.status === "awaiting_approval") {
    if (generation) {
      return action({
        stage: "generation_awaiting_approval",
        targetNodeId: nodeId,
        navigationLabel: "前往确认候选",
        command: "approve_generation_digest",
        commandLabel: "确认候选清单",
        commandDetail: "确认后候选进入假说选择，由你决定送审哪些",
        meetingRoundId: roundId,
      });
    }
    const disabledReason = reviewDigestConfirmBlocker(meeting.digestDraft);
    return action({
      stage: "review_awaiting_approval",
      targetNodeId: nodeId,
      navigationLabel: "前往确认本轮",
      command: "approve_review_digest",
      commandLabel: "确认并结束本轮",
      commandDetail: "归档本轮评审纪要，流程将自动继续下一步",
      disabledReason,
      meetingRoundId: roundId,
    });
  }
  return action({
    stage: "blocked",
    targetNodeId: nodeId,
    navigationLabel: "查看当前任务",
    disabledReason: `会议状态 ${meeting.status} 无法继续`,
    meetingRoundId: roundId,
  });
}

export function resolveHypothesisFirstNextAction(
  input: HypothesisFirstNextActionInput,
): HypothesisFirstNextAction {
  const runId = String(input.run?.runId || "").trim();
  if (!runId) {
    return action({
      stage: "no_run",
      targetNodeId: null,
      navigationLabel: "选择题目开始研究",
      command: "create_run",
      commandLabel: "选择题目开始研究",
    });
  }

  const meetings = input.meetings ?? [];
  const generation = latestOf(meetings, isGenerationMeeting);
  const review = latestOf(meetings, isReviewMeeting);
  const request = latestRequest(input.collectionRequests);
  const terminal = Boolean(input.boundChatRoundsTerminal);
  const state = input.chainState;

  // Meeting gates come before the converged navigation: a round still walking
  // its four-state gate is the actionable step, and the formal-pipeline
  // navigation must not mask it (observed live: a chain already marked
  // converged while its final review round sat in awaiting_approval offered
  // only 前往资料搜集, hiding 确认并结束本轮).
  if (generation && generation.status !== "closed") {
    return meetingStage("generation", generation, terminal);
  }

  if (review && review.status !== "closed") {
    const followUp = Boolean(review.previousMeetingRoundId);
    if (review.status === "open" && !terminal && followUp) {
      return action({
        stage: "next_review",
        targetNodeId: reviewMeetingNodeId(review),
        navigationLabel: "前往下一轮讨论",
        statusMessage: "下一轮讨论已开启",
        meetingRoundId: review.meetingRoundId,
      });
    }
    return meetingStage("review", review, terminal);
  }

  if (state?.hypothesisConverged) {
    const runtimeNode = formalRuntimeNode(input);
    return action({
      stage: "converged",
      targetNodeId: runtimeNode?.nodeId ?? HYPOTHESIS_FIRST_CONVERGENCE_NODE_ID,
      navigationLabel: runtimeNode ? `前往${runtimeNode.label}` : "查看假说收敛",
      statusMessage: "假说先行闭环已完成",
      commandDetail: runtimeNode
        ? "假说阶段完成，无需再操作假说；查看下一步研究任务"
        : undefined,
    });
  }
  if (state?.budgetExhausted) {
    return action({
      stage: "budget_exhausted",
      targetNodeId: HYPOTHESIS_FIRST_CONVERGENCE_NODE_ID,
      navigationLabel: "前往假说收敛",
      command: "human_adjudication",
      commandLabel: "人工裁决",
      statusMessage: "轮次预算已耗尽，需要人工裁决",
    });
  }

  if (!hasSelection(input) && candidateCount(input) === 0) {
    return action({
      stage: "generation_missing",
      targetNodeId: HYPOTHESIS_FIRST_GENERATION_NODE_ID,
      navigationLabel: "前往候选生成",
      command: "open_generation",
      commandLabel: generation?.status === "closed" ? "重新生成候选假说" : "生成候选假说",
    });
  }

  if (!hasSelection(input) && candidateCount(input) > 0) {
    return action({
      stage: "selection_required",
      targetNodeId: HYPOTHESIS_FIRST_SELECTION_NODE_ID,
      navigationLabel: "前往假说选择",
      command: "record_selection",
      commandLabel: "记录选择并开启评审",
    });
  }

  if (request && request.status !== "handed_off" && !request.handoffRef) {
    const status = childStatus(request, input.collectionChildStatus);
    const collectionRunId = String(request.collectionRunId || "").trim() || undefined;
    if (RECOVERY_CHILD.has(status)) {
      return action({
        stage: "collection_recovery",
        targetNodeId: "source_finding",
        navigationLabel: "前往资料搜集",
        command: status === "needs_continue" ? "continue_collection" : "retry_collection",
        commandLabel: status === "needs_continue" ? "继续搜集" : "重试搜集",
        recovery: {
          command: status === "needs_continue" ? "continue_collection" : "retry_collection",
          label: status === "needs_continue" ? "继续搜集" : "重试搜集",
          reason: "资料搜集未完成",
        },
        collectionRequestId: request.requestId,
        collectionRunId,
      });
    }
    if (COMPLETED_CHILD.has(status) || status === "completed") {
      if (!collectionRunId) {
        return action({
          stage: "blocked",
          targetNodeId: collectionNodeId(request),
          navigationLabel: "查看资料搜集",
          disabledReason: "资料搜集已完成，但缺少子运行标识，无法自动交接",
          statusMessage: "自动交接缺少资料搜集运行标识",
          collectionRequestId: request.requestId,
        });
      }
      return action({
        stage: "handoff_pending",
        targetNodeId: collectionNodeId(request),
        navigationLabel: "查看资料搜集",
        command: "retry_handoff",
        commandLabel: "重试自动交接",
        recovery: {
          command: "retry_handoff",
          label: "重试自动交接",
          reason: "搜集已完成但尚未交接下一轮",
        },
        collectionRequestId: request.requestId,
        collectionRunId,
      });
    }
    if (request.collectionRunId || COLLECTING_CHILD.has(status) || state?.collectionReady) {
      return action({
        stage: "collecting",
        targetNodeId: "source_finding",
        navigationLabel: "查看资料搜集",
        statusMessage: "资料搜集中",
        collectionRequestId: request.requestId,
        collectionRunId,
      });
    }
    return action({
      stage: "blocked",
      targetNodeId: collectionNodeId(request),
      navigationLabel: "查看资料搜集",
      disabledReason: "搜集请求已记录，但还没有子运行",
      collectionRequestId: request.requestId,
      collectionRunId,
    });
  }

  if (request && (request.status === "handed_off" || request.handoffRef)) {
    const next = openReviewAfterHandoff(meetings, request);
    if (next && next.status !== "closed") {
      if (next.status === "open" && !terminal) {
        return action({
          stage: "next_review",
          targetNodeId: reviewMeetingNodeId(next),
          navigationLabel: "前往下一轮讨论",
          statusMessage: "下一轮讨论已开启",
          meetingRoundId: next.meetingRoundId,
        });
      }
      return meetingStage("review", next, terminal);
    }
  }

  if (hasSelection(input) && !review) {
    return action({
      stage: "blocked",
      targetNodeId: HYPOTHESIS_FIRST_SELECTION_NODE_ID,
      navigationLabel: "前往假说选择",
      disabledReason: "已记录选择，但评审讨论尚未开启",
    });
  }

  return action({
    stage: "blocked",
    targetNodeId: input.selectedNodeId?.startsWith("hf_")
      ? input.selectedNodeId
      : HYPOTHESIS_FIRST_GENERATION_NODE_ID,
    navigationLabel: "查看当前任务",
    disabledReason: "假说先行状态无法识别，请从当前卡片恢复",
  });
}

export function focusNodeFromNextAction(next: HypothesisFirstNextAction): string {
  return next.targetNodeId || HYPOTHESIS_FIRST_GENERATION_NODE_ID;
}

export function shouldHideSourceFindingStart(stage: HypothesisFirstStage): boolean {
  return stage === "collecting"
    || stage === "handoff_pending"
    || stage === "collection_recovery"
    || stage === "next_review"
    || stage === "converged"
    || stage === "budget_exhausted";
}

export function isHypothesisFirstDiscussionActive(
  meetings: readonly MeetingRoundRecord[] | null | undefined,
): boolean {
  return (meetings ?? []).some((meeting) => {
    if (!isGenerationMeeting(meeting) && !isReviewMeeting(meeting)) return false;
    return meeting.status === "open"
      || meeting.status === "summarizing"
      || meeting.status === "awaiting_approval";
  });
}
