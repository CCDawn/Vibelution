import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  fetchHypothesisSelectionContext,
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

export function HypothesisSelectionPanel({ teamId, questionId }: HypothesisSelectionPanelProps) {
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

  if (contextQuery.isPending) {
    return <VStateSurface title="正在读取假说选择上下文" tone="loading" />;
  }
  if (contextQuery.isError || !context) {
    return (
      <VEmptyState title="假说选择上下文不可用">
        {contextQuery.error instanceof Error ? <code>{contextQuery.error.message}</code> : null}
      </VEmptyState>
    );
  }

  const candidates = context.candidates;
  const latestSelection = context.latestSelection;
  const reviewMeeting = context.reviewMeeting ?? null;
  const reviewMeetingId = reviewMeeting?.meetingRoundId ?? "";
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
          <h3>假说选择（假说先行）</h3>
          <p>
            已选 {selectedIds.length} / {candidates.length} 条候选（{HYPOTHESIS_SELECTION_MIN}–
            {HYPOTHESIS_SELECTION_MAX}）
          </p>
        </div>
        <div className={css.headingActions}>
          {reviewMeeting ? (
            <VStatusChip tone={meetingStatusTone(reviewMeeting.status)}>
              {MEETING_STATUS_LABELS[reviewMeeting.status] ?? reviewMeeting.status}
            </VStatusChip>
          ) : (
            <VStatusChip tone="neutral">未开启评审</VStatusChip>
          )}
        </div>
      </div>

      {latestSelection ? (
        <div className={css.summary}>
          <span>当前生效选择</span>
          <p>
            {latestSelection.selectionId} · {latestSelection.selectedCandidateIds.join("、")} ·{" "}
            {latestSelection.decidedBy || "unknown"} · {latestSelection.createdAt || "—"}
          </p>
        </div>
      ) : (
        <p className={css.hint}>尚未记录选择，默认勾选赛题 artifact 的已选假说集合。</p>
      )}

      <div className={css.candidateList}>
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
                  aria-label={`选择假说 ${candidate.hypothesis_id}`}
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
                <span>预测 {candidate.predictions.length} 条</span>
                <span>支持证据 {candidate.supporting_evidence_refs.length} 条</span>
              </div>
            </article>
          );
        })}
      </div>

      {recordMutation.isError ? (
        <VErrorSummary
          label="选择记录失败"
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
              ? `选择数量需在 ${HYPOTHESIS_SELECTION_MIN}–${HYPOTHESIS_SELECTION_MAX} 之间`
              : !dirty
                ? "选择未发生变化"
                : undefined
          }
          isDisabled={!withinBounds || !dirty}
          isPending={recordMutation.isPending}
          onPress={submitSelection}
          variant="primary"
        >
          记录选择并开启评审
        </VButton>
        <VButton
          density="compact"
          disabledReason="记录选择并开启评审讨论后可用"
          isDisabled={!reviewMeetingId}
          onPress={openMeetingSection}
          variant="secondary"
        >
          查看评审讨论
        </VButton>
      </div>
    </section>
  );
}
