/**
 * Live task inspector for hypothesis-first region cards.
 *
 * Canvas cards remain a projection. This panel is the current-task surface:
 * discussion, digest confirm, selection, collection progress, and recovery.
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { fetchChatRoomDetail } from "../../../api/chat";
import { getChallengeQuestionRunDetail } from "../../../api/challengeQuestionRuns";
import {
  executeHypothesisFirstCommand,
  isFetchJsonHttpError,
  isHypothesisFirstCommandStateConflict,
  openHypothesisCandidateGeneration,
  openNextHypothesisReviewRound,
  parseClaimBeliefGate,
  recordCollectionHandoff,
} from "../../../api/hypothesisFirst";
import { queryKeys } from "../../../api/queryKeys";
import type {
  CommandAction,
  HypothesisFirstChainState,
  HypothesisFirstClaimBeliefGate,
  HypothesisFirstStateV2,
  MeetingRoundRecord,
  WorkflowProblem,
} from "../../../api/types/hypothesisFirst";
import {
  VActionGroup,
  VButton,
  VConfirmDialog,
  VEmptyState,
  VErrorSummary,
  VInput,
  VStateRow,
  VStateSurface,
  VStatusChip,
  VSurface,
} from "../../../components/vui";
import { HypothesisSelectionList } from "../challenge-cup/HypothesisSelectionList";
import { ChallengeQuestionReviewForm } from "../challenge-cup/ChallengeQuestionReviewForm";
import {
  HYPOTHESIS_FIRST_CONVERGENCE_NODE_ID,
  HYPOTHESIS_FIRST_COLLECTION_NODE_ID,
  HYPOTHESIS_FIRST_GENERATION_NODE_ID,
  HYPOTHESIS_FIRST_REVIEW_NODE_ID,
  HYPOTHESIS_FIRST_SELECTION_NODE_ID,
  isHypothesisReviewRetryAttempt,
} from "./hypothesisFirstCanvasRegion";
import { HypothesisFirstMeetingOps } from "./HypothesisFirstMeetingOps";
import {
  buildHypothesisFirstReviewProjection,
  currentProjectedReview,
} from "./hypothesisFirstMeetingProjection";
import {
  boundChatRoundsAreTerminal,
  meetingsForHypothesisFirstQuestion,
  resolveHypothesisFirstNextAction,
  type HypothesisFirstNextAction,
} from "./hypothesisFirstNextAction";
import { resolveHypothesisFirstNextActionFromV2 } from "./hypothesisFirstStateV2Adapter";
import type { HypothesisFirstV2NextAction } from "./hypothesisFirstStateV2Adapter";
import { invalidateHypothesisFirstQueries, resolveHypothesisFirstRoundBudget, useHypothesisFirstChain } from "./useHypothesisFirstChain";
import { resolvePollingInterval, usePageVisibility } from "../../../app/pollingPolicy";
import type { ScopedDiscussionModel } from "./scopedDiscussionModel";
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
  onFormalRunCreated?: (input: {
    runId: string;
    nodeId: string;
    questionId: string;
  }) => void;
  onRetryCollection?: () => Promise<void>;
  discussionModel?: ScopedDiscussionModel;
  /** Formal run-level actions do not require a selected canvas node. */
  formalRuntime?: boolean;
};

export function inspectorScopedRoomId(
  discussionModel: ScopedDiscussionModel | undefined,
  meeting: MeetingRoundRecord | null,
  questionId: string,
): string {
  if (
    !discussionModel
    || discussionModel.status !== "ready"
    || !discussionModel.roomId
    || !discussionModel.meetingRoundId
    || discussionModel.questionId !== questionId
    || discussionModel.scope?.questionId !== questionId
    || discussionModel.meetingRoundId !== meeting?.meetingRoundId
  ) {
    return "";
  }
  const expectedMeetingType = discussionModel.scope?.kind === "question_generation"
    ? "hypothesis_candidate_generation"
    : "hypothesis_review";
  return meeting.meetingType === expectedMeetingType ? discussionModel.roomId : "";
}

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
  reviewRoundLinks: ReturnType<typeof useHypothesisFirstChain>["reviewRoundLinks"],
  selectionId?: string | null,
) {
  const projection = buildHypothesisFirstReviewProjection(meetings, reviewRoundLinks, selectionId);
  if (nodeId.startsWith("hf_meeting_")) {
    // No fallback to the latest round: a future round card must show its
    // "not yet opened" empty state instead of another round's operations.
    return projection.byNodeId.get(nodeId)?.meeting ?? null;
  }
  return currentProjectedReview(projection)?.meeting ?? null;
}

function checklistRoundIndex(
  projection: ReturnType<typeof buildHypothesisFirstReviewProjection>,
  currentTargetNodeId: string | null | undefined,
  selectedNodeId: string,
): number | null {
  return projection.byNodeId.get(String(currentTargetNodeId ?? ""))?.roundIndex
    ?? projection.byNodeId.get(selectedNodeId)?.roundIndex
    ?? currentProjectedReview(projection)?.roundIndex
    ?? null;
}

export function inspectorNodeOwnsCurrentStep(nodeId: string, targetNodeId: string | null): boolean {
  // A missing target is not proof that this card owns the live command.
  // Fail closed so stale/history cards never expose write operations while
  // the chain scope is loading or cannot resolve the current step.
  if (!targetNodeId) return false;
  if (nodeId === targetNodeId) return true;
  if (nodeId === HYPOTHESIS_FIRST_REVIEW_NODE_ID && targetNodeId.startsWith("hf_meeting_")) return true;
  if (
    (nodeId === HYPOTHESIS_FIRST_COLLECTION_NODE_ID || nodeId.startsWith("hf_collection_"))
    && (targetNodeId === "source_finding" || targetNodeId.startsWith("hf_collection_"))
  ) return true;
  return false;
}

type ReviewRoundBudgetSnapshot = {
  stateV2?: { convergence?: { roundBudget?: number; roundIndex?: number } | null } | null;
  chainState?: { roundBudget?: number; hypothesisRoundCount?: number } | null;
};

// ---------------------------------------------------------------------------
// Review rounds have one server-owned budget. The resolver authority lives in
// useHypothesisFirstChain (V2 convergence → V1 chain state → hard limit);
// per-round records may retain historical roundBudget values, but they are
// not mutable budget authority.
// ---------------------------------------------------------------------------
export function resolveHypothesisFirstReviewRoundBudget(
  snapshot: ReviewRoundBudgetSnapshot,
): number {
  return resolveHypothesisFirstRoundBudget(snapshot);
}

/** 当前轮序 M（开启新轮即 M+1）；快照缺失时返回 null，文案降级为不提轮次。 */
export function resolveHypothesisFirstNextReviewRoundIndex(
  snapshot: ReviewRoundBudgetSnapshot,
): number | null {
  const v2Index = snapshot.stateV2?.convergence?.roundIndex;
  if (typeof v2Index === "number" && Number.isFinite(v2Index) && v2Index >= 0) {
    return v2Index + 1;
  }
  const v1Count = snapshot.chainState?.hypothesisRoundCount;
  if (typeof v1Count === "number" && Number.isFinite(v1Count) && v1Count >= 0) {
    return v1Count + 1;
  }
  return null;
}

/** 服务端快照解析出的轮次上限 M；文案读「第 N 轮 / 上限 M」。 */
export function reviewRoundActionCopy(
  nextRoundIndex: number | null,
  lang: Language,
  roundBudget: number,
): { label: string; detail: string } {
  const isZh = lang === "zh";
  return {
    label: isZh ? "发起新一轮评审" : "Open a new review round",
    detail: nextRoundIndex !== null
      ? (isZh
        ? `本轮尚未收敛，将在上限 ${roundBudget} 内开启第 ${nextRoundIndex} 轮评审。`
        : `This review has not converged; opening round ${nextRoundIndex} within the limit of ${roundBudget}.`)
      : (isZh
        ? `本轮尚未收敛，将在上限 ${roundBudget} 内开启新一轮评审。`
        : `This review has not converged; opening another round within the limit of ${roundBudget}.`),
  };
}

export type DiscussionMemberCompletion = { spoken: number; total: number };

// ---------------------------------------------------------------------------
// Claim belief hard gate (R2.2): server-authored verdict on the recommended
// candidate's claim evidence. Bilingual copy helpers + panel composed from the
// existing VUI primitives and local styles — no new VUI component.
// ---------------------------------------------------------------------------

