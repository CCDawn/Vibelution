import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  fetchHypothesisSelectionContext,
  openHypothesisCandidateGeneration,
} from "../../../api/hypothesisFirst";
import { queryKeys } from "../../../api/queryKeys";
import {
  VButton,
  VEmptyState,
  VErrorSummary,
  VStateSurface,
  VStatusChip,
} from "../../../components/vui";
import { invalidateHypothesisFirstQueries } from "../research-workflow/useHypothesisFirstChain";
import {
  HypothesisSelectionList,
  HYPOTHESIS_SELECTION_MAX,
  HYPOTHESIS_SELECTION_MIN,
} from "./HypothesisSelectionList";
import css from "./HypothesisSelectionPanel.styles";

export { HYPOTHESIS_SELECTION_MAX, HYPOTHESIS_SELECTION_MIN };

export type HypothesisSelectionPanelProps = {
  teamId: string;
  questionId: string;
  lang?: "zh" | "en";
  /** Opens the selected review round where its live workflow actions are available. */
  onOpenReviewMeeting?: (nodeId: string) => void;
};

function meetingStatusTone(status: string): "accent" | "warning" | "neutral" | "success" {
  if (status === "closed") return "success";
  if (status === "awaiting_approval") return "warning";
  if (status === "open" || status === "summarizing") return "accent";
  return "neutral";
}

const MEETING_STATUS_LABELS: Record<string, string> = {
  open: "讨论中",
  summarizing: "正在整理讨论结论",
  awaiting_approval: "待人工确认",
  closed: "已关门",
};

const MEETING_STATUS_LABELS_EN: Record<string, string> = {
  open: "Discussing",
  summarizing: "Summarizing",
  awaiting_approval: "Awaiting approval",
  closed: "Closed",
};

