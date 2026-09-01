import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { fetchChatRoomDetail } from "../../../api/chat";
import {
  approveHypothesisDigest,
  closeReviewMeeting,
  draftMeetingSummary,
  executeHypothesisFirstCommand,
  fetchMeetingRound,
  fetchMeetingRoundSourceMessages,
  isHypothesisFirstCommandStateConflict,
  openHypothesisCandidateGeneration,
  recordCollectionHandoff,
  rejectMeetingDigestDraft,
  reopenHypothesisReviewMeeting,
} from "../../../api/hypothesisFirst";
import { queryKeys } from "../../../api/queryKeys";
import { resolvePollingInterval, usePageVisibility } from "../../../app/pollingPolicy";
import { VButton, VErrorSummary, VStateSurface } from "../../../components/vui";
import { MeetingRoundDisplay } from "../meetingRoundDisplay";
import {
  boundChatRoundsAreTerminal,
  type HypothesisFirstCommand,
  type HypothesisFirstNextAction,
} from "./hypothesisFirstNextAction";
import { invalidateHypothesisFirstQueries } from "./useHypothesisFirstChain";
import styles from "./HypothesisFirstMeetingOps.styles";

type Language = "zh" | "en";

/**
 * Human-readable reasons for evidence requests dropped during a successful
 * close. Mirrors the `reason` values built by the chain's collection step
 * (`decision_not_persisted`, `search_envelope_missing`/`invalid`,
 * `collection_payload_invalid`); unknown codes fall through verbatim.
 */
const SKIPPED_REASON_LABELS: Record<string, { zh: string; en: string }> = {
  decision_not_persisted: {
    zh: "该请求未随结论持久化",
    en: "the decision was not persisted with the closure",
  },
  search_envelope_missing: {
    zh: "缺少检索关键词",
    en: "search keywords are missing",
  },
  search_envelope_invalid: {
    zh: "检索参数无效",
    en: "the search parameters are invalid",
  },
  collection_payload_invalid: {
    zh: "搜集要求无效",
    en: "the collection requirements are invalid",
  },
};

function describeSkippedReason(reason: string, isZh: boolean): string {
  const label = SKIPPED_REASON_LABELS[reason];
  if (label) return isZh ? label.zh : label.en;
  return reason;
}

/** Readable text for a prepare-draft `{status:"blocked", blocker}` response. */
const PREPARE_BLOCKER_LABELS: Record<string, { zh: string; en: string }> = {
  discussion_round_running: {
    zh: "讨论回合仍在进行，全部结束后才能重新整理结论",
    en: "A discussion round is still running; the conclusion can be re-organized only after all rounds finish",
  },
  discussion_has_no_completed_messages: {
    zh: "讨论未产出可引用的成功发言，不能重新整理结论",
    en: "The discussion produced no successful statements to cite; the conclusion cannot be re-organized",
  },
};

function describePrepareBlocker(payload: unknown, isZh: boolean): string | null {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return null;
  const record = payload as Record<string, unknown>;
  if (String(record.status ?? "") !== "blocked") return null;
  const blocker = record.blocker;
  if (!blocker || typeof blocker !== "object") {
    return isZh ? "系统暂时无法重新整理结论" : "The system cannot re-organize the conclusion right now";
  }
  const info = blocker as Record<string, unknown>;
  const label = PREPARE_BLOCKER_LABELS[String(info.code ?? "")];
  if (label) return isZh ? label.zh : label.en;
  const message = String(info.message ?? "").trim();
  if (message) return message;
  const code = String(info.code ?? "").trim();
  return code || (isZh ? "系统暂时无法重新整理结论" : "The system cannot re-organize the conclusion right now");
}

/**
 * Detail text (without the headline) for a prepare-draft `{status:"blocked",
 * blocker}` response on the automatic/manual draft path. Running rounds win
 * because they explain the wait; otherwise the known-code copy or the server
 * message is shown with the remediation label (or raw code) appended. Null
 * when the response is not a blocked prepare result.
 */
