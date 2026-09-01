/**
 * Typed next-step model for the hypothesis-first canvas.
 *
 * Toolbar consumes navigation fields only. Inspector consumes command fields.
 * The two surfaces must never share the same button copy for navigate vs write.
 */
import type {
  ActionCommand,
  CommandAction,
  CollectionRequestRecord,
  HypothesisFirstChainState,
  HypothesisSelectionRecord,
  MeetingDigestDraft,
  MeetingEvidenceRequestDraft,
  MeetingRoundRecord,
  ReviewRoundLinkRecord,
} from "../../../api/types/hypothesisFirst";
import {
  HYPOTHESIS_FIRST_CONVERGENCE_NODE_ID,
  HYPOTHESIS_FIRST_GENERATION_NODE_ID,
  HYPOTHESIS_FIRST_SELECTION_NODE_ID,
} from "./hypothesisFirstCanvasRegion";
import { getNodeAdapter } from "./nodeAdapterModel";
import {
  buildHypothesisFirstReviewProjection,
  currentActionableProjectedReview,
  type HypothesisFirstReviewProjection,
  type ProjectedReviewMeeting,
} from "./hypothesisFirstMeetingProjection";
import { effectiveCollectionRequestStatus } from "./hypothesisFirstCollectionStatus";

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
  | "program_delivery"
  | "completed"
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
  | "resume_discussion"
  | "stop_discussion"
  | "open_next_review"
  | "human_adjudication"
  | "retry_review_dispatch"
  | "retry_formal_node"
  | "reconcile_formal_run"
  | "retry_program_handoff"
  | "record_program_review"
  | "create_formal_revision";

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
  stateSource?: "v2_canonical" | "v1_legacy";
  canonicalActionId?: string;
  canonicalAction?: CommandAction;
  canonicalCommand?: ActionCommand;
  expectedStateVersion?: string;
  navigationDeepLink?: string;
};

export type HypothesisFirstNextActionInput = {
  run?: {
    runId?: string | null;
    runtimeCurrentNodeIds?: readonly string[] | null;
  } | null;
  /** A hypothesis-first chain can be active before a formal workflow run exists. */
  workflowActive?: boolean;
  questionId?: string | null;
  chainState?: HypothesisFirstChainState | null;
  meetings?: readonly MeetingRoundRecord[] | null;
  reviewRoundLinks?: readonly ReviewRoundLinkRecord[] | null;
  selection?: HypothesisSelectionRecord | null;
  collectionRequests?: readonly CollectionRequestRecord[] | null;
  boundChatRoundsTerminal?: boolean;
  /** Explicit override for "the discussion ended abnormally"; derived from
   *  chatRounds when absent. */
  boundChatRoundsTerminalFailed?: boolean;
  /** Bound chat-room rounds; legacy fallback for terminal/failed derivation
   *  when the caller has not precomputed a boolean. */
  chatRounds?: ReadonlyArray<{ roundId: string; status: string }> | null;
  collectionChildStatus?: string | null;
  selectedNodeId?: string | null;
};

const GENERATION_TYPE = "hypothesis_candidate_generation";
const REVIEW_TYPE = "hypothesis_review";

const COLLECTING_CHILD = new Set(["queued", "pending", "running", "collecting", "starting", "dispatching"]);
const RECOVERY_CHILD = new Set(["failed", "needs_continue", "error", "blocked"]);
// Backend stop_collection and terminal-event bridging park the child run on
// "cancelled" (legacy "canceled" and "stopped" spellings also occur); a
// stopped run needs the user-decides recovery surface, not a "collecting" mask.
const STOPPED_CHILD = new Set(["cancelled", "canceled", "stopped"]);
const COMPLETED_CHILD = new Set(["completed", "succeeded"]);
// Terminal chat-round statuses, mirrored from the backend discussion-turn
// taxonomy (core/web/services/team_workflow/research_runtime/
// hypothesis_first_state_v2.py, _CHAT_ROOM_ROUND_TERMINAL_STATUSES unified
// with _CHAT_ROOM_ROUND_TERMINAL_RUNTIME_STATUSES). A bound round in any of
// these states means the room is done and the summary gate may open.
const CHAT_TERMINAL = new Set([
  // completed family
  "completed",
  "done",
  "ready",
  "routed",
  "success",
  "succeeded",
  // Backend finalizes mixed-success rounds as "partial"; the room is ready.
  // Kept for old-snapshot replay.
  "partial",
  // Legacy defensive spellings never written by the current backend; kept so
  // old persisted snapshots still replay as terminal.
  "finished",
  // continuation gates: the turn ended but a follow-up may still be needed
  "needs_continue",
  "paused_limit",
  "closed",
  // stopped family
  "cancelled",
  "canceled",
  "idle",
  "stopped",
  "stopped_by_user",
  "superseded",
  "terminated",
  // runtime stop bookkeeping
  "force_stopped",
  "orphan_reconciled",
  "orphaned_room_reconciled",
  // failed family
  "error",
  "failed",
  "failed_provider",
  "failed_runtime",
  "stop_failed",
]);
// Failed endings still open the summary gate (captured content exists to
// draft), but the status copy must say the discussion ended abnormally
// instead of "finished".
const CHAT_TERMINAL_FAILED = new Set([
  "error",
  "failed",
  "failed_provider",
  "failed_runtime",
  "stop_failed",
]);

