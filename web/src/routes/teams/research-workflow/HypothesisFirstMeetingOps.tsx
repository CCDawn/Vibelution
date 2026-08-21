import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { fetchChatRoomDetail } from "../../../api/chat";
import {
  approveHypothesisDigest,
  draftMeetingSummary,
  fetchMeetingRound,
  fetchMeetingRoundSourceMessages,
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

export function useBoundChatRoundsTerminal(
  meetingRoundId: string | undefined,
  linkedChatRoomId: string | undefined,
  chatRoomRoundIds: string[] | undefined,
  serverFlag?: boolean,
): boolean {
  const pageVisible = usePageVisibility();
  const roomQuery = useQuery({
    queryKey: queryKeys.chatRoom(linkedChatRoomId || ""),
    queryFn: ({ signal }) => fetchChatRoomDetail(linkedChatRoomId || "", { signal }),
    enabled: Boolean(linkedChatRoomId) && typeof serverFlag !== "boolean",
    staleTime: 4_000,
    refetchInterval: typeof serverFlag === "boolean"
      ? false
      : resolvePollingInterval(pageVisible, 4_000),
  });
  if (typeof serverFlag === "boolean") return serverFlag;
  return boundChatRoundsAreTerminal({
    meeting: meetingRoundId
      ? {
          meetingRoundId,
          meetingType: "",
          mode: "",
          scopeHash: "",
          participants: [],
          status: "open",
          startedAt: "",
          program: "",
          theme: "",
          campaign: "",
          question: "",
          branch: "",
          workflow: "",
          agentId: "",
          chatRoomRoundIds,
          boundChatRoundsTerminal: serverFlag,
        }
      : null,
    chatRounds: roomQuery.data?.rounds,
  });
}

export function HypothesisFirstMeetingOps(props: {
  teamId: string;
  questionId: string;
  meetingRoundId: string;
  nextAction: HypothesisFirstNextAction;
  compact?: boolean;
  onRetryCollection?: () => Promise<void>;
  onApproved?: () => void;
}) {
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

  const invalidate = () => invalidateHypothesisFirstQueries(queryClient, props.teamId, props.questionId);

  const draftMutation = useMutation({
    mutationFn: () => draftMeetingSummary(props.teamId, props.meetingRoundId, { actor: "operator", force: false }),
    onSuccess: invalidate,
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
      const hash = roundQuery.data?.meetingRound?.digestDraft?.contentHash || "";
      return approveHypothesisDigest(props.teamId, props.meetingRoundId, {
        closedBy: "operator",
        expectedDigestContentHash: hash,
      });
    },
    onSuccess: (payload) => {
      // The API returns 200 with closed=false + validationErrors when the
      // digest cannot be confirmed; surface it instead of a silent no-op.
      if (payload && payload.closed === false) {
        const errors = (payload.validationErrors ?? []).map((item) => item.message).filter(Boolean);
        setApproveBlockedReason(
          errors.length
            ? errors.join("；")
            : "本轮结论未通过校验，未被确认；请退回后重新整理",
        );
      } else if (payload?.hypothesisRound?.status === "failed") {
        // Confirmed, but the hypothesis-round generation failed downstream.
        setApproveBlockedReason(
          "本轮已确认，但假说评审轮生成失败；请重新发起评审讨论以重试生成。",
        );
      } else {
        setApproveBlockedReason(null);
      }
      invalidate();
      if (payload && payload.closed !== false) {
        props.onApproved?.();
      }
    },
  });
  const rejectMutation = useMutation({
    mutationFn: () => rejectMeetingDigestDraft(props.teamId, props.meetingRoundId, { actor: "operator" }),
    onSuccess: () => {
      setApproveBlockedReason(null);
      invalidate();
    },
  });
  const generationMutation = useMutation({
    mutationFn: () => openHypothesisCandidateGeneration(props.teamId, props.questionId),
    onSuccess: invalidate,
  });
  const [reopenBlockedReason, setReopenBlockedReason] = useState<string | null>(null);
  const reopenReviewMutation = useMutation({
    mutationFn: () => reopenHypothesisReviewMeeting(props.teamId, props.meetingRoundId),
    onSuccess: (payload) => {
      // Reopening burns the failed round first; if the budget gate then denies
      // the replacement round, say so instead of letting the meeting vanish.
      setReopenBlockedReason(
        payload?.openStatus === "budget_exhausted"
          ? "失败轮已作废，但轮次预算已耗尽，无法开启新的评审轮；请在假说收敛卡提升预算并发起新一轮评审。"
          : null,
      );
      invalidate();
    },
  });
  const collectionRunId = props.nextAction.collectionRunId || "";
  const canHandoff = props.nextAction.command === "retry_handoff"
    && Boolean(props.nextAction.collectionRequestId)
    && Boolean(collectionRunId);
  const handoffMutation = useMutation({
    mutationFn: () => recordCollectionHandoff(props.teamId, props.nextAction.collectionRequestId || "", {
      handoffRef: `source_collection_run:${collectionRunId}`,
    }),
    onSuccess: invalidate,
  });

  if (roundQuery.isPending) {
    return <VStateSurface title="正在读取讨论" tone="loading" />;
  }
  if (roundQuery.isError || !roundQuery.data) {
    return (
      <VErrorSummary
        label="讨论不可用"
        summary={roundQuery.error instanceof Error ? roundQuery.error.message : "meeting_round_unavailable"}
      />
    );
  }

  const commandEnabled = props.nextAction.meetingRoundId === props.meetingRoundId;
  const autoDraftFailed = commandEnabled
    && props.nextAction.command === "draft_summary"
    && draftMutation.isError;
  const command = interruptedCandidateDiscussion
    ? "open_generation"
    : failedCandidateDiscussion
    ? "open_generation"
    : failedReviewDiscussion
      ? "reopen_review"
    : autoDraftFailed
      ? "retry_draft_summary"
    : (commandEnabled ? (props.nextAction.recovery?.command || props.nextAction.command) : undefined);
  const commandLabel = interruptedCandidateDiscussion
    ? "重试启动候选讨论"
    : failedCandidateDiscussion
    ? "重新发起候选讨论"
    : failedReviewDiscussion
      ? "重新发起评审讨论"
    : autoDraftFailed
      ? (roundQuery.data.meetingRound.meetingType === "hypothesis_candidate_generation"
        ? "重试整理候选清单"
        : "重试整理本轮结论")
    : (commandEnabled ? (props.nextAction.recovery?.label || props.nextAction.commandLabel) : undefined);
  const commandDetail = failedCandidateDiscussion || failedReviewDiscussion
    ? "放弃本轮失败尝试，以同一批假说开启下一轮"
    : autoDraftFailed
      ? undefined
      : (commandEnabled ? props.nextAction.commandDetail : undefined);
  const commandDisabledReason = props.nextAction.disabledReason
    || (command === "retry_handoff" && !canHandoff
      ? "缺少资料搜集运行标识，无法重试自动交接"
      : undefined);
  const pending = draftMutation.isPending
    || approveMutation.isPending
    || rejectMutation.isPending
    || generationMutation.isPending
    || reopenReviewMutation.isPending
    || handoffMutation.isPending;
  const error =
    draftMutation.error
    || approveMutation.error
    || rejectMutation.error
    || generationMutation.error
    || reopenReviewMutation.error
    || handoffMutation.error;
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
    if (next === "retry_handoff") {
      if (canHandoff) handoffMutation.mutate();
      return;
    }
    if (next === "retry_collection" || next === "continue_collection") {
      void props.onRetryCollection?.();
    }
  };

  const showPrimaryCommand = Boolean(
    command
    && commandLabel
    && command !== "draft_summary"
    && command !== "record_selection"
    && command !== "create_run"
    && command !== "human_adjudication",
  );
  const showReject = commandEnabled
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
          onPress={() => rejectMutation.mutate()}
        >
          退回重新整理
        </VButton>
      ) : null}
    </div>
  ) : undefined;

  return (
    <div className={styles.task}>
      {error ? (
        <VErrorSummary
          label="操作未完成"
          summary={error instanceof Error ? error.message : String(error)}
        />
      ) : null}
      {approveBlockedReason ? (
        <VErrorSummary
          label="本轮结论未被确认"
          summary={approveBlockedReason}
          data-testid="approve-blocked-reason"
        />
      ) : null}
      {reopenBlockedReason ? (
        <VErrorSummary
          label="评审轮未重开"
          summary={reopenBlockedReason}
          data-testid="reopen-blocked-reason"
        />
      ) : null}
      <MeetingRoundDisplay
        round={displayRound}
        messages={sourceMessages}
        compact={props.compact}
        actions={actionBar}
      />
    </div>
  );
}