function describeDraftBlockDetail(payload: unknown, isZh: boolean): string | null {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return null;
  const record = payload as Record<string, unknown>;
  if (String(record.status ?? "") !== "blocked") return null;
  const blocker = record.blocker;
  if (!blocker || typeof blocker !== "object" || Array.isArray(blocker)) {
    return isZh ? "系统暂时无法整理本轮结论" : "The system cannot organize this round right now";
  }
  const info = blocker as Record<string, unknown>;
  const runningRoundIds = Array.isArray(info.runningRoundIds) ? info.runningRoundIds : [];
  if (runningRoundIds.length) {
    return isZh
      ? `${runningRoundIds.length} 个讨论回合仍在进行，全部结束后才能整理结论`
      : `${runningRoundIds.length} discussion round(s) still running; organization starts once all rounds finish`;
  }
  const remediation = String(info.remediationLabel ?? "").trim();
  const code = String(info.code ?? "").trim();
  const suffix = remediation || code
    ? (isZh ? `（${remediation || code}）` : ` (${remediation || code})`)
    : "";
  const label = PREPARE_BLOCKER_LABELS[code];
  if (label) return `${isZh ? label.zh : label.en}${suffix}`;
  const message = String(info.message ?? "").trim();
  if (message) return `${message}${suffix}`;
  if (code) return code;
  return isZh ? "系统暂时无法整理本轮结论" : "The system cannot organize this round right now";
}

/**
 * Reject responses come in two envelopes: a V2 command receipt wraps the
 * prepare-draft result in `result`, while the legacy digest-reject endpoint
 * returns the prepare/blocked shape directly. Unwrap to the inner response.
 */
function prepareResponseFromMutationPayload(payload: unknown): unknown {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return payload;
  if ("result" in payload) {
    const result = (payload as { result?: unknown }).result;
    if (result && typeof result === "object" && !Array.isArray(result)) return result;
  }
  return payload;
}