export function HypothesisSelectionPanel({
  teamId,
  questionId,
  lang = "zh",
  onOpenReviewMeeting,
}: HypothesisSelectionPanelProps) {
  const isZh = lang === "zh";
  const queryClient = useQueryClient();
  const contextQuery = useQuery({
    queryKey: queryKeys.hypothesisFirstSelectionContext(teamId, questionId),
    queryFn: () => fetchHypothesisSelectionContext(teamId, questionId),
    enabled: Boolean(teamId && questionId),
    staleTime: 15_000,
  });
  const context = contextQuery.data;
  const generationMutation = useMutation({
    mutationFn: () => openHypothesisCandidateGeneration(teamId, questionId),
    onSuccess: () => {
      invalidateHypothesisFirstQueries(queryClient, teamId, questionId);
    },
  });

  if (contextQuery.isPending) {
    return (
      <section className={css.section} id="hypothesis-first-selection">
        <VStateSurface title={isZh ? "正在读取假说选择上下文" : "Loading hypothesis selection context"} tone="loading" />
      </section>
    );
  }
  if (contextQuery.isError || !context) {
    return (
      <VEmptyState title={isZh ? "假说选择上下文不可用" : "Hypothesis selection context unavailable"}>
        {contextQuery.error instanceof Error ? <code>{contextQuery.error.message}</code> : null}
      </VEmptyState>
    );
  }

  const candidates = context.candidates;
  const selectedCount = (
    context.latestSelection?.selectedCandidateIds ??
    context.defaultSelectedCandidateIds ??
    []
  ).length;
  const reviewMeeting = context.reviewMeeting ?? null;
  const reviewMeetingNodeId = reviewMeeting?.meetingRoundId
    && Number.isInteger(reviewMeeting.roundIndex)
    && (reviewMeeting.roundIndex ?? 0) > 0
    ? `hf_meeting_${reviewMeeting.roundIndex}`
    : "";
  const canOpenReviewMeeting = Boolean(reviewMeetingNodeId && onOpenReviewMeeting);
  const reviewMeetingDisabledReason = !reviewMeeting?.meetingRoundId
    ? (isZh ? "记录选择并开启评审讨论后可用" : "Available after recording a selection and starting the review")
    : !reviewMeetingNodeId
      ? (isZh ? "评审讨论正在建立可操作节点，请稍后重试" : "The review is still preparing its actionable workflow node")
      : !onOpenReviewMeeting
        ? (isZh ? "请从研究流程中打开评审讨论" : "Open the review discussion from the research workflow")
        : undefined;
  const generationMeeting = context.generationMeeting ?? null;
  const generationOpen = Boolean(
    generationMeeting && generationMeeting.status !== "closed",
  );

  return (
    <section className={css.section} id="hypothesis-first-selection">
      <div className={css.heading}>
        <div>
          <h3>{isZh ? "假说选择（假说先行）" : "Hypothesis selection (hypothesis-first)"}</h3>
          <p>
            {isZh
              ? reviewMeeting?.status === "closed"
                ? `候选总数 ${candidates.length} 条 · 最终采用 ${selectedCount} 条`
                : `候选总数 ${candidates.length} 条 · 需选择 ${HYPOTHESIS_SELECTION_MIN}–${HYPOTHESIS_SELECTION_MAX} 条`
              : reviewMeeting?.status === "closed"
                ? `${candidates.length} candidates · ${selectedCount} selected`
                : `${candidates.length} candidates · select ${HYPOTHESIS_SELECTION_MIN}–${HYPOTHESIS_SELECTION_MAX}`}
          </p>
        </div>
        <div className={css.headingActions}>
          {reviewMeeting ? (
            <VStatusChip tone={meetingStatusTone(reviewMeeting.status)}>
              {(isZh ? MEETING_STATUS_LABELS : MEETING_STATUS_LABELS_EN)[reviewMeeting.status] ?? reviewMeeting.status}
            </VStatusChip>
          ) : (
            <VStatusChip tone="neutral">{isZh ? "未开启评审" : "Review not started"}</VStatusChip>
          )}
        </div>
      </div>

      {candidates.length === 0 ? (
        <VEmptyState
          title={
            generationOpen
              ? (isZh ? "候选假说生成讨论进行中" : "Candidate generation discussion in progress")
              : (isZh ? "尚无候选假说" : "No candidate hypotheses yet")
          }
        >
          <div className={css.generationState}>
            {generationMeeting ? (
              <VStatusChip tone={meetingStatusTone(generationMeeting.status)}>
                {(isZh ? MEETING_STATUS_LABELS : MEETING_STATUS_LABELS_EN)[generationMeeting.status]
                  ?? generationMeeting.status}
              </VStatusChip>
            ) : null}
            <p>
              {generationOpen
                ? (isZh
                  ? "团队正在讨论并生成候选假说，闭环后此处会出现可选择列表。"
                  : "The team is discussing candidate hypotheses; the selectable list appears after closure.")
                : (isZh
                  ? "该题目还没有候选假说。先让团队开启一轮候选生成讨论，闭环产出候选后再人工选择。"
                  : "No candidates yet. Start a candidate-generation discussion first, then select after closure.")}
            </p>
            {!generationOpen ? (
              <VButton
                density="compact"
                isPending={generationMutation.isPending}
                onPress={() => generationMutation.mutate()}
                variant="primary"
              >
                {generationMeeting
                  ? (isZh ? "重新生成候选假说" : "Regenerate candidates")
                  : (isZh ? "生成候选假说" : "Generate candidates")}
              </VButton>
            ) : null}
            {generationMutation.isError ? (
              <VErrorSummary
                label={isZh ? "候选生成失败" : "Candidate generation failed"}
                summary={
                  generationMutation.error instanceof Error
                    ? generationMutation.error.message
                    : "open_candidate_generation_failed"
                }
              />
            ) : null}
          </div>
        </VEmptyState>
      ) : (
        <HypothesisSelectionList teamId={teamId} questionId={questionId} lang={lang} />
      )}

      <div className={css.actions}>
        <VButton
          density="compact"
          disabledReason={reviewMeetingDisabledReason}
          isDisabled={!canOpenReviewMeeting}
          onPress={() => onOpenReviewMeeting?.(reviewMeetingNodeId)}
          variant="secondary"
        >
          {isZh ? "查看评审讨论" : "View review discussion"}
        </VButton>
      </div>
    </section>
  );
}
