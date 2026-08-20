import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

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
  const roomQuery = useQuery({
    queryKey: queryKeys.chatRoom(linkedChatRoomId || ""),
    queryFn: ({ signal }) => fetchChatRoomDetail(linkedChatRoomId || "", { signal }),
    enabled: Boolean(linkedChatRoomId) && typeof serverFlag !== "boolean",
    staleTime: 4_000,
    refetchInterval: typeof serverFlag === "boolean" ? false : 4_000,
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
  const roundQuery = useQuery({
    queryKey: queryKeys.teamMeetingRound(props.teamId, props.meetingRoundId),
    queryFn: ({ signal }) => fetchMeetingRound(props.teamId, props.meetingRoundId, { signal }),
    enabled: Boolean(props.teamId && props.meetingRoundId),
    refetchInterval: (query) => {
      const status = query.state.data?.meetingRound?.status ?? "";
      return status === "open" || status === "summarizing" ? 4_000 : false;
    },
  });
  const messagesQuery = useQuery({
    queryKey: queryKeys.teamMeetingRoundSourceMessages(props.teamId, props.meetingRoundId),
    queryFn: ({ signal }) => fetchMeetingRoundSourceMessages(props.teamId, props.meetingRoundId, { signal }),
    enabled: Boolean(props.teamId && props.meetingRoundId),
    refetchInterval: () => {
      const status = roundQuery.data?.meetingRound?.status ?? "";
      return status === "open" || status === "summarizing" ? 4_000 : false;
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
  const approveMutation = useMutation({
    mutationFn: () => {
      const hash = roundQuery.data?.meetingRound?.digestDraft?.contentHash || "";
      return approveHypothesisDigest(props.teamId, props.meetingRoundId, {
        closedBy: "operator",
        expectedDigestContentHash: hash,
      });
    },
    onSuccess: () => {
      invalidate();
      props.onApproved?.();
    },
  });
  const rejectMutation = useMutation({
    mutationFn: () => rejectMeetingDigestDraft(props.teamId, props.meetingRoundId, { actor: "operator" }),
    onSuccess: invalidate,
  });
  const generationMutation = useMutation({
    mutationFn: () => openHypothesisCandidateGeneration(props.teamId, props.questionId),
    onSuccess: invalidate,
  });
  const reopenReviewMutation = useMutation({
    mutationFn: () => reopenHypothesisReviewMeeting(props.teamId, props.meetingRoundId),
    onSuccess: invalidate,
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

  return (
    <div className={styles.task}>
      <MeetingRoundDisplay
        round={displayRound}
        messages={sourceMessages}
        compact={props.compact}
      />
      {error ? (
        <VErrorSummary
          label="操作未完成"
          summary={error instanceof Error ? error.message : String(error)}
        />
      ) : null}
      <div className={styles.actions}>
        {command && commandLabel && command !== "draft_summary" && command !== "record_selection" && command !== "create_run" && command !== "human_adjudication" ? (
          <VButton
            type="button"
            variant="primary"
            density="compact"
            isPending={pending}
            isDisabled={Boolean(commandDisabledReason)}
            disabledReason={commandDisabledReason}
            onPress={() => runCommand(command)}
          >
            {commandLabel}
          </VButton>
        ) : null}
        {commandEnabled && (props.nextAction.stage === "review_awaiting_approval" || props.nextAction.stage === "generation_awaiting_approval") ? (
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
    </div>
  );
}