/** Meeting-round queries are team-scoped; next-action state is question-scoped. */
export function meetingsForHypothesisFirstQuestion(
  meetings: readonly MeetingRoundRecord[] | null | undefined,
  questionId?: string | null,
): MeetingRoundRecord[] {
  const list = [...(meetings ?? [])];
  const needle = String(questionId || "").trim().toUpperCase();
  if (!needle) return list;
  return list.filter((meeting) => String(meeting.question || "").trim().toUpperCase() === needle);
}

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
  // summaryDraftError is the server-persisted failure; summaryError only
  // exists on client-synthesized display records.
  return Boolean(meeting.summaryError?.trim())
    || Boolean(meeting.summaryDraftError?.code || meeting.summaryDraftError?.message)
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

export function chatRoundIsFailedTerminal(status: string | null | undefined): boolean {
  return CHAT_TERMINAL_FAILED.has(String(status || "").trim().toLowerCase());
}

function boundChatRoundStatuses(input: {
  meeting?: MeetingRoundRecord | null;
  chatRounds?: ReadonlyArray<{ roundId: string; status: string }> | null;
}): string[] | null {
  const boundIds = (input.meeting?.chatRoomRoundIds ?? []).map((id) => id.trim()).filter(Boolean);
  const rounds = input.chatRounds ?? [];
  if (!boundIds.length) {
    if (!rounds.length) return null;
    return rounds.map((round) => round.status);
  }
  const byId = new Map(rounds.map((round) => [round.roundId, round]));
  if (boundIds.some((id) => !byId.has(id))) return null;
  return boundIds.map((id) => String(byId.get(id)?.status ?? ""));
}

export function boundChatRoundsAreTerminal(input: {
  meeting?: MeetingRoundRecord | null;
  chatRounds?: ReadonlyArray<{ roundId: string; status: string }> | null;
}): boolean {
  if (typeof input.meeting?.boundChatRoundsTerminal === "boolean") {
    return input.meeting.boundChatRoundsTerminal;
  }
  const statuses = boundChatRoundStatuses(input);
  return statuses !== null && statuses.every((status) => chatRoundIsTerminal(status));
}

/** True when the bound rounds are observable and at least one ended in a
 *  failed terminal state; callers combine it with terminal before showing
 *  "ended abnormally" copy. */