const CLAIM_GATE_REASONS: Record<string, { zh: string; en: string }> = {
  claim_data_missing: { zh: "claim 数据缺失", en: "claim data missing" },
  claim_ledger_unavailable: { zh: "claim 台账不可用", en: "claim ledger unavailable" },
  claim_evidence_store_unavailable: { zh: "claim 证据库不可用", en: "claim evidence store unavailable" },
  candidate_claim_binding_missing: { zh: "候选未绑定核心 claim", en: "candidate claim binding missing" },
  claim_ledger_entry_unreadable: { zh: "claim 台账条目不可读", en: "claim ledger entry unreadable" },
  claim_belief_evaluation_failed: { zh: "claim 置信评估失败", en: "claim belief evaluation failed" },
  candidate_evidence_gap: { zh: "已接受证据存在缺口", en: "accepted evidence gaps remain" },
  claim_belief_state_blocked: { zh: "核心 claim 被反证或争议中", en: "a core claim is contradicted or disputed" },
  claim_belief_gate_unavailable: { zh: "置信门评估不可用", en: "gate evaluation unavailable" },
};

const CLAIM_GATE_BELIEF_STATES: Record<string, { zh: string; en: string }> = {
  contradicted: { zh: "被反证", en: "contradicted" },
  disputed: { zh: "争议中", en: "disputed" },
  unknown: { zh: "状态未知", en: "unknown" },
};

const CLAIM_GATE_PROBLEMS: Record<string, { zh: string; en: string }> = {
  ledger_entry_invalid: { zh: "台账条目无效", en: "ledger entry invalid" },
  belief_entry_missing: { zh: "置信条目缺失", en: "belief entry missing" },
};

const CLAIM_GATE_GAPS: Record<string, { zh: string; en: string }> = {
  accepted_support_missing: { zh: "缺少已接受的支持证据", en: "no accepted supporting evidence" },
  accepted_counter_or_boundary_missing: { zh: "缺少已接受的反证/边界证据", en: "no accepted counter/boundary evidence" },
};

function claimGateReasonLabel(reason: string, isZh: boolean): string {
  const key = String(reason || "").trim();
  const mapped = CLAIM_GATE_REASONS[key];
  return mapped ? (isZh ? mapped.zh : mapped.en) : key || (isZh ? "原因未知" : "unknown reason");
}

function claimGateBlockedClaimLabel(claim: HypothesisFirstClaimBeliefGate["blockedClaims"][number], isZh: boolean): string {
  const problem = CLAIM_GATE_PROBLEMS[String(claim.problem || "")];
  if (problem) return isZh ? problem.zh : problem.en;
  const belief = CLAIM_GATE_BELIEF_STATES[String(claim.beliefState || "unknown")];
  return belief ? (isZh ? belief.zh : belief.en) : String(claim.beliefState || "unknown");
}

function claimGateStatusView(status: HypothesisFirstClaimBeliefGate["status"], isZh: boolean): {
  label: string;
  tone: "success" | "danger" | "neutral";
} {
  if (status === "allowed") return { label: isZh ? "已通过" : "Passed", tone: "success" };
  if (status === "blocked") return { label: isZh ? "未通过" : "Blocked", tone: "danger" };
  return { label: isZh ? "门禁状态未知" : "Gate status unknown", tone: "neutral" };
}

function ClaimBeliefGatePanel({ gate, lang }: { gate: HypothesisFirstClaimBeliefGate; lang: Language }) {
  const isZh = lang === "zh";
  const status = claimGateStatusView(gate.status, isZh);
  return (
    <section
      className={styles.candidateChecklist}
      data-testid="claim-belief-gate-panel"
      aria-label={isZh ? "claim 置信门" : "Claim belief gate"}
    >
      <div className={styles.candidateChecklistSummary}>
        <strong>{isZh ? "claim 置信门" : "Claim belief gate"}</strong>
        <VStatusChip tone={status.tone}>{status.label}</VStatusChip>
      </div>
      <p className={styles.status}>
        {isZh ? "原因：" : "Reason: "}
        {claimGateReasonLabel(gate.reason, isZh)}
      </p>
      {gate.candidateId ? (
        <p className={styles.status}>
          {isZh ? `入选候选：${gate.candidateId}` : `Recommended candidate: ${gate.candidateId}`}
        </p>
      ) : null}
      {gate.blockedClaims.length ? (
        <ul className={styles.candidateChecklistList}>
          {gate.blockedClaims.map((claim, index) => (
            <li className={styles.candidateChecklistItem} key={`${claim.claimId}:${index}`}>
              <div className={styles.candidateChecklistIdentity}>
                <strong>{claim.claimId}</strong>
                <span>{claimGateBlockedClaimLabel(claim, isZh)}</span>
              </div>
              <VStatusChip tone="danger">{isZh ? "阻断收敛" : "Blocking"}</VStatusChip>
            </li>
          ))}
        </ul>
      ) : null}
      {gate.evidenceGaps.length ? (
        <ul className={styles.bulletedList}>
          {gate.evidenceGaps.map((gap, index) => {
            const mapped = CLAIM_GATE_GAPS[String(gap.gap || "")];
            return (
              <li key={`${gap.claimId}:${gap.gap}:${index}`}>
                {gap.claimId}
                {isZh ? "：" : ": "}
                {mapped ? (isZh ? mapped.zh : mapped.en) : gap.gap}
              </li>
            );
          })}
        </ul>
      ) : null}
    </section>
  );
}

/**
 * x/y 位成员已发言：分母是房间成员数，分子按消息 sender 去重（仅统计已完成、
 * 内容非空且归属房间成员的发言）。与 HypothesisFirstMeetingOps 的
 * completedSourceMessageCount（完成消息条数统计）语义不同，互不复用。
 */
