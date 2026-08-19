import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  fetchHypothesisSelectionContext,
  openHypothesisCandidateGeneration,
  recordHypothesisSelection,
} from "../../../api/hypothesisFirst";
import { queryKeys } from "../../../api/queryKeys";
import type {
  HypothesisSelectionContext,
  HypothesisSelectionRecordPayload,
} from "../../../api/types";
import {
  VButton,
  VCheckbox,
  VEmptyState,
  VErrorSummary,
  VStateSurface,
  VStatusChip,
} from "../../../components/vui";
import css from "./HypothesisSelectionPanel.styles";

export const HYPOTHESIS_SELECTION_MIN = 1;
export const HYPOTHESIS_SELECTION_MAX = 16;

export type HypothesisSelectionPanelProps = {
  teamId: string;
  questionId: string;
  lang?: "zh" | "en";
};

function sameIdSet(left: string[], right: string[]): boolean {
  if (left.length !== right.length) return false;
  const rightSet = new Set(right);
  return left.every((id) => rightSet.has(id));
}

function meetingStatusTone(status: string): "accent" | "warning" | "neutral" | "success" {
  if (status === "closed") return "success";
  if (status === "awaiting_approval") return "warning";
  if (status === "open" || status === "summarizing") return "accent";
  return "neutral";
}

const MEETING_STATUS_LABELS: Record<string, string> = {
  open: "讨论中",
  summarizing: "纪要生成中",
  awaiting_approval: "待人工确认",
  closed: "已关门",
};

const MEETING_STATUS_LABELS_EN: Record<string, string> = {
  open: "Discussing",
  summarizing: "Summarizing",
  awaiting_approval: "Awaiting approval",
  closed: "Closed",
};

