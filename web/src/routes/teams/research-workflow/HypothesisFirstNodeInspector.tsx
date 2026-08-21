/**
 * Live task inspector for hypothesis-first region cards.
 *
 * Canvas cards remain a projection. This panel is the current-task surface:
 * discussion, digest confirm, selection, collection progress, and recovery.
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { fetchChatRoomDetail } from "../../../api/chat";
import {
  openHypothesisCandidateGeneration,
  openNextHypothesisReviewRound,
  recordCollectionHandoff,
} from "../../../api/hypothesisFirst";
import { queryKeys } from "../../../api/queryKeys";
import {
  VButton,
  VEmptyState,
  VErrorSummary,
  VStateRow,
  VStateSurface,
  VSurface,
} from "../../../components/vui";
import { HypothesisSelectionList } from "../challenge-cup/HypothesisSelectionList";
import {
  HYPOTHESIS_FIRST_CONVERGENCE_NODE_ID,
  HYPOTHESIS_FIRST_GENERATION_NODE_ID,
  HYPOTHESIS_FIRST_SELECTION_NODE_ID,
} from "./hypothesisFirstCanvasRegion";
import { HypothesisFirstMeetingOps } from "./HypothesisFirstMeetingOps";
import {
  boundChatRoundsAreTerminal,
  meetingsForHypothesisFirstQuestion,
  resolveHypothesisFirstNextAction,
  type HypothesisFirstNextAction,
} from "./hypothesisFirstNextAction";
import { invalidateHypothesisFirstQueries, useHypothesisFirstChain } from "./useHypothesisFirstChain";
import { resolvePollingInterval, usePageVisibility } from "../../../app/pollingPolicy";
import styles from "./HypothesisFirstNodeInspector.styles";

type Language = "zh" | "en";

export type HypothesisFirstNodeInspectorProps = {
  lang?: Language;
  teamId: string;
  questionId: string;
  nodeId: string;
  runId?: string;
  onOpenQuestion: (questionId: string) => void;
  collectionChildStatus?: string | null;
  onNavigateToNode?: (nodeId: string) => void;
  onRetryCollection?: () => Promise<void>;
};

function pickGeneration(meetings: ReturnType<typeof useHypothesisFirstChain>["meetings"]) {
  const sorted = [...meetings]
    .filter((item) => item.meetingType === "hypothesis_candidate_generation")
    .sort((left, right) => {
      const leftIndex = left.roundIndex ?? 0;
      const rightIndex = right.roundIndex ?? 0;
      if (leftIndex !== rightIndex) return leftIndex - rightIndex;
      return String(left.startedAt ?? "").localeCompare(String(right.startedAt ?? ""));
    });
  return sorted[sorted.length - 1] ?? null;
}

function pickReview(
  meetings: ReturnType<typeof useHypothesisFirstChain>["meetings"],
  nodeId: string,
) {
  const reviews = meetings.filter((item) => item.meetingType === "hypothesis_review");
  if (nodeId.startsWith("hf_meeting_")) {
    const roundIndex = Number(nodeId.slice("hf_meeting_".length));
    // No fallback to the latest round: a future round card must show its
    // "not yet opened" empty state instead of another round's operations.
    return reviews.find((item) => (item.roundIndex ?? 0) === roundIndex) ?? null;
  }
  return reviews.at(-1) ?? null;
}

function inspectorNodeOwnsCurrentStep(nodeId: string, targetNodeId: string | null): boolean {
  if (!targetNodeId) return true;
  if (nodeId === targetNodeId) return true;
  return nodeId.startsWith("hf_collection_") && targetNodeId === "source_finding";
}

export function HypothesisFirstNodeInspector({
  lang = "zh",
  teamId,
  questionId,
  nodeId,
  runId = "",
  onOpenQuestion,
  collectionChildStatus = null,
  onNavigateToNode,
  onRetryCollection,
}: HypothesisFirstNodeInspectorProps) {
  const isZh = lang === "zh";
  const queryClient = useQueryClient();
  const [retrying, setRetrying] = useState(false);
  const chain = useHypothesisFirstChain(teamId, questionId);
  const questionMeetings = meetingsForHypothesisFirstQuestion(chain.meetings, questionId);
  const generation = pickGeneration(questionMeetings);
  const review = pickReview(questionMeetings, nodeId);
  const activeMeeting = nodeId === HYPOTHESIS_FIRST_GENERATION_NODE_ID ? generation : review;
  const pageVisible = usePageVisibility();
  const roomQuery = useQuery({
    queryKey: queryKeys.chatRoom(activeMeeting?.linkedChatRoomId || ""),
    queryFn: ({ signal }) => fetchChatRoomDetail(activeMeeting?.linkedChatRoomId || "", { signal }),
    enabled: Boolean(activeMeeting?.linkedChatRoomId) && activeMeeting?.status === "open",
    refetchInterval: activeMeeting?.status === "open"
      ? resolvePollingInterval(pageVisible, 4_000)
      : false,
  });
  const nextAction = resolveHypothesisFirstNextAction({
    run: { runId: runId || (questionId ? "present" : "") },
    chainState: chain.chainState,
    meetings: questionMeetings,
    questionId,
    selection: chain.selection,
    collectionRequests: chain.collectionRequests,
    boundChatRoundsTerminal: boundChatRoundsAreTerminal({
      meeting: activeMeeting,
      chatRounds: roomQuery.data?.rounds,
    }),
    collectionChildStatus,
    selectedNodeId: nodeId,
  });
  const nodeOwnsCurrentStep = inspectorNodeOwnsCurrentStep(nodeId, nextAction.targetNodeId);
  const reviewMeetings = questionMeetings.filter(
    (meeting) => meeting.meetingType === "hypothesis_review",
  );
  const stageSummary = chain.chainState?.hypothesisConverged && reviewMeetings.length > 0
    ? {
        rounds: reviewMeetings.filter((meeting) => meeting.status === "closed").length,
        retries: reviewMeetings.filter(
          (meeting) =>
            meeting.status === "closed"
            && meeting.recoveryReason === "discussion_has_no_completed_messages",
        ).length,
        kept: chain.selection?.selectedCandidateIds.length ?? 0,
      }
    : null;

  if (!questionId) {
    return (
      <VEmptyState title={isZh ? "缺少题目上下文" : "Question context required"}>
        <p>{isZh ? "该卡片需要题目上下文才能继续当前任务。" : "This card needs question context before the current task can continue."}</p>
        <p className={styles.description}>
          {isZh
            ? "下一步：先从题目总览选择一道赛题，再打开假说先行流程。"
            : "Next: choose a challenge question from the overview, then open the hypothesis-first workflow."}
        </p>
      </VEmptyState>
    );
  }
  if (chain.loading) {
    return <VStateSurface tone="loading" title={isZh ? "加载假说先行任务" : "Loading hypothesis-first task"} fill className={styles.fill} />;
  }
  if (chain.error) {
    return (
      <VSurface tone="panel" className={styles.panel} data-vui="hypothesis-first-node-error">
        <div role="alert">{isZh ? "假说先行链加载失败：" : "Hypothesis-first chain failed to load: "}{chain.error}</div>
        <VButton
          type="button"
          variant="secondary"
          density="compact"
          isPending={retrying}
          isDisabled={retrying}
          onPress={async () => {
            setRetrying(true);
            try {
              await Promise.all([
                queryClient.refetchQueries({
                  queryKey: ["teams", teamId, "hypothesis-first"],
                  type: "active",
                }),
                queryClient.refetchQueries({
                  queryKey: queryKeys.teamMeetingRounds(teamId),
                  type: "active",
                }),
                queryClient.refetchQueries({
                  queryKey: queryKeys.teamHypothesisRounds(teamId),
                  type: "active",
                }),
                queryClient.refetchQueries({
                  queryKey: queryKeys.hypothesisFirstSelectionContext(teamId, questionId),
                  type: "active",
                }),
              ]);
            } finally {
              setRetrying(false);
            }
          }}
        >
          {isZh ? "重试" : "Retry"}
        </VButton>
      </VSurface>
    );
  }

  return (
    <VSurface tone="panel" className={styles.panel} data-vui="hypothesis-first-node-detail">
      <header>
        <div className={styles.stage}>{isZh ? "假说先行" : "Hypothesis first"}</div>
        <h3 className={styles.title}>{inspectorTitle(nodeId, lang)}</h3>
      </header>
      {nodeOwnsCurrentStep && nextAction.statusMessage ? (
        <div role="status" className={styles.status}>{nextAction.statusMessage}</div>
      ) : null}
      {nodeOwnsCurrentStep && nextAction.disabledReason ? (
        <VStateRow tone="warning">{nextAction.disabledReason}</VStateRow>
      ) : null}
      {nodeOwnsCurrentStep ? (
        <InspectorBody
          teamId={teamId}
          questionId={questionId}
          nodeId={nodeId}
          liveMeetingRoundId={activeMeeting?.meetingRoundId || nextAction.meetingRoundId || ""}
          nextAction={nextAction}
          lang={lang}
          stageSummary={stageSummary}
          onRetryCollection={onRetryCollection}
          onNavigateToNode={onNavigateToNode}
          onOpenQuestion={onOpenQuestion}
        />
      ) : (
        <div className={styles.task} data-testid="hypothesis-first-previous-step-pending">
          <VStateRow tone="warning">
            {nodeId === HYPOTHESIS_FIRST_CONVERGENCE_NODE_ID
              ? (isZh ? "前序任务尚未完成，请先处理当前步骤。" : "Earlier tasks are not complete; handle the current step first.")
              : (isZh ? "当前任务在其他步骤，请前往当前步骤。" : "The current task is on another step; go to the current step.")}
          </VStateRow>
          {nextAction.targetNodeId && onNavigateToNode ? (
            <VButton
              type="button"
              variant="primary"
              density="compact"
              onPress={() => onNavigateToNode(nextAction.targetNodeId || HYPOTHESIS_FIRST_GENERATION_NODE_ID)}
            >
              {isZh ? "前往当前步骤" : "Go to current step"}
            </VButton>
          ) : null}
        </div>
      )}
      <div className={styles.secondary}>
        <VButton type="button" variant="ghost" density="compact" onClick={() => onOpenQuestion(questionId)}>
          {isZh ? "打开赛题详情" : "Open question details"}
        </VButton>
      </div>
    </VSurface>
  );
}

function inspectorTitle(nodeId: string, lang: Language): string {
  if (nodeId === HYPOTHESIS_FIRST_GENERATION_NODE_ID) return lang === "zh" ? "候选假说生成" : "Candidate generation";
  if (nodeId === HYPOTHESIS_FIRST_SELECTION_NODE_ID) return lang === "zh" ? "假说选择" : "Hypothesis selection";
  if (nodeId.startsWith("hf_meeting_")) return lang === "zh"
    ? `第 ${nodeId.slice("hf_meeting_".length)} 轮讨论·评审`
    : `Review discussion · round ${nodeId.slice("hf_meeting_".length)}`;
  if (nodeId.startsWith("hf_collection_")) return lang === "zh" ? "资料搜集" : "Evidence collection";
  if (nodeId === HYPOTHESIS_FIRST_CONVERGENCE_NODE_ID) return lang === "zh" ? "假说收敛门" : "Hypothesis convergence gate";
  return lang === "zh" ? "当前任务" : "Current task";
}

function InspectorBody(props: {
  teamId: string;
  questionId: string;
  nodeId: string;
  liveMeetingRoundId: string;
  nextAction: HypothesisFirstNextAction;
  lang: Language;
  stageSummary?: { rounds: number; retries: number; kept: number } | null;
  onRetryCollection?: () => Promise<void>;
  onNavigateToNode?: (nodeId: string) => void;
  onOpenQuestion: (questionId: string) => void;
}) {
  const { nodeId, nextAction, teamId, questionId, liveMeetingRoundId, lang } = props;
  const isZh = lang === "zh";
  if (nodeId === HYPOTHESIS_FIRST_GENERATION_NODE_ID) {
    if (nextAction.stage === "selection_required") {
      return (
        <div className={styles.task}>
          <p className={styles.description}>
            {isZh ? "候选清单已确认，请在选择卡勾选假说。" : "The candidate list is ready; select hypotheses in the selection card."}
          </p>
          {props.onNavigateToNode ? (
            <VButton type="button" variant="primary" density="compact" onPress={() => props.onNavigateToNode?.(HYPOTHESIS_FIRST_SELECTION_NODE_ID)}>
              {isZh ? "前往假说选择" : "Go to hypothesis selection"}
            </VButton>
          ) : null}
        </div>
      );
    }
    if (nextAction.stage === "generation_missing") {
      return (
        <OpenGenerationButton
          teamId={teamId}
          questionId={questionId}
          label={nextAction.commandLabel || (isZh ? "生成候选假说" : "Generate candidate hypotheses")}
          lang={lang}
        />
      );
    }
    if (nextAction.meetingRoundId || liveMeetingRoundId) {
      return (
        <HypothesisFirstMeetingOps
          teamId={teamId}
          questionId={questionId}
          meetingRoundId={liveMeetingRoundId || nextAction.meetingRoundId || ""}
          nextAction={nextAction}
          compact
          lang={lang}
          onApproved={() => props.onNavigateToNode?.(HYPOTHESIS_FIRST_SELECTION_NODE_ID)}
        />
      );
    }
    return (
      <OpenGenerationButton
        teamId={teamId}
        questionId={questionId}
        label={nextAction.commandLabel || (isZh ? "生成候选假说" : "Generate candidate hypotheses")}
        lang={lang}
      />
    );
  }
  if (nodeId === HYPOTHESIS_FIRST_SELECTION_NODE_ID) {
    return <HypothesisSelectionList teamId={teamId} questionId={questionId} compact lang={lang} />;
  }
  if (nodeId.startsWith("hf_meeting_")) {
    if (!liveMeetingRoundId && !nextAction.meetingRoundId) {
      return <p className={styles.description}>{isZh ? "尚未找到对应评审讨论。" : "The matching review discussion was not found."}</p>;
    }
    return (
      <HypothesisFirstMeetingOps
        teamId={teamId}
        questionId={questionId}
        meetingRoundId={liveMeetingRoundId || nextAction.meetingRoundId || ""}
        nextAction={nextAction}
        compact
        lang={lang}
        onRetryCollection={props.onRetryCollection}
      />
    );
  }
  if (
    nodeId.startsWith("hf_collection_")
    || nextAction.stage === "collecting"
    || nextAction.stage === "collection_recovery"
    || nextAction.stage === "handoff_pending"
  ) {
    return (
      <CollectionTaskBody
        nextAction={nextAction}
        lang={lang}
        teamId={teamId}
        questionId={questionId}
        onRetryCollection={props.onRetryCollection}
      />
    );
  }
  if (nodeId === HYPOTHESIS_FIRST_CONVERGENCE_NODE_ID) {
    const summary = props.stageSummary;
    return (
      <div className={styles.task}>
        <VStateRow tone={nextAction.stage === "converged" ? "success" : "warning"}>
          {nextAction.statusMessage || nextAction.disabledReason || (isZh ? "待收敛" : "Awaiting convergence")}
        </VStateRow>
        {nextAction.stage === "converged" && summary ? (
          <div className={styles.stageSummary} data-testid="hypothesis-stage-summary">
            <strong>{isZh ? "✓ 假说阶段完成" : "✓ Hypothesis stage complete"}</strong>
            <p className={styles.status}>
              {isZh
                ? `${summary.rounds} 轮评审${summary.retries > 0 ? `（含 ${summary.retries} 次失败重试）` : ""} · 保留 ${summary.kept} 条假说进入正式研究`
                : `${summary.rounds} review rounds${summary.retries > 0 ? ` (${summary.retries} failed retries)` : ""} · ${summary.kept} hypotheses retained for formal research`}
            </p>
          </div>
        ) : null}
        {nextAction.stage === "converged" && nextAction.commandDetail ? (
          <p className={styles.status}>{nextAction.commandDetail}</p>
        ) : null}
        {nextAction.command === "human_adjudication" ? (
          <div className={styles.task}>
            <NextReviewRoundButton
              teamId={teamId}
              questionId={questionId}
              meetingRoundId={liveMeetingRoundId}
              lang={lang}
            />
            <VButton
              type="button"
              variant="ghost"
              density="compact"
              onClick={() => props.onOpenQuestion(questionId)}
            >
              {isZh ? "打开赛题详情" : "Open question details"}
            </VButton>
          </div>
        ) : null}
      </div>
    );
  }
  return (
    <VEmptyState title={isZh ? "未知的假说先行卡片" : "Unknown hypothesis-first card"}>
      <p className={styles.description}>
        {isZh ? "下一步：返回流程画布，选择一个有效的假说先行节点。" : "Next: return to the workflow canvas and choose a valid hypothesis-first node."}
      </p>
    </VEmptyState>
  );
}

function NextReviewRoundButton(props: { teamId: string; questionId: string; meetingRoundId: string; lang: Language }) {
  const queryClient = useQueryClient();
  const [blockedReason, setBlockedReason] = useState<string | null>(null);
  const mutation = useMutation({
    mutationFn: () =>
      openNextHypothesisReviewRound(props.teamId, props.meetingRoundId, 5),
    onSuccess: (payload) => {
      setBlockedReason(
        payload?.status === "budget_exhausted"
          ? (props.lang === "zh" ? "轮次预算已达上限 5，无法再开启新的评审轮。" : "The round budget has reached its limit of 5; no new review round can be opened.")
          : null,
      );
      invalidateHypothesisFirstQueries(queryClient, props.teamId, props.questionId);
    },
  });
  return (
    <div className={styles.task} data-testid="next-review-round-action">
      {blockedReason ? (
        <VErrorSummary label={props.lang === "zh" ? "无法开启新评审轮" : "Unable to open a new review round"} summary={blockedReason} />
      ) : null}
      {mutation.isError ? (
        <VErrorSummary
          label={props.lang === "zh" ? "发起下一轮评审失败" : "Failed to open the next review round"}
          summary={mutation.error instanceof Error ? mutation.error.message : "open_next_review_failed"}
        />
      ) : null}
      <VButton
        type="button"
        variant="primary"
        density="compact"
        isPending={mutation.isPending}
        isDisabled={!props.meetingRoundId}
        disabledReason={props.meetingRoundId ? undefined : (props.lang === "zh" ? "缺少上一轮评审标识" : "The previous review round ID is missing")}
        onPress={() => mutation.mutate()}
      >
        {props.lang === "zh" ? "提升预算并发起新一轮评审" : "Increase budget and open a new review round"}
      </VButton>
    </div>
  );
}

function OpenGenerationButton(props: { teamId: string; questionId: string; label: string; lang: Language }) {
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: () => openHypothesisCandidateGeneration(props.teamId, props.questionId),
    onSuccess: () => invalidateHypothesisFirstQueries(queryClient, props.teamId, props.questionId),
  });
  return (
    <div className={styles.task}>
      {mutation.isError ? (
        <VErrorSummary
          label={props.lang === "zh" ? "候选生成失败" : "Candidate generation failed"}
          summary={mutation.error instanceof Error ? mutation.error.message : "open_candidate_generation_failed"}
        />
      ) : null}
      <VButton
        type="button"
        variant="primary"
        density="compact"
        isPending={mutation.isPending}
        onPress={() => mutation.mutate()}
      >
        {props.label}
      </VButton>
    </div>
  );
}

function CollectionTaskBody(props: {
  nextAction: HypothesisFirstNextAction;
  lang: Language;
  teamId: string;
  questionId: string;
  onRetryCollection?: () => Promise<void>;
}) {
  const queryClient = useQueryClient();
  const isZh = props.lang === "zh";
  const requestId = props.nextAction.collectionRequestId || "";
  const collectionRunId = props.nextAction.collectionRunId || "";
  const canHandoff = props.nextAction.command === "retry_handoff"
    && Boolean(requestId)
    && Boolean(collectionRunId);
  const handoff = useMutation({
    mutationFn: () => recordCollectionHandoff(props.teamId, requestId, {
      handoffRef: `source_collection_run:${collectionRunId}`,
    }),
    onSuccess: () => invalidateHypothesisFirstQueries(queryClient, props.teamId, props.questionId),
  });
  return (
    <div className={styles.task}>
      <div role="status">
        <VStateRow tone={props.nextAction.stage === "collecting" ? "accent" : "warning"}>
          {props.nextAction.statusMessage || props.nextAction.recovery?.reason || (isZh ? "资料搜集" : "Evidence collection")}
        </VStateRow>
      </div>
      {handoff.isError ? (
        <VErrorSummary
          label={isZh ? "交接失败" : "Handoff failed"}
          summary={handoff.error instanceof Error ? handoff.error.message : "handoff_failed"}
        />
      ) : null}
      {props.nextAction.command === "retry_handoff" && canHandoff ? (
        <VButton
          type="button"
          variant="primary"
          density="compact"
          isPending={handoff.isPending}
          onPress={() => handoff.mutate()}
        >
          {props.nextAction.commandLabel}
        </VButton>
      ) : null}
      {(props.nextAction.command === "retry_collection" || props.nextAction.command === "continue_collection") && props.onRetryCollection ? (
        <VButton type="button" variant="primary" density="compact" onPress={() => void props.onRetryCollection?.()}>
          {props.nextAction.commandLabel}
        </VButton>
      ) : null}
    </div>
  );
}
