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
} from "../../../components/vui";
import { invalidateHypothesisFirstQueries } from "../research-workflow/useHypothesisFirstChain";
import css from "./HypothesisSelectionList.styles";

export const HYPOTHESIS_SELECTION_MIN = 1;
export const HYPOTHESIS_SELECTION_MAX = 16;

export type HypothesisSelectionListProps = {
  teamId: string;
  questionId: string;
  lang?: "zh" | "en";
  compact?: boolean;
  hideSubmit?: boolean;
};

function sameIdSet(left: string[], right: string[]): boolean {
  if (left.length !== right.length) return false;
  const rightSet = new Set(right);
  return left.every((id) => rightSet.has(id));
}

export function HypothesisSelectionList({
  teamId,
  questionId,
  lang = "zh",
  hideSubmit = false,
}: HypothesisSelectionListProps) {
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
      invalidateHypothesisFirstQueries(queryClient, teamId, questionId);
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

  return (
    <div data-testid="hypothesis-selection-list">
      {latestSelection ? (
        <div className={css.summary}>
          <span>{isZh ? "当前生效选择" : "Current effective selection"}</span>
          <p>
            {isZh
              ? `已选 ${latestSelection.selectedCandidateIds.length} 条假说`
              : `${latestSelection.selectedCandidateIds.length} hypotheses selected`}
          </p>
        </div>
      ) : null}
      {candidates.length > 0 ? (
        <div className={css.summary}>
          <span>{isZh ? "快捷操作" : "Quick actions"}</span>
          <p>
            <VButton
              density="compact"
              variant="ghost"
              isDisabled={
                recordMutation.isPending
                || selectedIds.length === candidates.length
                || candidates.length > HYPOTHESIS_SELECTION_MAX
              }
              disabledReason={
                candidates.length > HYPOTHESIS_SELECTION_MAX
                  ? (isZh
                    ? `候选超过上限 ${HYPOTHESIS_SELECTION_MAX} 条，请手动选择`
                    : `More than ${HYPOTHESIS_SELECTION_MAX} candidates; select manually`)
                  : undefined
              }
              onPress={() =>
                setSelectedIds(candidates.slice(0, HYPOTHESIS_SELECTION_MAX).map((c) => c.hypothesis_id))}
            >
              {isZh ? `全选送审（${Math.min(candidates.length, HYPOTHESIS_SELECTION_MAX)} 条）` : "Select all"}
            </VButton>
          </p>
        </div>
      ) : null}
      <div className={css.candidateList}>
        {candidates.length === 0 ? (
          <VEmptyState title={isZh ? "尚无候选假说" : "No candidate hypotheses yet"} />
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
                    <strong>{candidate.statement}</strong>
                    {candidate.mechanism ? <small>{candidate.mechanism}</small> : null}
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
      {hideSubmit ? null : (
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
        </div>
      )}
    </div>
  );
}