export function HypothesisFirstMeetingOps(props: {
  lang?: Language;
  teamId: string;
  questionId: string;
  runId?: string;
  meetingRoundId: string;
  nextAction: HypothesisFirstNextAction;
  compact?: boolean;
  onRetryCollection?: () => Promise<void>;
  onApproved?: () => void;
}) {
  const lang = props.lang ?? "zh";
  const isZh = lang === "zh";
  const queryClient = useQueryClient();
  const pageVisible = usePageVisibility();
  const roundQuery = useQuery({
    queryKey: queryKeys.teamMeetingRound(props.teamId, props.meetingRoundId),
    queryFn: ({ signal }) => fetchMeetingRound(props.teamId, props.meetingRoundId, { signal }),
    enabled: Boolean(props.teamId && props.meetingRoundId),
    refetchInterval: (query) => {
      const status = query.state.data?.meetingRound?.status ?? "";
      return status === "open" || status === "summarizing"
        ? resolvePollingInterval(pageVisible, 4_000)
        : false;
    },
  });
  const messagesQuery = useQuery({
    queryKey: queryKeys.teamMeetingRoundSourceMessages(props.teamId, props.meetingRoundId),
    queryFn: ({ signal }) => fetchMeetingRoundSourceMessages(props.teamId, props.meetingRoundId, { signal }),
    enabled: Boolean(props.teamId && props.meetingRoundId),
    refetchInterval: () => {
      const status = roundQuery.data?.meetingRound?.status ?? "";
      return status === "open" || status === "summarizing"
        ? resolvePollingInterval(pageVisible, 4_000)
        : false;
    },
  });

  const invalidate = () => invalidateHypothesisFirstQueries(
    queryClient,
    props.teamId,
    props.questionId,
    props.runId,
  );
  const canonicalAction = props.nextAction.canonicalAction;
  const allowLegacyMutation = props.nextAction.stateSource !== "v2_canonical";
  const canonicalActionUnavailable = () => Promise.reject(new Error("canonical_action_unavailable"));
  const refreshOnConflict = (error: unknown) => {
    if (isHypothesisFirstCommandStateConflict(error)) invalidate();
  };

  const [draftBlockedNotice, setDraftBlockedNotice] = useState<string | null>(null);
  // The reject flow already renders the blocker from its own re-prepare
  // result; the follow-up draft kick must not repeat it as a second notice.
  const suppressDraftBlockNoticeRef = useRef(false);
  const draftMutation = useMutation<unknown, Error, void>({
    mutationFn: () => {
      if (canonicalAction?.command === "regenerate_summary") {
        return executeHypothesisFirstCommand(
          props.teamId,
          props.questionId,
          canonicalAction,
          undefined,
          { runId: props.runId },
        );
      }
      if (allowLegacyMutation) {
        return draftMeetingSummary(props.teamId, props.meetingRoundId, { actor: "operator", force: false });
      }
      return canonicalActionUnavailable();
    },
    onSuccess: (payload) => {
      // A blocked prepare resolves as a 200 success; surface the blocker so
      // the auto-draft (one attempt per meeting) and the manual retry button
      // never fail silently.
      setDraftBlockedNotice(
        describeDraftBlockDetail(prepareResponseFromMutationPayload(payload), isZh),
      );
      invalidate();
    },
  });
  const autoDraftedMeetingIds = useRef(new Set<string>());
  const roundStatus = roundQuery.data?.meetingRound?.status ?? "";
  const sourceMessages = messagesQuery.data?.messages ?? [];
  const completedSourceMessageCount = sourceMessages.filter((message) => {
    const content = String(message.content ?? "").trim().toLowerCase();
    return String(message.status ?? "").trim().toLowerCase() === "completed"
      && content !== "pass"
      && content !== "pass."
      && content !== "pass。";
  }).length;
  const failedCandidateDiscussion = messagesQuery.isSuccess
    && sourceMessages.length > 0
    && completedSourceMessageCount === 0
    && roundQuery.data?.meetingRound?.meetingType === "hypothesis_candidate_generation"
    && (roundStatus === "open" || roundStatus === "summarizing");
  const failedReviewDiscussion = messagesQuery.isSuccess
    && sourceMessages.length > 0
    && completedSourceMessageCount === 0
    && roundQuery.data?.meetingRound?.meetingType === "hypothesis_review"
    && (roundStatus === "open" || roundStatus === "summarizing");
  const interruptedCandidateDiscussion = messagesQuery.isSuccess
    && sourceMessages.length === 0
    && roundQuery.data?.meetingRound?.meetingType === "hypothesis_candidate_generation"
    && (roundQuery.data.meetingRound.chatRoomRoundIds?.length ?? 0) === 0
    && (roundStatus === "open" || roundStatus === "summarizing");
  const shouldAutoDraft = props.nextAction.command === "draft_summary"
    && props.nextAction.meetingRoundId === props.meetingRoundId
    && roundStatus === "open"
    && messagesQuery.isSuccess
    && completedSourceMessageCount > 0;
  useEffect(() => {
    if (!shouldAutoDraft || autoDraftedMeetingIds.current.has(props.meetingRoundId)) return;
    autoDraftedMeetingIds.current.add(props.meetingRoundId);
    draftMutation.mutate();
  }, [draftMutation.mutate, props.meetingRoundId, shouldAutoDraft]);
  const [approveBlockedReason, setApproveBlockedReason] = useState<string | null>(null);
  const approveMutation = useMutation({
    mutationFn: () => {
      if (canonicalAction?.command === "approve_summary") {
        return executeHypothesisFirstCommand(
          props.teamId,
          props.questionId,
          canonicalAction,
          { decision: "accepted" },
          { runId: props.runId },
        ).then((receipt) => receipt.result as Awaited<ReturnType<typeof approveHypothesisDigest>>);
      }
      if (!allowLegacyMutation) return canonicalActionUnavailable();
      const hash = roundQuery.data?.meetingRound?.digestDraft?.contentHash || "";
      return approveHypothesisDigest(props.teamId, props.meetingRoundId, {
        closedBy: "operator",
        expectedDigestContentHash: hash,
      });
    },
    onSuccess: (payload) => {
      setRejectNotice(null);
      // The API returns 200 with closed=false + validationErrors when the
      // digest cannot be confirmed; surface it instead of a silent no-op.
      if (payload && payload.closed === false) {
        const errors = (payload.validationErrors ?? []).map((item) => item.message).filter(Boolean);
        setApproveBlockedReason(
          errors.length
            ? errors.join("；")
            : (isZh
              ? "本轮结论未通过校验，未被确认；请退回后重新整理"
              : "The conclusion failed validation and was not confirmed; send it back and organize it again"),
        );
      } else if (payload?.hypothesisRound?.status === "failed") {
        // Confirmed, but the hypothesis-round generation failed downstream.
        setApproveBlockedReason(
          isZh
            ? "本轮已确认，但假说评审轮生成失败；请重新发起评审讨论以重试生成。"
            : "The round was confirmed, but review-round generation failed; reopen the review discussion to retry generation.",
        );
      } else {
        setApproveBlockedReason(null);
        // Partially-invalid evidence requests are dropped on a successful
        // close and reported in collection.skipped ({decisionId, reason,
        // error?}); validationErrors only exists on the closed=false branch.
        const skipped = payload?.collection?.skipped ?? [];
        const reasons = [
          ...new Set(
            skipped
              .map((item) => describeSkippedReason(String(item?.reason ?? ""), isZh))
              .filter(Boolean),
          ),
        ];
        setDroppedRequestNotice(
          skipped.length
            ? (isZh
              ? `本轮已确认，但 ${skipped.length} 条证据请求被跳过：${reasons.join("；")}`
              : `The round was confirmed, but ${skipped.length} evidence requests were skipped: ${reasons.join("; ")}`)
            : null,
        );
      }
      invalidate();
      if (payload && payload.closed !== false) {
        props.onApproved?.();
      }
    },
    onError: (error) => {
      refreshOnConflict(error);
      // A stale digest hash means another page updated the draft; refetch so
      // the cached contentHash catches up instead of retrying the old one.
      if (error instanceof Error && /stale/i.test(error.message)) {
        void queryClient.invalidateQueries({
          queryKey: queryKeys.teamMeetingRound(props.teamId, props.meetingRoundId),
        });
        setApproveBlockedReason(
          isZh
            ? "纪要已在其他页面更新，已重新加载最新纪要，请再次确认。"
            : "The digest changed on another page. The latest version was reloaded; confirm it again.",
        );
      }
    },
  });
  const rejectMutation = useMutation<unknown, Error, void>({
    mutationFn: () => {
      if (canonicalAction?.command === "approve_summary") {
        return executeHypothesisFirstCommand(
          props.teamId,
          props.questionId,
          canonicalAction,
          { decision: "rejected" },
          { runId: props.runId },
        );
      }
      if (allowLegacyMutation) {
        return rejectMeetingDigestDraft(props.teamId, props.meetingRoundId, { actor: "operator" });
      }
      return canonicalActionUnavailable();
    },
    onSuccess: (payload) => {
      setApproveBlockedReason(null);
      setDroppedRequestNotice(null);
      // A rejection is never a confirmation: never call onApproved here.
      // V2 responds with the re-prepared draft (or a blocked prepare result);
      // surface the blocker instead of pretending the redraft is running.
      const blockerText = describePrepareBlocker(
        prepareResponseFromMutationPayload(payload),
        isZh,
      );
      if (blockerText) suppressDraftBlockNoticeRef.current = true;
      setRejectNotice(
        blockerText
          ? (isZh
            ? `结论已退回，但系统暂时无法重新整理：${blockerText}`
            : `The conclusion was sent back, but it cannot be re-organized yet: ${blockerText}`)
          : (isZh
            ? "系统正在重新整理结论，请稍候查看新版结论。"
            : "The system is re-organizing the conclusion; the new version will appear shortly."),
      );
      invalidate();
      // Reject clears the draft server-side but never re-summarizes; kick the
      // draft immediately so the round does not sit in summarizing with no
      // available action. The V2 adapter already performs that regeneration
      // atomically with the signed command, so do not dispatch it twice.
      if (canonicalAction?.command !== "approve_summary") {
        draftMutation.mutate();
      }
    },
    onError: refreshOnConflict,
  });
  const generationMutation = useMutation<unknown, Error, void>({
    mutationFn: () => {
      if (canonicalAction
        && (canonicalAction.command === "open_generation" || canonicalAction.command === "retry_generation")) {
        return executeHypothesisFirstCommand(
          props.teamId,
          props.questionId,
          canonicalAction,
          undefined,
          { runId: props.runId },
        );
      }
      if (allowLegacyMutation) {
        return openHypothesisCandidateGeneration(props.teamId, props.questionId, props.runId);
      }
      return canonicalActionUnavailable();
    },
    onSuccess: invalidate,
    onError: refreshOnConflict,
  });
  const [reopenBlockedReason, setReopenBlockedReason] = useState<string | null>(null);
  const [droppedRequestNotice, setDroppedRequestNotice] = useState<string | null>(null);
  const [rejectNotice, setRejectNotice] = useState<string | null>(null);
  const closeCorrectionMutation = useMutation({
    mutationFn: () =>
      closeReviewMeeting(props.teamId, props.meetingRoundId, {
        closedBy: "operator",
        decisions: [
          {
            decision: "close_round",
            rationale: "本轮证据请求均无效，按现有结论关闭，不发起资料搜集",
            decidedBy: "operator",
            evidenceRefs: [`meeting_round:${props.meetingRoundId}`],
            status: "adopted",
          },
        ],
      }),
    onSuccess: () => {
      setApproveBlockedReason(null);
      invalidate();
    },
  });
  const reopenReviewMutation = useMutation<unknown, Error, void>({
    mutationFn: () => {
      if (canonicalAction && ["retry_review_dispatch", "reopen_review", "resume_discussion", "stop_discussion"].includes(canonicalAction.command)) {
        return executeHypothesisFirstCommand(
          props.teamId,
          props.questionId,
          canonicalAction,
          undefined,
          { runId: props.runId },
        );
      }
      if (allowLegacyMutation) return reopenHypothesisReviewMeeting(props.teamId, props.meetingRoundId);
      return canonicalActionUnavailable();
    },
    onSuccess: (payload) => {
      const openStatus = payload && typeof payload === "object" && "openStatus" in payload
        ? String(payload.openStatus || "")
        : "";
      // Reopening burns the failed round first; if the budget gate then denies
      // the replacement round, say so instead of letting the meeting vanish.
      setReopenBlockedReason(
        openStatus === "budget_exhausted"
          ? (isZh
            ? "失败轮已作废，但已达到评审硬上限，假说仍未收敛。"
            : "The failed round was voided, but the hard review limit was reached without convergence.")
          : null,
      );
      invalidate();
    },
  });
  const collectionRunId = props.nextAction.collectionRunId || "";
  const canHandoff = props.nextAction.command === "retry_handoff"
    && Boolean(props.nextAction.collectionRequestId)
    && Boolean(collectionRunId);
  const handoffMutation = useMutation<unknown, Error, void>({
    mutationFn: () => {
      if (canonicalAction?.command === "handoff_collection") {
        return executeHypothesisFirstCommand(
          props.teamId,
          props.questionId,
          canonicalAction,
          undefined,
          { runId: props.runId },
        );
      }
      if (allowLegacyMutation) {
        return recordCollectionHandoff(props.teamId, props.nextAction.collectionRequestId || "", {
          handoffRef: `source_collection_run:${collectionRunId}`,
        });
      }
      return canonicalActionUnavailable();
    },
    onSuccess: invalidate,
    onError: refreshOnConflict,
  });
  // V2 canonical-only commands (stop_collection / cancel_run / archive_run)
  // have no legacy endpoint: the adapter leaves `command` undefined but still
  // emits commandLabel/commandDetail and the signed canonical action, so the
  // primary button renders and dispatches straight through the command channel.
  const canonicalOnlyMutation = useMutation<unknown, Error, void>({
    mutationFn: () => {
      if (!canonicalAction) return canonicalActionUnavailable();
      return executeHypothesisFirstCommand(
        props.teamId,
        props.questionId,
        canonicalAction,
        undefined,
        { runId: props.runId },
      );
    },
    onSuccess: invalidate,
    onError: refreshOnConflict,
  });

  if (roundQuery.isPending) {
    return <VStateSurface title={isZh ? "正在读取讨论" : "Loading discussion"} tone="loading" />;
  }
  if (roundQuery.isError || !roundQuery.data) {
    return (
      <VErrorSummary
        label={isZh ? "讨论不可用" : "Discussion unavailable"}
        summary={roundQuery.error instanceof Error ? roundQuery.error.message : "meeting_round_unavailable"}
      />
    );
  }

  const commandEnabled = props.nextAction.meetingRoundId === props.meetingRoundId;
  const autoDraftFailed = commandEnabled
    && props.nextAction.command === "draft_summary"
    && draftMutation.isError;
  const legacyCommand = interruptedCandidateDiscussion
    ? "open_generation"
    : failedCandidateDiscussion
    ? "open_generation"
    : failedReviewDiscussion
      ? "reopen_review"
    : autoDraftFailed
      ? "retry_draft_summary"
    : (commandEnabled ? (props.nextAction.recovery?.command || props.nextAction.command) : undefined);
  const command = allowLegacyMutation
    ? legacyCommand
    : (commandEnabled && canonicalAction ? props.nextAction.command : undefined);
  // Canonical-only when the signed action exists but no legacy command is
  // mapped; the button then dispatches via canonicalOnlyMutation.
  const canonicalOnlyCommand = !allowLegacyMutation
    && commandEnabled
    && Boolean(canonicalAction)
    && !props.nextAction.command;
  const legacyCommandLabel = interruptedCandidateDiscussion
    ? (isZh ? "重试启动候选讨论" : "Retry candidate discussion")
    : failedCandidateDiscussion
    ? (isZh ? "重新发起候选讨论" : "Reopen candidate discussion")
    : failedReviewDiscussion
      ? (isZh ? "重新发起评审讨论" : "Reopen review discussion")
    : autoDraftFailed
      ? (roundQuery.data.meetingRound.meetingType === "hypothesis_candidate_generation"
        ? (isZh ? "重试整理候选清单" : "Retry candidate list summary")
        : (isZh ? "重试整理本轮结论" : "Retry round summary"))
    : (commandEnabled ? (props.nextAction.recovery?.label || props.nextAction.commandLabel) : undefined);
  const commandLabel = allowLegacyMutation
    ? legacyCommandLabel
    : (commandEnabled && canonicalAction ? props.nextAction.commandLabel : undefined);
  const commandDetail = failedCandidateDiscussion || failedReviewDiscussion
    ? (isZh ? "放弃本轮失败尝试，以同一批假说开启下一轮" : "Discard the failed attempt and open the next round with the same hypotheses")
    : autoDraftFailed
      ? undefined
      : (commandEnabled ? props.nextAction.commandDetail : undefined);
  const commandDisabledReason = props.nextAction.disabledReason
    || (command === "retry_handoff" && !canHandoff
      ? (isZh ? "缺少资料搜集运行标识，无法重试自动交接" : "The source-collection run ID is missing; automatic handoff cannot be retried")
      : undefined);
  const pending = draftMutation.isPending
    || approveMutation.isPending
    || rejectMutation.isPending
    || generationMutation.isPending
    || reopenReviewMutation.isPending
    || handoffMutation.isPending
    || canonicalOnlyMutation.isPending
    || closeCorrectionMutation.isPending;
  const error =
    draftMutation.error
    || approveMutation.error
    || rejectMutation.error
    || generationMutation.error
    || reopenReviewMutation.error
    || handoffMutation.error
    || canonicalOnlyMutation.error
    || closeCorrectionMutation.error;
  const displayRound = props.nextAction.command === "draft_summary"
    && roundQuery.data.meetingRound.status === "open"
    ? {
        ...roundQuery.data.meetingRound,
        status: "summarizing" as const,
        summaryError: autoDraftFailed ? "automatic_organization_failed" : undefined,
      }
    : roundQuery.data.meetingRound;

  const runCommand = (next: HypothesisFirstCommand) => {
    if (next === "draft_summary" || next === "retry_draft_summary") {
      draftMutation.mutate();
      return;
    }
    if (next === "approve_generation_digest" || next === "approve_review_digest") {
      approveMutation.mutate();
      return;
    }
    if (next === "open_generation") {
      generationMutation.mutate();
      return;
    }
    if (next === "reopen_review") {
      reopenReviewMutation.mutate();
      return;
    }
    if (next === "retry_review_dispatch" || next === "resume_discussion" || next === "stop_discussion") {
      reopenReviewMutation.mutate();
      return;
    }
    if (next === "retry_handoff") {
      if (canHandoff) handoffMutation.mutate();
      return;
    }
    if (next === "retry_collection" || next === "continue_collection") {
      void props.onRetryCollection?.();
    }
  };

  const showPrimaryCommand = Boolean(
    (command || canonicalOnlyCommand)
    && commandLabel
    && command !== "draft_summary"
    && command !== "record_selection"
    && command !== "create_run"
    && command !== "human_adjudication",
  );
  const showReject = commandEnabled
    && (allowLegacyMutation || canonicalAction?.command === "approve_summary")
    && (props.nextAction.stage === "review_awaiting_approval" || props.nextAction.stage === "generation_awaiting_approval");
  const actionBar = (showPrimaryCommand || showReject) ? (
    <div className={styles.actions} data-testid="meeting-round-actions">
      {showPrimaryCommand ? (
        <div className={styles.commandWrap}>
          <VButton
            type="button"
            variant="primary"
            density="compact"
            isPending={pending}
            isDisabled={Boolean(commandDisabledReason)}
            disabledReason={commandDisabledReason}
            onPress={() => {
              if (canonicalOnlyCommand) {
                canonicalOnlyMutation.mutate();
                return;
              }
              if (!command) return;
              runCommand(command);
            }}
          >
            {commandLabel}
          </VButton>
          {commandDetail ? <span className={styles.commandDetail}>{commandDetail}</span> : null}
        </div>
      ) : null}
      {showReject ? (
        <VButton
          type="button"
          variant="ghost"
          density="compact"
          isPending={rejectMutation.isPending}
          isDisabled={pending}
          onPress={() => rejectMutation.mutate()}
        >
          {isZh ? "退回重新整理" : "Send back for revision"}
        </VButton>
      ) : null}
    </div>
  ) : undefined;

  return (
    <div className={styles.task}>
      {error ? (
        <VErrorSummary
          label={isZh ? "操作未完成" : "Action could not finish"}
          summary={isHypothesisFirstCommandStateConflict(error)
            ? (isZh ? "状态已更新，请重新确认。" : "The workflow state changed. Review it and confirm again.")
            : error instanceof Error ? error.message : String(error)}
        />
      ) : null}
      {approveBlockedReason ? (
        <VErrorSummary
          label={isZh ? "本轮结论未被确认" : "Round conclusion was not confirmed"}
          summary={approveBlockedReason}
          data-testid="approve-blocked-reason"
          actions={allowLegacyMutation && commandEnabled && (roundStatus === "awaiting_approval") ? (
            <VButton
              type="button"
              variant="ghost"
              density="compact"
              isPending={closeCorrectionMutation.isPending}
              isDisabled={pending}
              onPress={() => closeCorrectionMutation.mutate()}
            >
              {isZh ? "按现有结论关闭本轮（不发起资料搜集）" : "Close with the current conclusion (do not start collection)"}
            </VButton>
          ) : undefined}
        />
      ) : null}
      {draftBlockedNotice ? (
        <VErrorSummary
          label={isZh ? "自动整理暂未开始" : "Automatic organization has not started"}
          summary={draftBlockedNotice}
          data-testid="draft-blocked-notice"
        />
      ) : null}
      {rejectNotice ? (
        <VStateSurface
          tone="info"
          density="compact"
          title={isZh ? "本轮结论已退回" : "Conclusion sent back"}
          data-testid="reject-notice"
        >
          {rejectNotice}
        </VStateSurface>
      ) : null}
      {droppedRequestNotice ? (
        <VErrorSummary
          label={isZh ? "部分证据请求被跳过" : "Some evidence requests were skipped"}
          summary={droppedRequestNotice}
          data-testid="dropped-request-notice"
        />
      ) : null}
      {reopenBlockedReason ? (
        <VErrorSummary
          label={isZh ? "评审轮未重开" : "Review round was not reopened"}
          summary={reopenBlockedReason}
          data-testid="reopen-blocked-reason"
        />
      ) : null}
      <MeetingRoundDisplay
        round={displayRound}
        messages={sourceMessages}
        compact={props.compact}
        lang={lang}
        actions={actionBar}
      />
    </div>
  );
}