export function discussionMemberCompletion(detail: {
  participants?: ReadonlyArray<{ participantId?: string; agentCode?: string; kind?: string }>;
  rounds?: ReadonlyArray<{
    messages?: ReadonlyArray<{
      participantId?: string;
      speakerCode?: string;
      speakerTitle?: string;
      status?: string;
      content?: string;
    }>;
  }>;
} | undefined): DiscussionMemberCompletion | null {
  const participants = detail?.participants ?? [];
  if (!participants.length) return null;
  const memberKeys = new Set<string>();
  for (const participant of participants) {
    const key = String(participant.participantId ?? "").trim();
    if (key) memberKeys.add(key);
  }
  if (!memberKeys.size) return null;
  const spoken = new Set<string>();
  for (const round of detail?.rounds ?? []) {
    for (const message of round.messages ?? []) {
      if (String(message.status ?? "").trim().toLowerCase() !== "completed") continue;
      if (!String(message.content ?? "").trim()) continue;
      const senderKey = String(message.participantId ?? "").trim();
      if (senderKey && memberKeys.has(senderKey)) spoken.add(senderKey);
    }
  }
  return { spoken: Math.min(spoken.size, memberKeys.size), total: memberKeys.size };
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
  onFormalRunCreated,
  onRetryCollection,
  discussionModel,
  formalRuntime = false,
}: HypothesisFirstNodeInspectorProps) {
  const isZh = lang === "zh";
  const queryClient = useQueryClient();
  const [retrying, setRetrying] = useState(false);
  const chain = useHypothesisFirstChain(teamId, questionId, runId);
  const questionMeetings = meetingsForHypothesisFirstQuestion(chain.meetings, questionId);
  const generation = pickGeneration(questionMeetings);
  const currentSelectionId = chain.selection?.selectionId || chain.chainState?.selectionId || "";
  const reviewProjection = buildHypothesisFirstReviewProjection(
    questionMeetings,
    chain.reviewRoundLinks,
    currentSelectionId,
  );
  const review = pickReview(questionMeetings, nodeId, chain.reviewRoundLinks, currentSelectionId);
  const activeMeeting = nodeId === HYPOTHESIS_FIRST_GENERATION_NODE_ID ? generation : review;
  const scopedRoomId = inspectorScopedRoomId(discussionModel, activeMeeting, questionId);
  const pageVisible = usePageVisibility();
  const roomQuery = useQuery({
    queryKey: queryKeys.chatRoom(scopedRoomId),
    queryFn: ({ signal }) => fetchChatRoomDetail(scopedRoomId, { signal }),
    enabled: !chain.scopeMismatch && Boolean(scopedRoomId) && activeMeeting?.status === "open",
    refetchInterval: activeMeeting?.status === "open"
      ? resolvePollingInterval(pageVisible, 4_000)
      : false,
  });
  if (chain.scopeMismatch) {
    return (
      <VSurface tone="panel" className={styles.panel} data-testid="hypothesis-first-scope-mismatch">
        <VStateRow tone="warning">
          {isZh
            ? "流程上下文与当前题目或运行不一致，已隐藏写操作。请刷新后重试。"
            : "The workflow scope does not match the current question or run; write actions are hidden. Refresh and try again."}
        </VStateRow>
      </VSurface>
    );
  }
  const selectedProjectedReview = reviewProjection.byNodeId.get(nodeId)
    ?? (activeMeeting ? reviewProjection.byMeetingId.get(activeMeeting.meetingRoundId) : undefined);
  const nextAction = chain.stateV2
    ? resolveHypothesisFirstNextActionFromV2(chain.stateV2, {
        preferredCandidateId: selectedProjectedReview?.candidateId,
        preferredMeetingRoundId: activeMeeting?.meetingRoundId,
      })
    : resolveHypothesisFirstNextAction({
    run: { runId: runId || (questionId ? "present" : "") },
    chainState: chain.chainState,
    meetings: questionMeetings,
    reviewRoundLinks: chain.reviewRoundLinks,
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
  const currentChecklistRoundIndex = checklistRoundIndex(
    reviewProjection,
    nextAction.targetNodeId,
    nodeId,
  );
  const canonicalChecklistRows = chain.stateV2?.review.candidates.map((candidate) => {
    const pendingQueueKind: "discussing" | "inflight" | "queued" | undefined = (() => {
      if (
        candidate.lifecycle === "completed"
        || candidate.lifecycle === "failed"
        || candidate.actionability === "blocked"
      ) {
        return undefined;
      }
      // 开候选会串行、讨论线程池并发 2：discussion.running 即正在讨论，
      // summarization/approval 在途的既不算讨论也不算排队。
      if (candidate.discussion?.lifecycle === "running") return "discussing";
      if (
        candidate.summarization?.lifecycle === "running"
        || candidate.approval?.lifecycle === "waiting_human"
      ) return "inflight";
      return "queued";
    })();
    return {
      candidateId: candidate.candidateId,
      roundIndex: candidate.roundIndex,
      nodeId: `hf_meeting_${candidate.roundIndex}_${encodeURIComponent(candidate.candidateId)}`,
      kind: candidate.lifecycle === "completed"
        ? "confirmed" as const
        : candidate.lifecycle === "failed" || candidate.actionability === "blocked"
          ? "blocked" as const
          : "pending" as const,
      queueKind: pendingQueueKind,
    };
  }) ?? null;
  const nodeOwnsCurrentStep = !chain.scopeMismatch && (formalRuntime
    || inspectorNodeOwnsCurrentStep(nodeId, nextAction.targetNodeId));
  const reviewMeetings = questionMeetings.filter(
    (meeting) => meeting.meetingType === "hypothesis_review",
  );
  const reviewHistory = reviewMeetings
    .filter((meeting) => !isHypothesisReviewRetryAttempt(meeting))
    .sort((left, right) => (left.roundIndex ?? 0) - (right.roundIndex ?? 0));
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
  const discussionCompletion = discussionMemberCompletion(roomQuery.data);
  const showDiscussionCompletion = Boolean(
    nodeOwnsCurrentStep
    && scopedRoomId
    && activeMeeting?.status === "open"
    && discussionCompletion
    && (
      nodeId === HYPOTHESIS_FIRST_GENERATION_NODE_ID
      || nodeId === HYPOTHESIS_FIRST_REVIEW_NODE_ID
      || nodeId.startsWith("hf_meeting_")
    ),
  );

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
                  queryKey: queryKeys.hypothesisFirstSelectionContext(teamId, questionId, runId),
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
      {showDiscussionCompletion ? (
        <div role="status" className={styles.status} data-testid="discussion-member-completion">
          {isZh
            ? `${discussionCompletion?.spoken}/${discussionCompletion?.total} 位成员已发言`
            : `${discussionCompletion?.spoken}/${discussionCompletion?.total} members have spoken`}
        </div>
      ) : null}
      {nodeOwnsCurrentStep ? (
        <>
          <InspectorBody
            teamId={teamId}
            questionId={questionId}
            runId={runId}
            nodeId={nodeId}
            liveMeetingRoundId={activeMeeting?.meetingRoundId || nextAction.meetingRoundId || ""}
            nextAction={nextAction}
            lang={lang}
            stageSummary={stageSummary}
            onRetryCollection={onRetryCollection}
            onNavigateToNode={onNavigateToNode}
            onFormalRunCreated={onFormalRunCreated}
            onOpenQuestion={onOpenQuestion}
            stateV2={chain.stateV2}
            chainState={chain.chainState}
            formalRuntime={formalRuntime}
          />
          {(
            nodeId === HYPOTHESIS_FIRST_REVIEW_NODE_ID
            || nodeId.startsWith("hf_meeting_")
            || nodeId === HYPOTHESIS_FIRST_CONVERGENCE_NODE_ID
          ) ? (
            <ReviewCandidateChecklist
              rows={canonicalChecklistRows ?? reviewProjection.rounds.map((round) => ({
                candidateId: round.candidateId,
                roundIndex: round.roundIndex,
                nodeId: round.nodeId,
                kind: reviewCandidateState(round.meeting),
              }))}
              currentRoundIndex={chain.stateV2?.review.activeRoundIndex ?? currentChecklistRoundIndex}
              lang={lang}
              onNavigateToNode={onNavigateToNode}
            />
          ) : null}
          {nodeId === HYPOTHESIS_FIRST_REVIEW_NODE_ID ? (
            <ReviewHistory meetings={reviewHistory} allMeetings={reviewMeetings} lang={lang} />
          ) : null}
        </>
      ) : nodeId === HYPOTHESIS_FIRST_REVIEW_NODE_ID ? (
        <ReviewHistory meetings={reviewHistory} allMeetings={reviewMeetings} lang={lang} />
      ) : (
        <div className={styles.task} data-testid="hypothesis-first-previous-step-pending">
          <VStateRow tone="warning">
            {!nextAction.targetNodeId
              ? (isZh ? "当前步骤尚未确定，写操作已暂时隐藏。" : "The current step is unresolved; write actions are temporarily hidden.")
              : nodeId === HYPOTHESIS_FIRST_CONVERGENCE_NODE_ID
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
          {isZh ? "打开题目档案" : "Open question archive"}
        </VButton>
      </div>
    </VSurface>
  );
}

function reviewCandidateState(meeting: MeetingRoundRecord): "confirmed" | "blocked" | "pending" {
  if (meeting.status === "closed") {
    return "confirmed";
  }
  if (["failed", "blocked", "cancelled", "canceled"].includes(meeting.status)) {
    return "blocked";
  }
  return "pending";
}

function ReviewCandidateChecklist({
  rows,
  currentRoundIndex,
  lang,
  onNavigateToNode,
}: {
  rows: readonly {
    candidateId: string;
    roundIndex: number;
    nodeId: string;
    kind: "confirmed" | "blocked" | "pending";
    /** V2-only queue awareness; legacy projection rows omit it. */
    queueKind?: "discussing" | "inflight" | "queued";
  }[];
  currentRoundIndex: number | null;
  lang: Language;
  onNavigateToNode?: (nodeId: string) => void;
}) {
  const currentRounds = currentRoundIndex === null
    ? []
    : rows.filter((round) => round.roundIndex === currentRoundIndex);
  if (!currentRounds.length) return null;
  const confirmed = currentRounds.filter((state) => state.kind === "confirmed").length;
  const blocked = currentRounds.filter((state) => state.kind === "blocked").length;
  const pending = currentRounds.length - confirmed - blocked;
  // 位次感知只在 V2 canonical rows 提供完整 queue 标签时启用，避免用旧会议
  // 投影猜出一个假的排队数。
  const allPendingTagged = currentRounds
    .every((row) => row.kind !== "pending" || typeof row.queueKind === "string");
  const discussing = allPendingTagged
    ? currentRounds.filter((row) => row.kind === "pending" && row.queueKind === "discussing").length
    : 0;
  const queued = allPendingTagged
    ? currentRounds.filter((row) => row.kind === "pending" && row.queueKind === "queued").length
    : 0;
  const isZh = lang === "zh";
  return (
    <section className={styles.candidateChecklist} aria-label={isZh ? "候选确认清单" : "Candidate confirmation checklist"} data-testid="candidate-confirmation-checklist">
      <div className={styles.candidateChecklistSummary}>
        <strong>{isZh ? "候选确认清单" : "Candidate confirmation checklist"}</strong>
        <span>{isZh
          ? `共 ${currentRounds.length} · 已确认 ${confirmed} · 待确认 ${pending}${blocked ? ` · 已阻塞 ${blocked}` : ""}${discussing || queued ? ` · 正在讨论 ${discussing} 个 · 排队等待 ${queued} 个` : ""}`
          : `${currentRounds.length} total · ${confirmed} confirmed · ${pending} pending${blocked ? ` · ${blocked} blocked` : ""}${discussing || queued ? ` · ${discussing} in discussion · ${queued} queued` : ""}`}
        </span>
      </div>
      <ol className={styles.candidateChecklistList}>
        {currentRounds.map((round, index) => {
          const state = round.kind;
          const identity = isZh ? `候选 ${round.candidateId}` : `Candidate ${round.candidateId}`;
          const label = state === "confirmed"
            ? (isZh ? "已确认" : "Confirmed")
            : state === "blocked"
              ? (isZh ? "已阻塞" : "Blocked")
              : (isZh ? "待确认" : "Pending");
          const tone = state === "confirmed" ? "success" : state === "blocked" ? "warning" : "neutral";
          return (
            <li className={styles.candidateChecklistItem} key={round.nodeId}>
              <div className={styles.candidateChecklistIdentity}>
                <strong>{identity}</strong>
                <span>{isZh ? `第 ${round.roundIndex} 轮` : `Round ${round.roundIndex}`}</span>
              </div>
              <VStatusChip tone={tone}>{label}</VStatusChip>
              {onNavigateToNode ? (
                <VButton
                  type="button"
                  variant={state === "pending" ? "primary" : "ghost"}
                  density="compact"
                  onPress={() => onNavigateToNode(round.nodeId)}
                >
                  {isZh ? "查看该候选评审" : "View candidate review"}
                </VButton>
              ) : null}
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function inspectorTitle(nodeId: string, lang: Language): string {
  if (nodeId === HYPOTHESIS_FIRST_GENERATION_NODE_ID) return lang === "zh" ? "候选假说生成" : "Candidate generation";
  if (nodeId === HYPOTHESIS_FIRST_SELECTION_NODE_ID) return lang === "zh" ? "假说选择" : "Hypothesis selection";
  if (nodeId === HYPOTHESIS_FIRST_REVIEW_NODE_ID) return lang === "zh" ? "假说评审" : "Hypothesis review";
  if (nodeId.startsWith("hf_meeting_")) {
    const reviewTarget = nodeId.slice("hf_meeting_".length);
    const separator = reviewTarget.indexOf("_");
    const round = separator >= 0 ? reviewTarget.slice(0, separator) : reviewTarget;
    const encodedCandidate = separator >= 0 ? reviewTarget.slice(separator + 1) : "";
    let candidateId = encodedCandidate;
    try {
      candidateId = decodeURIComponent(encodedCandidate);
    } catch {
      // The id is display-only. Preserve the raw server token if it is malformed.
    }
    return lang === "zh"
      ? `第 ${round} 轮讨论·${candidateId ? `候选 ${candidateId}` : "评审"}`
      : `Review discussion · round ${round}${candidateId ? ` · candidate ${candidateId}` : ""}`;
  }
  if (nodeId.startsWith("hf_collection_")) return lang === "zh" ? "资料搜集" : "Evidence collection";
  if (nodeId === HYPOTHESIS_FIRST_COLLECTION_NODE_ID) return lang === "zh" ? "资料补充" : "Evidence collection";
  if (nodeId === HYPOTHESIS_FIRST_CONVERGENCE_NODE_ID) return lang === "zh" ? "假说收敛门" : "Hypothesis convergence gate";
  return lang === "zh" ? "当前任务" : "Current task";
}

function InspectorBody(props: {
  teamId: string;
  questionId: string;
  runId: string;
  nodeId: string;
  liveMeetingRoundId: string;
  nextAction: HypothesisFirstNextAction;
  lang: Language;
  stageSummary?: { rounds: number; retries: number; kept: number } | null;
  onRetryCollection?: () => Promise<void>;
  onNavigateToNode?: (nodeId: string) => void;
  onFormalRunCreated?: HypothesisFirstNodeInspectorProps["onFormalRunCreated"];
  onOpenQuestion: (questionId: string) => void;
  stateV2?: HypothesisFirstStateV2 | null;
  chainState?: HypothesisFirstChainState | null;
  formalRuntime?: boolean;
}) {
  const { nodeId, nextAction, teamId, questionId, runId, liveMeetingRoundId, lang } = props;
  const isZh = lang === "zh";
  const outputRunId = props.stateV2?.programDelivery?.outputRunId || "";
  const programDeliveryQuery = useQuery({
    queryKey: queryKeys.challengeQuestionRunDetail(teamId, questionId, outputRunId),
    queryFn: () => getChallengeQuestionRunDetail(teamId, questionId, outputRunId),
    enabled: Boolean(
      outputRunId
      && (props.stateV2?.currentPhase === "program_delivery" || props.stateV2?.currentPhase === "completed"),
    ),
    staleTime: 30_000,
  });
  if (props.formalRuntime) {
    return (
      <FormalRuntimeActionBody
        teamId={teamId}
        questionId={questionId}
        runId={runId}
        nextAction={nextAction}
        stateV2={props.stateV2}
        lang={lang}
        onFormalRunCreated={props.onFormalRunCreated}
      />
    );
  }
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
          runId={runId}
          label={nextAction.commandLabel || (isZh ? "生成候选假说" : "Generate candidate hypotheses")}
          lang={lang}
          canonicalAction={nextAction.canonicalAction}
          allowLegacyMutation={nextAction.stateSource !== "v2_canonical"}
        />
      );
    }
    if (nextAction.meetingRoundId || liveMeetingRoundId) {
      return (
        <HypothesisFirstMeetingOps
          teamId={teamId}
          questionId={questionId}
          runId={runId}
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
        runId={runId}
        label={nextAction.commandLabel || (isZh ? "生成候选假说" : "Generate candidate hypotheses")}
        lang={lang}
        canonicalAction={nextAction.canonicalAction}
        allowLegacyMutation={nextAction.stateSource !== "v2_canonical"}
      />
    );
  }
  if (nodeId === HYPOTHESIS_FIRST_SELECTION_NODE_ID) {
    return (
      <HypothesisSelectionList
        teamId={teamId}
        questionId={questionId}
        runId={runId}
        compact
        lang={lang}
        canonicalAction={nextAction.canonicalAction?.command === "record_selection"
          ? nextAction.canonicalAction
          : undefined}
        allowLegacyMutation={nextAction.stateSource !== "v2_canonical"}
      />
    );
  }
  if (nodeId === HYPOTHESIS_FIRST_REVIEW_NODE_ID || nodeId.startsWith("hf_meeting_")) {
    if (!liveMeetingRoundId && !nextAction.meetingRoundId) {
      return <p className={styles.description}>{isZh ? "尚未找到对应评审讨论。" : "The matching review discussion was not found."}</p>;
    }
    return (
      <HypothesisFirstMeetingOps
        teamId={teamId}
        questionId={questionId}
        runId={runId}
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
        runId={runId}
        stateV2={props.stateV2}
        onRetryCollection={props.onRetryCollection}
      />
    );
  }
  if (nodeId === HYPOTHESIS_FIRST_CONVERGENCE_NODE_ID) {
    const summary = props.stageSummary;
    const programDelivery = props.stateV2?.programDelivery;
    const canonicalActions = canonicalActionsFor(nextAction);
    // V2 is the gate authority; the raw V1 chain state is only consulted on
    // the route-unavailable fallback, never layered under an explicit V2 null.
    const rawClaimGate = props.stateV2
      ? props.stateV2.convergence?.claimBeliefGate
      : props.chainState?.claimBeliefGate;
    const claimGate = parseClaimBeliefGate(rawClaimGate);
    const gateBlockedDetail = claimGate?.status === "blocked"
      ? (isZh
        ? `收敛被 claim 证据门拦截（${claimGateReasonLabel(claimGate.reason, isZh)}）；请先补齐或修订 claim 证据，再考虑开启新一轮评审。`
        : `Convergence is blocked by the claim evidence gate (${claimGateReasonLabel(claimGate.reason, isZh)}); revise the claims or evidence before opening another round.`)
      : null;
    const humanAdjudication = canonicalActions.find(
      (action): action is Extract<CommandAction, { command: "human_adjudication" }> => action.command === "human_adjudication",
    );
    // Human adjudication needs its rationale/decision form. Keep all other
    // canonical actions visible alongside it, including a disabled
    // adjudication action when the server says why it is unavailable.
    const genericCanonicalActions = canonicalActions.filter(
      (action) => action.command !== "human_adjudication" || !humanAdjudication?.enabled,
    );
    if (props.stateV2?.currentPhase === "completed") {
      return (
        <div className={styles.task} data-testid="challenge-cup-workflow-completed">
          <VStateRow tone="success">
            {isZh ? "挑战杯研究流程已闭环" : "Challenge Cup research workflow completed"}
          </VStateRow>
          <p className={styles.status}>
            {isZh
              ? "正式研究结果已登记，H1–H4 四项审核全部通过。"
              : "The formal result is registered and all H1-H4 gates are approved."}
          </p>
        </div>
      );
    }
    if (props.stateV2?.currentPhase === "program_delivery") {
      if (programDelivery?.actionability === "blocked") {
        const deliveryProblems = programDelivery.problems;
        return (
          <div className={styles.task}>
            <VErrorSummary
              label={isZh ? "正式结果交付需要处理" : "Formal result delivery needs attention"}
              summary={deliveryProblems[0]?.message || nextAction.disabledReason || nextAction.statusMessage || (isZh ? "正式结果交付被阻塞" : "Formal result delivery is blocked")}
              details={deliveryProblems.length ? workflowProblemList(deliveryProblems) : undefined}
              defaultOpen={deliveryProblems.length > 1}
            />
            {canonicalActions.length ? (
              <CanonicalCommandActionList
                teamId={teamId}
                questionId={questionId}
                runId={runId}
                actions={canonicalActions}
                lang={lang}
                onFormalRunCreated={props.onFormalRunCreated}
              />
            ) : nextAction.canonicalAction ? (
              <CanonicalCommandButton
                teamId={teamId}
                questionId={questionId}
                runId={runId}
                action={nextAction.canonicalAction}
                lang={lang}
              />
            ) : null}
          </div>
        );
      }
      if (nextAction.canonicalAction?.command === "create_formal_revision") {
        return (
          <div className={styles.task}>
            <VStateRow tone="warning">
              {isZh ? "H1–H4 审核要求修订正式研究结果。" : "The H1-H4 review requested a formal research revision."}
            </VStateRow>
            <CanonicalCommandButton
              teamId={teamId}
              questionId={questionId}
              runId={runId}
              action={nextAction.canonicalAction}
              lang={lang}
            />
          </div>
        );
      }
      if (!outputRunId) {
        return (
          <VStateSurface
            tone="error"
            density="compact"
            title={isZh ? "缺少待审核结果标识" : "Review output identifier is missing"}
          >
            <p>{isZh ? "结果已进入交付阶段，但尚未绑定可审核的 outputRunId。" : "Delivery has started without a reviewable outputRunId."}</p>
          </VStateSurface>
        );
      }
      if (programDeliveryQuery.isLoading) {
        return <VStateSurface tone="loading" density="compact" title={isZh ? "读取正式结果审核信息" : "Loading formal result review"} />;
      }
      if (programDeliveryQuery.isError || !programDeliveryQuery.data) {
        return (
          <VStateSurface
            tone="error"
            density="compact"
            title={isZh ? "正式结果审核信息加载失败" : "Formal result review failed to load"}
          >
            <p>{programDeliveryQuery.error instanceof Error ? programDeliveryQuery.error.message : "challenge_question_run_detail_unavailable"}</p>
          </VStateSurface>
        );
      }
      return (
        <ChallengeQuestionReviewForm
          detail={programDeliveryQuery.data}
          lang={lang}
          canonicalAction={nextAction.canonicalAction?.command === "record_program_review"
            ? nextAction.canonicalAction
            : undefined}
          allowLegacyMutation={nextAction.stateSource !== "v2_canonical"}
        />
      );
    }
    return (
      <div className={styles.task}>
        {claimGate ? <ClaimBeliefGatePanel gate={claimGate} lang={lang} /> : null}
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
        {humanAdjudication?.enabled ? (
          <HumanAdjudicationAction
            teamId={teamId}
            questionId={questionId}
            runId={runId}
            action={humanAdjudication}
            lang={lang}
          />
        ) : null}
        {!humanAdjudication?.enabled && !genericCanonicalActions.length && nextAction.command === "human_adjudication" ? (
          <NextReviewRoundButton
            teamId={teamId}
            questionId={questionId}
            runId={runId}
            meetingRoundId={liveMeetingRoundId}
            nextRoundIndex={resolveHypothesisFirstNextReviewRoundIndex({
              stateV2: props.stateV2,
              chainState: props.chainState,
            })}
            roundBudget={resolveHypothesisFirstReviewRoundBudget({
              stateV2: props.stateV2,
              chainState: props.chainState,
            })}
            gateDetail={gateBlockedDetail}
            lang={lang}
          />
        ) : null}
        {genericCanonicalActions.length ? (
          <CanonicalCommandActionList
            teamId={teamId}
            questionId={questionId}
            runId={runId}
            actions={genericCanonicalActions}
            lang={lang}
            onFormalRunCreated={props.onFormalRunCreated}
          />
        ) : !humanAdjudication && nextAction.canonicalAction ? (
          <CanonicalCommandButton
            teamId={teamId}
            questionId={questionId}
            runId={runId}
            action={nextAction.canonicalAction}
            lang={lang}
            onFormalRunCreated={props.onFormalRunCreated}
          />
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

/**
 * V2 owns the complete command set. Legacy snapshots only carry the single
 * command selected for the old inspector, so retain that as a compatibility
 * fallback while never dropping server-authored disabled actions.
 */
function canonicalActionsFor(nextAction: HypothesisFirstNextAction): readonly CommandAction[] {
  const v2Action = nextAction as HypothesisFirstV2NextAction;
  if (Array.isArray(v2Action.canonicalActions) && v2Action.canonicalActions.length > 0) {
    return v2Action.canonicalActions;
  }
  return v2Action.canonicalAction ? [v2Action.canonicalAction] : [];
}

function workflowProblemList(problems: readonly WorkflowProblem[]) {
  return (
    <ul className={styles.bulletedList}>
      {problems.map((problem, index) => (
        <li key={`${problem.code}:${problem.sourceId || ""}:${index}`}>{problem.message}</li>
      ))}
    </ul>
  );
}

function CanonicalCommandActionList(props: {
  teamId: string;
  questionId: string;
  runId: string;
  actions: readonly CommandAction[];
  lang: Language;
  onFormalRunCreated?: HypothesisFirstNodeInspectorProps["onFormalRunCreated"];
}) {
  if (!props.actions.length) return null;
  const isZh = props.lang === "zh";
  return (
    <section className={styles.task} data-testid="canonical-command-action-list" aria-label={isZh ? "可用操作" : "Available actions"}>
      <VActionGroup ariaLabel={isZh ? "可用操作" : "Available actions"}>
        {props.actions.map((action) => (
          <CanonicalCommandButton
            key={action.actionId}
            teamId={props.teamId}
            questionId={props.questionId}
            runId={props.runId}
            action={action}
            lang={props.lang}
            onFormalRunCreated={props.onFormalRunCreated}
          />
        ))}
      </VActionGroup>
    </section>
  );
}

function formalRuntimeStatusLabel(status: string | null | undefined, lang: Language): string {
  const isZh = lang === "zh";
  switch (String(status || "").trim().toLowerCase()) {
    case "reconciliation_required": return isZh ? "状态待确认" : "Status needs reconciliation";
    case "failed": return isZh ? "正式运行失败" : "Formal run failed";
    case "cancelled": return isZh ? "正式运行已取消" : "Formal run cancelled";
    case "archived": return isZh ? "正式运行已归档" : "Formal run archived";
    case "succeeded": return isZh ? "正式运行已完成" : "Formal run succeeded";
    case "waiting_human": return isZh ? "等待人工处理" : "Waiting for human action";
    case "blocked": return isZh ? "正式运行被阻塞" : "Formal run blocked";
    case "queued": return isZh ? "正式运行排队中" : "Formal run queued";
    case "running": return isZh ? "正式运行中" : "Formal run running";
    default: return isZh ? "正式运行状态待确认" : "Formal run status needs review";
  }
}

function formalRuntimeStatusTone(status: string | null | undefined): "neutral" | "accent" | "success" | "warning" | "danger" {
  switch (String(status || "").trim().toLowerCase()) {
    case "succeeded": return "success";
    case "failed":
    case "cancelled":
    case "blocked": return "danger";
    case "reconciliation_required": return "warning";
    case "running":
    case "queued": return "accent";
    default: return "neutral";
  }
}

function FormalRuntimeActionBody(props: {
  teamId: string;
  questionId: string;
  runId: string;
  nextAction: HypothesisFirstV2NextAction;
  stateV2?: HypothesisFirstStateV2 | null;
  lang: Language;
  onFormalRunCreated?: HypothesisFirstNodeInspectorProps["onFormalRunCreated"];
}) {
  const isZh = props.lang === "zh";
  const runtime = props.stateV2?.formalRuntime;
  const status = runtime?.runStatus || (props.nextAction.stage === "blocked" ? "blocked" : null);
  const problems = (runtime?.problems ?? []).filter((problem, index, all) => all.findIndex((candidate) => (
    candidate.code === problem.code
    && candidate.sourceId === problem.sourceId
    && candidate.message === problem.message
  )) === index);
  const actions = canonicalActionsFor(props.nextAction);
  return (
    <div className={styles.task} data-testid="formal-runtime-action-body">
      <VStateRow tone={formalRuntimeStatusTone(status)}>
        {formalRuntimeStatusLabel(status, props.lang)}
      </VStateRow>
      {runtime?.runId ? <p className={styles.status}>{isZh ? `运行：${runtime.runId}` : `Run: ${runtime.runId}`}</p> : null}
      {problems.length ? (
        <VErrorSummary
          label={isZh ? "正式运行问题" : "Formal run problems"}
          summary={problems[0].message}
          details={problems.length ? workflowProblemList(problems) : undefined}
          defaultOpen={problems.length > 1}
        />
      ) : null}
      {actions.length ? (
        <CanonicalCommandActionList
          teamId={props.teamId}
          questionId={props.questionId}
          runId={props.runId}
          actions={actions}
          lang={props.lang}
          onFormalRunCreated={props.onFormalRunCreated}
        />
      ) : (
        <VStateRow tone="warning">
          {isZh ? "当前没有可执行的正式运行修复操作，请刷新状态。" : "No formal-run recovery action is available; refresh the state."}
        </VStateRow>
      )}
    </div>
  );
}

function ReviewHistory({
  meetings,
  allMeetings,
  lang,
}: {
  meetings: MeetingRoundRecord[];
  allMeetings: MeetingRoundRecord[];
  lang: Language;
}) {
  const isZh = lang === "zh";
  const retryCount = allMeetings.filter(isHypothesisReviewRetryAttempt).length;
  if (!meetings.length) {
    return (
      <VEmptyState title={isZh ? "尚无有效评审" : "No effective reviews yet"}>
        <p className={styles.description}>
          {isZh ? "失败 attempt 会计入重试统计，但不会占用新的画布节点。" : "Failed attempts count as retries without creating more canvas nodes."}
        </p>
      </VEmptyState>
    );
  }
  const rounds = groupReviewHistoryMeetings(meetings);
  const latestRound = rounds.at(-1)?.round ?? 0;
  return (
    <section className={styles.history} aria-label={isZh ? "假说评审历史" : "Hypothesis review history"}>
      <div className={styles.historySummary}>
        <strong>{isZh ? `${rounds.length} 轮有效评审` : `${rounds.length} effective reviews`}</strong>
        <VStatusChip tone="neutral">
          {isZh ? `${retryCount} 次失败重试` : `${retryCount} failed retries`}
        </VStatusChip>
      </div>
      <ol className={styles.historyList}>
        {rounds.map((item, index) => {
          const previousRound = index > 0 ? rounds[index - 1].round : 0;
          const retries = allMeetings.filter((candidate) => {
            const candidateRound = candidate.roundIndex ?? 0;
            return isHypothesisReviewRetryAttempt(candidate)
              && candidateRound > previousRound
              && candidateRound < item.round;
          }).length;
          const archived = item.meetings.filter(meetingHasDigestForHistory).length;
          const allClosed = item.meetings.every((meeting) => meeting.status === "closed");
          const hasOpen = item.meetings.some((meeting) => meeting.status === "open");
          const superseded = item.round < latestRound && !allClosed;
          const label = allClosed
            ? (isZh ? "已闭环" : "Closed")
            : superseded
              ? (isZh ? "已结束" : "Ended")
              : hasOpen
              ? (isZh ? "进行中" : "Active")
              : (isZh ? "待确认" : "Awaiting review");
          const tone = allClosed ? "success" : superseded ? "neutral" : hasOpen ? "accent" : "warning";
          const progressCopy = superseded
            ? (isZh ? "后续轮次已开始，本轮不再运行。" : "A later round has started; this round is no longer running.")
            : item.meetings.length > 1
            ? (isZh
              ? `本轮 ${item.meetings.length} 个候选评审，已归档 ${archived}/${item.meetings.length}。`
              : `${archived}/${item.meetings.length} candidate reviews archived in this round.`)
            : meetingHasDigestForHistory(item.meetings[0])
              ? (isZh ? "评审结论与纪要已归档。" : "Review conclusion and digest archived.")
              : (isZh ? "评审仍在进行或等待纪要。" : "Review is active or awaiting its digest.");
          return (
            <li className={styles.historyItem} key={item.key}>
              <div className={styles.historyTopline}>
                <strong>{isZh ? `第 ${item.round} 轮` : `Round ${item.round}`}</strong>
                <VStatusChip tone={tone}>{label}</VStatusChip>
              </div>
              <p className={styles.historyCopy}>{progressCopy}</p>
              {retries > 0 ? (
                <span className={styles.historyRetry}>
                  {isZh ? `包含 ${retries} 次失败重试` : `Includes ${retries} failed retries`}
                </span>
              ) : null}
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function groupReviewHistoryMeetings(meetings: readonly MeetingRoundRecord[]): Array<{
  key: string;
  round: number;
  meetings: MeetingRoundRecord[];
}> {
  const grouped = new Map<string, { key: string; round: number; meetings: MeetingRoundRecord[] }>();
  meetings.forEach((meeting, index) => {
    const hasRoundIndex = typeof meeting.roundIndex === "number";
    const round = hasRoundIndex ? Number(meeting.roundIndex) : index + 1;
    const key = hasRoundIndex ? `round:${round}` : `legacy:${meeting.meetingRoundId}`;
    const existing = grouped.get(key);
    if (existing) {
      existing.meetings.push(meeting);
    } else {
      grouped.set(key, { key, round, meetings: [meeting] });
    }
  });
  return [...grouped.values()].sort((left, right) => left.round - right.round);
}

function meetingHasDigestForHistory(meeting: MeetingRoundRecord): boolean {
  return Boolean(meeting.digestId || meeting.digestRef);
}

function errorRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

type CommandRejectionKind =
  | "not_ready"
  | "not_allowed"
  | "version_conflict"
  | "forbidden"
  | "generic";

type CommandRejection = {
  kind: CommandRejectionKind;
  message: string;
  blockers: readonly unknown[];
};

const REJECTION_KIND_BY_CODE: Readonly<Record<string, Exclude<CommandRejectionKind, "generic">>> = {
  node_not_ready: "not_ready",
  command_not_allowed: "not_allowed",
  run_version_conflict: "version_conflict",
  command_forbidden: "forbidden",
};

function commandRejection(error: unknown): CommandRejection {
  const payload = isFetchJsonHttpError(error) ? errorRecord(error.details) : null;
  const detail = errorRecord(payload?.detail) ?? payload;
  const blockers = Array.isArray(detail?.blockers) ? detail.blockers : [];
  const code = String(
    detail?.code || (isFetchJsonHttpError(error) ? error.code : "") || "",
  ).trim();
  // Server-authored rejection copy is Chinese already; fall back to the wire
  // message only so infrastructure failures still surface something.
  const message = String(detail?.message || (isFetchJsonHttpError(error) ? error.message : "") || "").trim();
  if (!isFetchJsonHttpError(error)) {
    return { kind: "generic", message, blockers };
  }
  // 412 is reserved for the readiness-blocker contract; every other
  // rejection needs an explicit server code before claiming a reason.
  const kind = REJECTION_KIND_BY_CODE[code]
    ?? (error.status === 412 ? "not_ready" as const : "generic" as const);
  return { kind, message, blockers };
}

function commandRejectionLabel(kind: CommandRejectionKind, lang: Language): string {
  if (lang === "en") {
    switch (kind) {
      case "not_ready": return "Node is not ready";
      case "not_allowed": return "The workflow state does not allow this action";
      case "version_conflict": return "The formal run moved on; refresh and retry";
      case "forbidden": return "You are not allowed to perform this action";
      default: return "Action could not finish";
    }
  }
  switch (kind) {
    case "not_ready": return "节点尚未就绪";
    case "not_allowed": return "当前状态不允许该操作";
    case "version_conflict": return "正式运行状态已变化，请刷新后重试";
    case "forbidden": return "当前身份无权执行该操作";
    default: return "操作未完成";
  }
}

function readinessBlockerLabel(blocker: unknown): string {
  if (typeof blocker === "string") return blocker;
  const value = errorRecord(blocker);
  if (!value) return String(blocker ?? "");
  const title = String(value.title || value.label || value.code || "").trim();
  const detail = String(value.detail || value.message || "").trim();
  return title && detail && title !== detail ? `${title}：${detail}` : title || detail;
}

function CanonicalCommandButton(props: {
  teamId: string;
  questionId: string;
  runId: string;
  action: CommandAction;
  lang: Language;
  onFormalRunCreated?: HypothesisFirstNodeInspectorProps["onFormalRunCreated"];
}) {
  const queryClient = useQueryClient();
  const [confirmationOpen, setConfirmationOpen] = useState(false);
  const mutation = useMutation<unknown, Error, void>({
    mutationFn: () => executeHypothesisFirstCommand(
      props.teamId,
      props.questionId,
      props.action,
      undefined,
      { runId: props.runId },
    ),
    onSuccess: (response) => {
      setConfirmationOpen(false);
      invalidateHypothesisFirstQueries(queryClient, props.teamId, props.questionId, props.runId);
      if (props.action.command !== "create_formal_run" || !props.onFormalRunCreated) {
        return;
      }
      const result = typeof response === "object" && response !== null && "result" in response
        ? (response as { result?: unknown }).result
        : null;
      const created = typeof result === "object" && result !== null
        ? result as Record<string, unknown>
        : null;
      const runId = typeof created?.runId === "string" ? created.runId : "";
      if (runId) {
        props.onFormalRunCreated({
          runId,
          nodeId: typeof created?.activeNodeId === "string" && created.activeNodeId
            ? created.activeNodeId
            : "source_finding",
          questionId: props.questionId,
        });
      }
    },
    onError: (error) => {
      if (isHypothesisFirstCommandStateConflict(error)) {
        setConfirmationOpen(false);
        invalidateHypothesisFirstQueries(queryClient, props.teamId, props.questionId, props.runId);
      }
    },
  });
  return (
    <div className={styles.task} data-testid={`canonical-command-${props.action.command}`}>
      {mutation.isError ? (() => {
        const isStateConflict = isHypothesisFirstCommandStateConflict(mutation.error);
        const rejection = commandRejection(mutation.error);
        return (
          <VErrorSummary
            label={isStateConflict
              ? (props.lang === "zh" ? "状态已更新" : "Workflow state changed")
              : commandRejectionLabel(rejection.kind, props.lang)}
            summary={isStateConflict
              ? (props.lang === "zh" ? "状态已更新，请重新确认。" : "The workflow state changed. Review it and confirm again.")
              : rejection.message || (props.lang === "zh" ? "命令未能执行，请稍后重试。" : "The command was not executed. Try again later.")}
            details={rejection.blockers.length ? (
              <ul className={styles.bulletedList} data-testid="canonical-command-readiness-blockers">
                {rejection.blockers.map((blocker, index) => (
                  <li key={`${readinessBlockerLabel(blocker)}:${index}`}>{readinessBlockerLabel(blocker)}</li>
                ))}
              </ul>
            ) : undefined}
            defaultOpen={Boolean(rejection.blockers.length)}
          />
        );
      })() : null}
      {!props.action.enabled && props.action.disabledReason ? (
        <span className={styles.commandDetail} role="status">{props.action.disabledReason}</span>
      ) : null}
      <VButton
        type="button"
        variant="primary"
        density="compact"
        isPending={mutation.isPending}
        isDisabled={!props.action.enabled}
        disabledReason={props.action.disabledReason || undefined}
        onPress={() => {
          if (!props.action.enabled || mutation.isPending) return;
          if (props.action.requiresConfirmation) {
            setConfirmationOpen(true);
            return;
          }
          mutation.mutate();
        }}
      >
        {props.action.label}
      </VButton>
      {props.action.requiresConfirmation ? (
        <VConfirmDialog
          open={confirmationOpen}
          onOpenChange={(open) => {
            if (!open && mutation.isPending) return;
            setConfirmationOpen(open);
          }}
          title={props.action.label}
          description={props.action.confirmationText || canonicalCommandConfirmationText(props.action.command, props.lang)}
          tone={["stop_discussion", "archive_run"].includes(props.action.command) ? "danger" : "neutral"}
          confirmLabel={props.lang === "zh" ? "确认执行" : "Confirm action"}
          cancelLabel={props.lang === "zh" ? "取消" : "Cancel"}
          confirmPending={mutation.isPending}
          confirmDisabled={!props.action.enabled}
          onConfirm={() => {
            if (!props.action.enabled || mutation.isPending) return;
            mutation.mutate();
          }}
        />
      ) : null}
    </div>
  );
}

function canonicalCommandConfirmationText(command: CommandAction["command"], lang: Language): string {
  if (lang === "en") {
    switch (command) {
      case "stop_discussion": return "This closes the current discussion. You may need to review the resulting state before continuing.";
      case "archive_run": return "This archives the terminal formal run so a replacement run can be created.";
      case "reconcile_formal_run": return "This will reconcile the formal run against the durable workflow state.";
      case "create_formal_revision": return "This will create a new formal revision from the current delivery result.";
      default: return "Review the current workflow state before executing this action.";
    }
  }
  switch (command) {
    case "stop_discussion": return "这会关闭当前讨论，继续流程前可能需要重新确认结果。";
    case "archive_run": return "这会归档当前终态正式运行，随后可重新创建正式运行。";
    case "reconcile_formal_run": return "这会根据持久化工作流状态核对正式运行。";
    case "create_formal_revision": return "这会基于当前交付结果创建新的正式修订。";
    default: return "请先确认当前工作流状态，再执行此操作。";
  }
}

function HumanAdjudicationAction(props: {
  teamId: string;
  questionId: string;
  runId: string;
  action: Extract<CommandAction, { command: "human_adjudication" }>;
  lang: Language;
}) {
  const queryClient = useQueryClient();
  const [rationale, setRationale] = useState("");
  const mutation = useMutation<unknown, Error, "accepted" | "rejected">({
    mutationFn: (decision) => executeHypothesisFirstCommand(
      props.teamId,
      props.questionId,
      props.action,
      { decision, rationale: rationale.trim() },
      { runId: props.runId },
    ),
    onSuccess: () => invalidateHypothesisFirstQueries(
      queryClient,
      props.teamId,
      props.questionId,
      props.runId,
    ),
    onError: (error) => {
      if (isHypothesisFirstCommandStateConflict(error)) {
        invalidateHypothesisFirstQueries(queryClient, props.teamId, props.questionId, props.runId);
      }
    },
  });
  const isZh = props.lang === "zh";
  return (
    <div className={styles.task} data-testid="human-adjudication-action">
      <VInput
        aria-label={isZh ? "人工裁决理由" : "Adjudication rationale"}
        value={rationale}
        onChange={(event) => setRationale(event.currentTarget.value)}
        placeholder={isZh ? "说明接受或拒绝当前收敛结果的理由" : "Explain why this convergence result is accepted or rejected"}
        isDisabled={mutation.isPending}
      />
      {mutation.isError ? (
        <VErrorSummary
          label={isZh ? "人工裁决未提交" : "Adjudication was not submitted"}
          summary={isHypothesisFirstCommandStateConflict(mutation.error)
            ? (isZh ? "状态已更新，请重新确认。" : "The workflow state changed. Review it and confirm again.")
            : mutation.error.message}
        />
      ) : null}
      <div className={styles.secondary}>
        <VButton
          type="button"
          variant="primary"
          density="compact"
          isPending={mutation.isPending}
          isDisabled={!rationale.trim()}
          disabledReason={!rationale.trim() ? (isZh ? "请先填写裁决理由" : "Enter a rationale first") : undefined}
          onPress={() => mutation.mutate("accepted")}
        >
          {isZh ? "接受当前收敛结果" : "Accept convergence"}
        </VButton>
        <VButton
          type="button"
          variant="ghost"
          density="compact"
          isPending={mutation.isPending}
          isDisabled={!rationale.trim()}
          onPress={() => mutation.mutate("rejected")}
        >
          {isZh ? "拒绝当前收敛结果" : "Reject convergence"}
        </VButton>
      </div>
    </div>
  );
}

function NextReviewRoundButton(props: {
  teamId: string;
  questionId: string;
  runId: string;
  meetingRoundId: string;
  nextRoundIndex: number | null;
  /** Server-resolved review-round budget; the copy reads "round N of M". */
  roundBudget: number;
  /** Claim-gate guidance replaces the generic "not converged" detail when the
   * server gate blocked convergence; the button authority itself is untouched. */
  gateDetail?: string | null;
  lang: Language;
}) {
  const queryClient = useQueryClient();
  const [blockedReason, setBlockedReason] = useState<string | null>(null);
  const copy = reviewRoundActionCopy(props.nextRoundIndex, props.lang, props.roundBudget);
  const mutation = useMutation({
    mutationFn: () =>
      openNextHypothesisReviewRound(props.teamId, props.meetingRoundId),
    onSuccess: (payload) => {
      setBlockedReason(
        payload?.status === "budget_exhausted"
          ? (props.lang === "zh" ? `已达到评审上限 ${props.roundBudget}，假说仍未收敛。` : `The review limit of ${props.roundBudget} was reached without convergence.`)
          : null,
      );
      invalidateHypothesisFirstQueries(queryClient, props.teamId, props.questionId, props.runId);
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
      <p className={styles.status} data-testid="next-review-round-budget">
        {props.gateDetail || copy.detail}
      </p>
      <VButton
        type="button"
        variant="primary"
        density="compact"
        isPending={mutation.isPending}
        isDisabled={!props.meetingRoundId}
        disabledReason={props.meetingRoundId ? undefined : (props.lang === "zh" ? "缺少上一轮评审标识" : "The previous review round ID is missing")}
        onPress={() => mutation.mutate()}
      >
        {copy.label}
      </VButton>
    </div>
  );
}

function OpenGenerationButton(props: {
  teamId: string;
  questionId: string;
  runId: string;
  label: string;
  lang: Language;
  canonicalAction?: HypothesisFirstNextAction["canonicalAction"];
  allowLegacyMutation: boolean;
}) {
  const queryClient = useQueryClient();
  const mutation = useMutation<unknown, Error, void>({
    mutationFn: () => {
      if (props.canonicalAction
        && (props.canonicalAction.command === "open_generation" || props.canonicalAction.command === "retry_generation")) {
        return executeHypothesisFirstCommand(
          props.teamId,
          props.questionId,
          props.canonicalAction,
          undefined,
          { runId: props.runId },
        );
      }
      if (props.allowLegacyMutation) {
        return openHypothesisCandidateGeneration(props.teamId, props.questionId, props.runId);
      }
      return Promise.reject(new Error("canonical_action_unavailable"));
    },
    onSuccess: () => invalidateHypothesisFirstQueries(
      queryClient,
      props.teamId,
      props.questionId,
      props.runId,
    ),
    onError: (error) => {
      if (isHypothesisFirstCommandStateConflict(error)) {
        invalidateHypothesisFirstQueries(queryClient, props.teamId, props.questionId, props.runId);
      }
    },
  });
  return (
    <div className={styles.task}>
      {mutation.isError ? (
        <VErrorSummary
          label={props.lang === "zh" ? "候选生成失败" : "Candidate generation failed"}
          summary={isHypothesisFirstCommandStateConflict(mutation.error)
            ? (props.lang === "zh" ? "状态已更新，请重新确认。" : "The workflow state changed. Review it and confirm again.")
            : mutation.error instanceof Error ? mutation.error.message : "open_candidate_generation_failed"}
        />
      ) : null}
      <VButton
        type="button"
        variant="primary"
        density="compact"
        isPending={mutation.isPending}
        isDisabled={!props.allowLegacyMutation && !props.canonicalAction}
        disabledReason={!props.allowLegacyMutation && !props.canonicalAction
          ? (props.lang === "zh" ? "当前状态没有可执行的已签名操作，请刷新状态" : "No signed action is available for the current state; refresh it")
          : undefined}
        onPress={() => mutation.mutate()}
      >
        {props.label}
      </VButton>
    </div>
  );
}

function collectionSourceChip(
  lifecycle: string,
  error: WorkflowProblem | null,
  lang: Language,
): { label: string; tone: "neutral" | "accent" | "success" | "warning" | "danger" } {
  const isZh = lang === "zh";
  if (error || lifecycle === "failed") return { label: isZh ? "失败" : "Failed", tone: "danger" };
  switch (lifecycle) {
    case "completed": return { label: isZh ? "已完成" : "Completed", tone: "success" };
    case "running": return { label: isZh ? "搜集中" : "Collecting", tone: "accent" };
    case "queued": return { label: isZh ? "排队中" : "Queued", tone: "neutral" };
    case "waiting_human": return { label: isZh ? "待人工处理" : "Waiting for human", tone: "warning" };
    case "cancelled":
    case "superseded": return { label: isZh ? "已取消" : "Cancelled", tone: "neutral" };
    default: return { label: isZh ? "等待开始" : "Pending", tone: "neutral" };
  }
}

/** 长时间资料搜集的逐源可见性：sources 为空时整体降级隐藏，不留占位噪音。 */
function CollectionSourceProgress({ sources, lang }: {
  sources: HypothesisFirstStateV2["collection"]["requests"][number]["sources"];
  lang: Language;
}) {
  if (!sources.length) return null;
  const isZh = lang === "zh";
  const completed = sources.filter((source) => !source.error && source.lifecycle === "completed").length;
  const totalItems = sources.reduce((sum, source) => sum + (Number(source.itemCount) || 0), 0);
  return (
    <section
      className={styles.candidateChecklist}
      data-testid="collection-source-progress"
      aria-label={isZh ? "逐源搜集进度" : "Per-source collection progress"}
    >
      <div className={styles.candidateChecklistSummary}>
        <strong>{isZh ? "逐源搜集进度" : "Per-source collection"}</strong>
        <span>{isZh
          ? `已完成 ${completed}/${sources.length} 源 · 已获 ${totalItems} 条资料`
          : `${completed}/${sources.length} sources done · ${totalItems} items`}
        </span>
      </div>
      <ul className={styles.candidateChecklistList}>
        {sources.map((source, index) => {
          const chip = collectionSourceChip(source.lifecycle, source.error, lang);
          return (
            <li className={styles.candidateChecklistItem} key={String(source.sourceId || index)}>
              <div className={styles.candidateChecklistIdentity}>
                <strong>{source.label || String(source.sourceId || index)}</strong>
                <span>{isZh ? `${Number(source.itemCount) || 0} 条` : `${Number(source.itemCount) || 0} items`}</span>
              </div>
              <VStatusChip tone={chip.tone}>{chip.label}</VStatusChip>
            </li>
          );
        })}
      </ul>
      {sources.some((source) => source.error) ? (
        <ul className={styles.bulletedList}>
          {sources.filter((source) => source.error).map((source, index) => (
            <li key={`${source.sourceId}:${index}`} className={styles.sourceError}>{source.error?.message}</li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

function CollectionTaskBody(props: {
  nextAction: HypothesisFirstNextAction;
  lang: Language;
  teamId: string;
  questionId: string;
  runId: string;
  stateV2?: HypothesisFirstStateV2 | null;
  onRetryCollection?: () => Promise<void>;
}) {
  const queryClient = useQueryClient();
  const isZh = props.lang === "zh";
  const requestId = props.nextAction.collectionRequestId || "";
  const collectionRunId = props.nextAction.collectionRunId || "";
  // 与 V2 adapter 的 active-request 规则一致：先取未完成请求，回退首个请求。
  const activeRequest = props.stateV2?.collection.requests.find(
    (request) => request.lifecycle !== "completed",
  ) ?? props.stateV2?.collection.requests[0] ?? null;
  const canHandoff = props.nextAction.command === "retry_handoff"
    && Boolean(requestId)
    && Boolean(collectionRunId);
  const handoff = useMutation<unknown, Error, void>({
    mutationFn: () => {
      if (props.nextAction.canonicalAction?.command === "handoff_collection") {
        return executeHypothesisFirstCommand(
          props.teamId,
          props.questionId,
          props.nextAction.canonicalAction,
          undefined,
          { runId: props.runId },
        );
      }
      if (props.nextAction.stateSource !== "v2_canonical") {
        return recordCollectionHandoff(props.teamId, requestId, {
          handoffRef: `source_collection_run:${collectionRunId}`,
        });
      }
      return Promise.reject(new Error("canonical_action_unavailable"));
    },
    onSuccess: () => invalidateHypothesisFirstQueries(
      queryClient,
      props.teamId,
      props.questionId,
      props.runId,
    ),
    onError: (error) => {
      if (isHypothesisFirstCommandStateConflict(error)) {
        invalidateHypothesisFirstQueries(queryClient, props.teamId, props.questionId, props.runId);
      }
    },
  });
  return (
    <div className={styles.task}>
      <div role="status">
        <VStateRow tone={props.nextAction.stage === "collecting" ? "accent" : "warning"}>
          {props.nextAction.statusMessage || props.nextAction.recovery?.reason || (isZh ? "资料搜集" : "Evidence collection")}
        </VStateRow>
      </div>
      {activeRequest ? (
        <CollectionSourceProgress sources={activeRequest.sources} lang={props.lang} />
      ) : null}
      {handoff.isError ? (
        <VErrorSummary
          label={isZh ? "交接失败" : "Handoff failed"}
          summary={isHypothesisFirstCommandStateConflict(handoff.error)
            ? (isZh ? "状态已更新，请重新确认。" : "The workflow state changed. Review it and confirm again.")
            : handoff.error instanceof Error ? handoff.error.message : "handoff_failed"}
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
