/**
 * Typed next-step model for the hypothesis-first canvas.
 *
 * Toolbar consumes navigation fields only. Inspector consumes command fields.
 * The two surfaces must never share the same button copy for navigate vs write.
 */
import type {
  ActionCommand,
  CommandAction,
  MeetingDigestDraft,
  MeetingEvidenceRequestDraft,
  MeetingRoundRecord,
  WorkflowNavigationAnchor,
} from "../../../api/types/hypothesisFirst";
import { HYPOTHESIS_FIRST_GENERATION_NODE_ID } from "./hypothesisFirstCanvasRegion";

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
  | "rejected"
  | "blocked";

export type HypothesisFirstCommand = ActionCommand;

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
  stateSource?: "v2_canonical";
  canonicalActionId?: string;
  canonicalAction?: CommandAction;
  canonicalCommand?: ActionCommand;
  expectedStateVersion?: string;
  navigation?: WorkflowNavigationAnchor;
};

const GENERATION_TYPE = "hypothesis_candidate_generation";
const REVIEW_TYPE = "hypothesis_review";

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

function isGenerationMeeting(meeting: MeetingRoundRecord): boolean {
  return meeting.meetingType === GENERATION_TYPE;
}

function isReviewMeeting(meeting: MeetingRoundRecord): boolean {
  return meeting.meetingType === REVIEW_TYPE;
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