export function boundChatRoundsFailedTerminal(input: {
  meeting?: MeetingRoundRecord | null;
  chatRounds?: ReadonlyArray<{ roundId: string; status: string }> | null;
}): boolean {
  const statuses = boundChatRoundStatuses(input);
  return statuses !== null && statuses.some((status) => chatRoundIsFailedTerminal(status));
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

const DIGEST_CAPTURE_KEYS = [
  "agreements",
  "disagreements",
  "actionItems",
  "knowledgeCandidates",
  "evidenceRequests",
] as const;

export function digestDraftCapturedDiscussion(
  draft: MeetingDigestDraft | null | undefined,
): boolean {
  if (!draft) return false;
  return DIGEST_CAPTURE_KEYS.some((key) => {
    const value = draft[key];
    return Array.isArray(value) && value.length > 0;
  });
}

export function reviewDigestConfirmBlocker(draft: MeetingDigestDraft | null | undefined): string | undefined {
  if (!draft) return "还没有可确认的评审结论";
  if (!digestDraftCapturedDiscussion(draft)) {
    return "纪要未捕获讨论内容";
  }
  // A round with ZERO evidence requests is the legal convergence close
  // (backend synthesizes a close_round decision); only requests that exist
  // but carry no usable keywords must be sent back for rework.
  const requests = draft.evidenceRequests ?? [];
  if (requests.length > 0 && !hasValidEvidenceRequestKeywords(requests)) {
    return "本轮的证据请求都缺少有效搜集关键词，请退回后重新整理";
  }
  return undefined;
}

function childStatus(
  request: CollectionRequestRecord | null,
  override?: string | null,
): string {
  return effectiveCollectionRequestStatus(request, override);
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
  projection: HypothesisFirstReviewProjection,
  request: CollectionRequestRecord,
): ProjectedReviewMeeting | null {
  const reviews = projection.rounds;
  return reviews.find((round) =>
    round.previousMeetingRoundId === request.meetingRoundId
  ) ?? null;
}

type HypothesisFirstSiblingProgress = {
  order: number;
  count: number;
  pending: number;
};

function siblingProgress(
  projection: HypothesisFirstReviewProjection,
  current: ProjectedReviewMeeting,
): HypothesisFirstSiblingProgress | undefined {
  const siblings = projection.rounds.filter((round) =>
    round.roundIndex === current.roundIndex
  );
  if (siblings.length <= 1) return undefined;
  const currentIndex = siblings.findIndex((round) =>
    round.meeting.meetingRoundId === current.meeting.meetingRoundId
  );
  return {
    order: Math.max(0, currentIndex) + 1,
    count: siblings.length,
    pending: siblings.filter((round) => round.meeting.status !== "closed").length,
  };
}

function siblingPrefix(progress: HypothesisFirstSiblingProgress | undefined): string {
  return progress && progress.count > 1
    ? `候选 ${progress.order}/${progress.count} · `
    : "";
}

function meetingStage(
  kind: "generation" | "review",
  meeting: MeetingRoundRecord,
  terminal: boolean,
  failedTerminal: boolean,
  reviewNodeId?: string,
  sibling?: HypothesisFirstSiblingProgress,
): HypothesisFirstNextAction {
  const generation = kind === "generation";
  const nodeId = generation ? HYPOTHESIS_FIRST_GENERATION_NODE_ID : reviewNodeId;
  const roundId = meeting.meetingRoundId;
  if (!nodeId) {
    return action({
      stage: "blocked",
      targetNodeId: null,
      navigationLabel: "等待轮次同步",
      disabledReason: "当前评审轮次信息待同步，请刷新后重试",
      meetingRoundId: roundId,
    });
  }
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
      statusMessage: failedTerminal
        ? (generation
          ? "讨论异常终止，可基于已捕获的发言整理候选清单"
          : `${siblingPrefix(sibling)}本轮讨论异常终止，可基于已捕获的发言整理结论`)
        : (generation
          ? "团队讨论已结束，系统正在整理候选清单"
          : `${siblingPrefix(sibling)}本轮评审已结束，系统正在整理结论`),
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
    if (terminal) {
      return action({
        stage: generation ? "generation_summarizing" : "review_summarizing",
        targetNodeId: nodeId,
        navigationLabel: generation ? "前往候选生成" : "前往评审讨论",
        recovery: {
          command: "retry_draft_summary",
          label: generation ? "重试整理候选清单" : "重试整理本轮结论",
          reason: "自动整理未完成",
        },
        statusMessage: "自动整理未完成，可手动重试",
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
    const remaining = sibling && sibling.count > 1
      ? Math.max(0, sibling.pending - 1)
      : 0;
    return action({
      stage: "review_awaiting_approval",
      targetNodeId: nodeId,
      navigationLabel: "前往确认本轮",
      command: "approve_review_digest",
      commandLabel: "确认并结束本轮",
      commandDetail: remaining > 0
        ? `归档本候选的评审纪要；确认后还需关闭其余 ${remaining} 个候选的评审`
        : "归档本轮评审纪要，流程将自动继续下一步",
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
  if (!runId && !input.workflowActive) {
    return action({
      stage: "no_run",
      targetNodeId: null,
      navigationLabel: "选择题目开始研究",
      command: "create_run",
      commandLabel: "选择题目开始研究",
    });
  }

  const meetings = meetingsForHypothesisFirstQuestion(
    input.meetings,
    input.questionId || input.chainState?.questionId,
  );
  const generation = latestOf(meetings, isGenerationMeeting);
  const currentSelectionId = String(
    input.selection?.selectionId || input.chainState?.selectionId || "",
  ).trim();
  const reviewProjection = buildHypothesisFirstReviewProjection(
    meetings,
    input.reviewRoundLinks,
    currentSelectionId,
  );
  const reviewRound = currentActionableProjectedReview(reviewProjection);
  const review = reviewRound?.meeting ?? null;
  const request = latestRequest(input.collectionRequests);
  // Explicit caller boolean wins (precomputed by boundChatRoundsAreTerminal);
  // otherwise fall back to the meeting's server-persisted flag, then to the
  // bound chat rounds themselves, so the legacy route resolver does not read
  // an ended room as "still discussing".
  const explicitTerminal = typeof input.boundChatRoundsTerminal === "boolean"
    ? input.boundChatRoundsTerminal
    : null;
  const explicitFailed = typeof input.boundChatRoundsTerminalFailed === "boolean"
    ? input.boundChatRoundsTerminalFailed
    : null;
  const chatTerminalFor = (meeting: MeetingRoundRecord | null | undefined): boolean =>
    explicitTerminal !== null
      ? explicitTerminal
      : boundChatRoundsAreTerminal({ meeting, chatRounds: input.chatRounds });
  const chatFailedFor = (meeting: MeetingRoundRecord | null | undefined): boolean =>
    explicitFailed !== null
      ? explicitFailed
      : boundChatRoundsFailedTerminal({ meeting, chatRounds: input.chatRounds });
  const state = input.chainState;

  // Meeting gates come before the converged navigation: a round still walking
  // its four-state gate is the actionable step, and the formal-pipeline
  // navigation must not mask it (observed live: a chain already marked
  // converged while its final review round sat in awaiting_approval offered
  // only 前往资料搜集, hiding 确认并结束本轮).
  if (generation && generation.status !== "closed") {
    return meetingStage("generation", generation, chatTerminalFor(generation), chatFailedFor(generation));
  }

  if (reviewRound && reviewRound.meeting.status !== "closed") {
    const activeReview = reviewRound.meeting;
    const followUp = Boolean(reviewRound.previousMeetingRoundId);
    const reviewTerminal = chatTerminalFor(activeReview);
    if (activeReview.status === "open" && !reviewTerminal && followUp) {
      return action({
        stage: "next_review",
        targetNodeId: reviewRound.nodeId,
        navigationLabel: "前往下一轮讨论",
        statusMessage: "下一轮讨论已开启",
        meetingRoundId: activeReview.meetingRoundId,
      });
    }
    return meetingStage(
      "review",
      activeReview,
      reviewTerminal,
      chatFailedFor(activeReview),
      reviewRound.nodeId,
      siblingProgress(reviewProjection, reviewRound),
    );
  }

  const unresolvedActiveReview = meetings.find(
    (meeting) => isReviewMeeting(meeting)
      && meeting.status !== "closed"
      && reviewProjection.unresolvedMeetingIds.includes(meeting.meetingRoundId),
  );
  if (unresolvedActiveReview) {
    return action({
      stage: "blocked",
      targetNodeId: input.selectedNodeId?.startsWith("hf_meeting_")
        ? input.selectedNodeId
        : HYPOTHESIS_FIRST_SELECTION_NODE_ID,
      navigationLabel: "等待轮次同步",
      disabledReason: "当前评审轮次信息待同步，请刷新后重试",
      meetingRoundId: unresolvedActiveReview.meetingRoundId,
    });
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
    if (RECOVERY_CHILD.has(status) || STOPPED_CHILD.has(status)) {
      const stopped = STOPPED_CHILD.has(status);
      const recoveryReason = stopped
        ? "资料搜集已停止，可重新发起搜集。"
        : status === "failed" && request.status === "failed"
          ? "资料搜集启动失败，请重试。"
          : status === "failed"
            ? "资料搜集失败，请重试。"
            : "资料搜集未完成";
      return action({
        stage: "collection_recovery",
        targetNodeId: "source_finding",
        navigationLabel: "前往资料搜集",
        command: status === "needs_continue" ? "continue_collection" : "retry_collection",
        commandLabel: status === "needs_continue" ? "继续搜集" : "重试搜集",
        statusMessage: stopped ? "资料搜集已停止" : undefined,
        recovery: {
          command: status === "needs_continue" ? "continue_collection" : "retry_collection",
          label: status === "needs_continue" ? "继续搜集" : "重试搜集",
          reason: recoveryReason,
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
    const next = openReviewAfterHandoff(reviewProjection, request);
    if (next && next.meeting.status !== "closed") {
      const nextTerminal = chatTerminalFor(next.meeting);
      if (next.meeting.status === "open" && !nextTerminal) {
        return action({
          stage: "next_review",
          targetNodeId: next.nodeId,
          navigationLabel: "前往下一轮讨论",
          statusMessage: "下一轮讨论已开启",
          meetingRoundId: next.meeting.meetingRoundId,
        });
      }
      return meetingStage(
        "review",
        next.meeting,
        nextTerminal,
        chatFailedFor(next.meeting),
        next.nodeId,
        siblingProgress(reviewProjection, next),
      );
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