export function HypothesisSelectionPanel({ teamId, questionId, lang = "zh" }: HypothesisSelectionPanelProps) {
  const isZh = lang === "zh";
  const queryClient = useQueryClient();
  const contextQuery = useQuery({
    queryKey: queryKeys.hypothesisFirstSelectionContext(teamId, questionId),
    queryFn: () => fetchHypothesisSelectionContext(teamId, questionId),
    enabled: Boolean(teamId && questionId),
    staleTime: 15_000,
  });
  const context: HypothesisSelectionContext | undefined = contextQuery.data;

  const serverBaseline = useMemo(
    () =>
      context?.latestSelection?.selectedCandidateIds ??
      context?.defaultSelectedCandidateIds ??
      [],
    [context],
  );
  const [selectedIds, setSelectedIds] = useState<string[]>(serverBaseline);
  useEffect(() => {
    setSelectedIds(serverBaseline);
  }, [serverBaseline]);

  const recordMutation = useMutation({
    mutationFn: (input: HypothesisSelectionRecordPayload) =>
      recordHypothesisSelection(teamId, input),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.hypothesisFirstSelectionContext(teamId, questionId),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.hypothesisFirstSelections(teamId),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.hypothesisFirstChainState(teamId, questionId),
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamMeetingRounds(teamId) });
    },
  });

  const generationMutation = useMutation({
    mutationFn: () => openHypothesisCandidateGeneration(teamId, questionId),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.hypothesisFirstSelectionContext(teamId, questionId),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.hypothesisFirstChainState(teamId, questionId),
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamMeetingRounds(teamId) });
    },
  });

  if (contextQuery.isPending) {
    return <VStateSurface title={isZh ? "正在读取假说选择上下文" : "Loading hypothesis selection context"} tone="loading" />;
  }
  if (contextQuery.isError || !context) {
    return (
      <VEmptyState title={isZh ? "假说选择上下文不可用" : "Hypothesis selection context unavailable"}>
        {contextQuery.error instanceof Error ? <code>{contextQuery.error.message}</code> : null}
      </VEmptyState>
    );
  }

  const candidates = context.candidates;
  const latestSelection = context.latestSelection;
  const reviewMeeting = context.reviewMeeting ?? null;
  const reviewMeetingId = reviewMeeting?.meetingRoundId ?? "";
  const generationMeeting = context.generationMeeting ?? null;
  const generationOpen = Boolean(
    generationMeeting && generationMeeting.status !== "closed",
  );
  const dirty = !sameIdSet(selectedIds, serverBaseline);
  const withinBounds =
    selectedIds.length >= HYPOTHESIS_SELECTION_MIN &&
    selectedIds.length <= HYPOTHESIS_SELECTION_MAX;

  const toggleCandidate = (candidateId: string, next: boolean) => {
    setSelectedIds((current) => {
      if (next) {
        if (current.includes(candidateId) || current.length >= HYPOTHESIS_SELECTION_MAX) {
          return current;
        }
        return [...current, candidateId];
      }
      if (current.length <= HYPOTHESIS_SELECTION_MIN) return current;
      return current.filter((id) => id !== candidateId);
    });
  };

  const submitSelection = () => {
    recordMutation.mutate({
      ...context.scope,
      mode: context.mode,
      questionId,
      selectedCandidateIds: selectedIds,
      decidedBy: "operator",
      previousSelectionId: latestSelection?.selectionId ?? "",
    });
  };

  const openMeetingSection = () => {
    document
      .getElementById("hypothesis-first-meeting")
      ?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  return (
    <section className={css.section} id="hypothesis-first-selection">
      <div className={css.heading}>
        <div>
          <h3>{isZh ? "假说选择（假说先行）" : "Hypothesis selection (hypothesis-first)"}</h3>
          <p>
            {isZh
              ? `已选 ${selectedIds.length} / ${candidates.length} 条候选（${HYPOTHESIS_SELECTION_MIN}–${HYPOTHESIS_SELECTION_MAX}）`
              : `Selected ${selectedIds.length} / ${candidates.length} candidates (${HYPOTHESIS_SELECTION_MIN}–${HYPOTHESIS_SELECTION_MAX})`}
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

      {latestSelection ? (
        <div className={css.summary}>
          <span>{isZh ? "当前生效选择" : "Current effective selection"}</span>
          <p>
            {latestSelection.selectionId} · {latestSelection.selectedCandidateIds.join("、")} ·{" "}
            {latestSelection.decidedBy || "unknown"} · {latestSelection.createdAt || "—"}
          </p>
        </div>
      ) : (
        <p className={css.hint}>{isZh ? "尚未记录选择，默认勾选赛题 artifact 的已选假说集合。" : "No selection recorded yet; the artifact's selected hypothesis set is pre-checked."}</p>
      )}

      <div className={css.candidateList}>
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
        ) : null}
        {candidates.map((candidate) => {
          const checked = selectedIds.includes(candidate.hypothesis_id);
          const checkDisabled =
            recordMutation.isPending ||
            (checked && selectedIds.length <= HYPOTHESIS_SELECTION_MIN) ||
            (!checked && selectedIds.length >= HYPOTHESIS_SELECTION_MAX);
          return (
            <article
              className={css.candidateCard}
              data-selected={checked ? "true" : "false"}
              key={candidate.hypothesis_id}
            >
              <div className={css.candidateTopline}>
                <VCheckbox
                  aria-label={isZh ? `选择假说 ${candidate.hypothesis_id}` : `Select hypothesis ${candidate.hypothesis_id}`}
                  className={css.candidateLabel}
                  isDisabled={checkDisabled}
                  isSelected={checked}
                  onChange={(next) => toggleCandidate(candidate.hypothesis_id, next)}
                >
                  <span>
                    <strong>{candidate.hypothesis_id} · {candidate.statement}</strong>
                    <small>{candidate.mechanism}</small>
                  </span>
                </VCheckbox>
              </div>
              <div className={css.candidateMeta}>
                <span>{isZh ? `预测 ${candidate.predictions.length} 条` : `${candidate.predictions.length} predictions`}</span>
                <span>{isZh ? `支持证据 ${candidate.supporting_evidence_refs.length} 条` : `${candidate.supporting_evidence_refs.length} supporting evidence`}</span>
              </div>
            </article>
          );
        })}
      </div>

      {recordMutation.isError ? (
        <VErrorSummary
          label={isZh ? "选择记录失败" : "Failed to record selection"}
          summary={
            recordMutation.error instanceof Error
              ? recordMutation.error.message
              : "record_hypothesis_selection_failed"
          }
        />
      ) : null}

      <div className={css.actions}>
        <VButton
          density="compact"
          disabledReason={
            !withinBounds
              ? (isZh
                ? `选择数量需在 ${HYPOTHESIS_SELECTION_MIN}–${HYPOTHESIS_SELECTION_MAX} 之间`
                : `Select between ${HYPOTHESIS_SELECTION_MIN} and ${HYPOTHESIS_SELECTION_MAX}`)
              : !dirty
                ? (isZh ? "选择未发生变化" : "Selection unchanged")
                : undefined
          }
          isDisabled={!withinBounds || !dirty}
          isPending={recordMutation.isPending}
          onPress={submitSelection}
          variant="primary"
        >
          {isZh ? "记录选择并开启评审" : "Record selection & start review"}
        </VButton>
        <VButton
          density="compact"
          disabledReason={isZh ? "记录选择并开启评审讨论后可用" : "Available after recording a selection and starting the review"}
          isDisabled={!reviewMeetingId}
          onPress={openMeetingSection}
          variant="secondary"
        >
          {isZh ? "查看评审讨论" : "View review discussion"}
        </VButton>
      </div>
    </section>
  );
}
