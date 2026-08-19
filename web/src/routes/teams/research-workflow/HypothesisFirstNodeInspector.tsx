/**
 * Live task inspector for hypothesis-first region cards.
 *
 * Canvas cards remain a projection. This panel is the current-task surface:
 * discussion, digest confirm, selection, collection progress, and recovery.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { fetchChatRoomDetail } from "../../../api/chat";
import {
  openHypothesisCandidateGeneration,
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
  resolveHypothesisFirstNextAction,
  type HypothesisFirstNextAction,
} from "./hypothesisFirstNextAction";
import { invalidateHypothesisFirstQueries, useHypothesisFirstChain } from "./useHypothesisFirstChain";
import styles from "./HypothesisFirstNodeInspector.styles";

export type HypothesisFirstNodeInspectorProps = {
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
    return reviews.find((item) => (item.roundIndex ?? 0) === roundIndex) ?? reviews.at(-1) ?? null;
  }
  return reviews.at(-1) ?? null;
}

function inspectorNodeOwnsCurrentStep(nodeId: string, targetNodeId: string | null): boolean {
  if (!targetNodeId) return true;
  if (nodeId === targetNodeId) return true;
  return nodeId.startsWith("hf_collection_") && targetNodeId === "source_finding";
}

export function HypothesisFirstNodeInspector({
  teamId,
  questionId,
  nodeId,
  runId = "",
  onOpenQuestion,
  collectionChildStatus = null,
  onNavigateToNode,
  onRetryCollection,
}: HypothesisFirstNodeInspectorProps) {
  const chain = useHypothesisFirstChain(teamId, questionId);
  const generation = pickGeneration(chain.meetings);
  const review = pickReview(chain.meetings, nodeId);
  const activeMeeting = nodeId === HYPOTHESIS_FIRST_GENERATION_NODE_ID ? generation : review;
  const roomQuery = useQuery({
    queryKey: queryKeys.chatRoom(activeMeeting?.linkedChatRoomId || ""),
    queryFn: ({ signal }) => fetchChatRoomDetail(activeMeeting?.linkedChatRoomId || "", { signal }),
    enabled: Boolean(activeMeeting?.linkedChatRoomId) && activeMeeting?.status === "open",
    refetchInterval: activeMeeting?.status === "open" ? 4_000 : false,
  });
  const nextAction = resolveHypothesisFirstNextAction({
    run: { runId: runId || (questionId ? "present" : "") },
    chainState: chain.chainState,
    meetings: chain.meetings,
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

  if (!questionId) {
    return <VEmptyState title="缺少题目上下文">该卡片需要题目上下文才能继续当前任务。</VEmptyState>;
  }
  if (chain.loading) {
    return <VStateSurface tone="loading" title="加载假说先行任务" fill className={styles.fill} />;
  }
  if (chain.error) {
    return (
      <VSurface tone="panel" className={styles.panel} data-vui="hypothesis-first-node-error">
        <div role="alert">假说先行链加载失败：{chain.error}</div>
      </VSurface>
    );
  }

  return (
    <VSurface tone="panel" className={styles.panel} data-vui="hypothesis-first-node-detail">
      <header>
        <div className={styles.stage}>假说先行</div>
        <h3 className={styles.title}>{inspectorTitle(nodeId)}</h3>
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
          onRetryCollection={onRetryCollection}
          onNavigateToNode={onNavigateToNode}
          onOpenQuestion={onOpenQuestion}
        />
      ) : (
        <div className={styles.task} data-testid="hypothesis-first-previous-step-pending">
          <VStateRow tone="warning">
            {nodeId === HYPOTHESIS_FIRST_CONVERGENCE_NODE_ID
              ? "前序任务尚未完成，请先处理当前步骤。"
              : "当前任务在其他步骤，请前往当前步骤。"}
          </VStateRow>
          {nextAction.targetNodeId && onNavigateToNode ? (
            <VButton
              type="button"
              variant="primary"
              density="compact"
              onPress={() => onNavigateToNode(nextAction.targetNodeId || HYPOTHESIS_FIRST_GENERATION_NODE_ID)}
            >
              前往当前步骤
            </VButton>
          ) : null}
        </div>
      )}
      <div className={styles.secondary}>
        <VButton type="button" variant="ghost" density="compact" onClick={() => onOpenQuestion(questionId)}>
          打开赛题详情
        </VButton>
      </div>
    </VSurface>
  );
}

function inspectorTitle(nodeId: string): string {
  if (nodeId === HYPOTHESIS_FIRST_GENERATION_NODE_ID) return "候选假说生成";
  if (nodeId === HYPOTHESIS_FIRST_SELECTION_NODE_ID) return "假说选择";
  if (nodeId.startsWith("hf_meeting_")) return `第 ${nodeId.slice("hf_meeting_".length)} 轮讨论·评审`;
  if (nodeId.startsWith("hf_collection_")) return "资料搜集";
  if (nodeId === HYPOTHESIS_FIRST_CONVERGENCE_NODE_ID) return "假说收敛门";
  return "当前任务";
}

function InspectorBody(props: {
  teamId: string;
  questionId: string;
  nodeId: string;
  liveMeetingRoundId: string;
  nextAction: HypothesisFirstNextAction;
  onRetryCollection?: () => Promise<void>;
  onNavigateToNode?: (nodeId: string) => void;
  onOpenQuestion: (questionId: string) => void;
}) {
  const { nodeId, nextAction, teamId, questionId, liveMeetingRoundId } = props;
  if (nodeId === HYPOTHESIS_FIRST_GENERATION_NODE_ID) {
    if (nextAction.stage === "selection_required") {
      return (
        <div className={styles.task}>
          <p className={styles.description}>候选清单已确认，请在选择卡勾选假说。</p>
          {props.onNavigateToNode ? (
            <VButton type="button" variant="primary" density="compact" onPress={() => props.onNavigateToNode?.(HYPOTHESIS_FIRST_SELECTION_NODE_ID)}>
              前往假说选择
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
          label={nextAction.commandLabel || "生成候选假说"}
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
          onApproved={() => props.onNavigateToNode?.(HYPOTHESIS_FIRST_SELECTION_NODE_ID)}
        />
      );
    }
    return (
      <OpenGenerationButton
        teamId={teamId}
        questionId={questionId}
        label={nextAction.commandLabel || "生成候选假说"}
      />
    );
  }
  if (nodeId === HYPOTHESIS_FIRST_SELECTION_NODE_ID) {
    return <HypothesisSelectionList teamId={teamId} questionId={questionId} compact />;
  }
  if (nodeId.startsWith("hf_meeting_")) {
    if (!liveMeetingRoundId && !nextAction.meetingRoundId) {
      return <p className={styles.description}>尚未找到对应评审讨论。</p>;
    }
    return (
      <HypothesisFirstMeetingOps
        teamId={teamId}
        questionId={questionId}
        meetingRoundId={liveMeetingRoundId || nextAction.meetingRoundId || ""}
        nextAction={nextAction}
        compact
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
        teamId={teamId}
        questionId={questionId}
        onRetryCollection={props.onRetryCollection}
      />
    );
  }
  if (nodeId === HYPOTHESIS_FIRST_CONVERGENCE_NODE_ID) {
    return (
      <div className={styles.task}>
        <VStateRow tone={nextAction.stage === "converged" ? "success" : "warning"}>
          {nextAction.statusMessage || nextAction.disabledReason || "待收敛"}
        </VStateRow>
        {nextAction.command === "human_adjudication" ? (
          <VButton type="button" variant="primary" density="compact" onClick={() => props.onOpenQuestion(questionId)}>
            {nextAction.commandLabel}
          </VButton>
        ) : null}
      </div>
    );
  }
  return <VEmptyState title="未知的假说先行卡片" />;
}

function OpenGenerationButton(props: { teamId: string; questionId: string; label: string }) {
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: () => openHypothesisCandidateGeneration(props.teamId, props.questionId),
    onSuccess: () => invalidateHypothesisFirstQueries(queryClient, props.teamId, props.questionId),
  });
  return (
    <div className={styles.task}>
      {mutation.isError ? (
        <VErrorSummary
          label="候选生成失败"
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
  teamId: string;
  questionId: string;
  onRetryCollection?: () => Promise<void>;
}) {
  const queryClient = useQueryClient();
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
          {props.nextAction.statusMessage || props.nextAction.recovery?.reason || "资料搜集"}
        </VStateRow>
      </div>
      {handoff.isError ? (
        <VErrorSummary
          label="交接失败"
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
