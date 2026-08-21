import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  fetchCandidateEvidenceTrail,
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

export const HYPOTHESIS_SELECTION_MIN = 2;
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
  compact = false,
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
  const previousServerBaseline = useRef<string[]>(serverBaseline);
  useEffect(() => {
    if (sameIdSet(previousServerBaseline.current, serverBaseline)) return;
    previousServerBaseline.current = [...serverBaseline];
    setSelectedIds([...serverBaseline]);
  }, [serverBaseline]);

  const recordMutation = useMutation({
    mutationFn: (input: HypothesisSelectionRecordPayload) =>
      recordHypothesisSelection(teamId, input),
    onSuccess: () => {
      invalidateHypothesisFirstQueries(queryClient, teamId, questionId);
    },
  });

  const candidates = context?.candidates ?? [];
  const reviewClosed = context?.reviewMeeting?.status === "closed";
  const effectiveSelectedIds =
    context?.latestSelection?.selectedCandidateIds ??
    context?.defaultSelectedCandidateIds ??
    [];
  const effectiveSelectedIdSet = new Set(effectiveSelectedIds);
  const visibleCandidates = reviewClosed
    ? candidates.filter((candidate) => effectiveSelectedIdSet.has(candidate.hypothesis_id))
    : candidates;
  const visibleCandidateIds = visibleCandidates.map((candidate) => candidate.hypothesis_id);
  const preferredCandidateId =
    effectiveSelectedIds.find((candidateId) => visibleCandidateIds.includes(candidateId)) ??
    visibleCandidateIds[0] ??
    null;
  const visibleCandidateKey = JSON.stringify(visibleCandidateIds);
  const [focusedCandidateId, setFocusedCandidateId] = useState<string | null>(null);
  useEffect(() => {
    if (!compact) return;
    setFocusedCandidateId((current) =>
      current && visibleCandidateIds.includes(current) ? current : preferredCandidateId,
    );
  }, [compact, preferredCandidateId, visibleCandidateKey]);

  const [expandedTrailCandidateId, setExpandedTrailCandidateId] = useState<string | null>(null);
  const trailQuery = useQuery({
    queryKey: ["hypothesis-first", "candidate-evidence-trail", teamId, questionId],
    queryFn: ({ signal }) => fetchCandidateEvidenceTrail(teamId, questionId, { signal }),
    enabled: Boolean(teamId && questionId && candidates.length > 0),
    staleTime: 30_000,
  });
  const trailByCandidate = new Map(
    (trailQuery.data?.trails ?? []).map((trail) => [trail.candidateId, trail.entries]),
  );

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

  const latestSelection = context.latestSelection;
  const dirty = !sameIdSet(selectedIds, serverBaseline);
  const withinBounds =
    selectedIds.length >= HYPOTHESIS_SELECTION_MIN &&
    selectedIds.length <= HYPOTHESIS_SELECTION_MAX;
  const selectionMinimumHint = selectedIds.length <= HYPOTHESIS_SELECTION_MIN
    ? (isZh
      ? `已达到最低选择数（${HYPOTHESIS_SELECTION_MIN} 条）；如需更换，请先勾选另一条，再取消当前选择。`
      : `The minimum is ${HYPOTHESIS_SELECTION_MIN} selections. To replace one, select another first, then remove the current one.`)
    : null;

  const toggleCandidate = (candidateId: string, next: boolean) => {
    if (!next && selectedIds.length <= HYPOTHESIS_SELECTION_MIN) {
      return;
    }
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
      {reviewClosed ? (
        <div className={css.selectionToolbar} data-testid="hypothesis-selection-archive-summary">
          <span>{isZh ? "最终采用" : "Final selection"}</span>
          <strong>
            {isZh
              ? `${visibleCandidates.length} 条`
              : `${visibleCandidates.length} selected`}
          </strong>
        </div>
      ) : candidates.length > 0 ? (
        <div className={css.selectionToolbar}>
          <span>
            {isZh
              ? `已选 ${selectedIds.length}/${candidates.length}`
              : `${selectedIds.length}/${candidates.length} selected`}
          </span>
          {candidates.length > selectedIds.length ? (
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
          ) : null}
        </div>
      ) : null}
      {selectionMinimumHint ? (
        <p className={css.hint} data-testid="hypothesis-selection-minimum-hint" role="status">
          {selectionMinimumHint}
        </p>
      ) : null}
      <div className={css.candidateList}>
        {visibleCandidates.length === 0 ? (
          <VEmptyState
            title={
              reviewClosed
                ? (isZh ? "没有可归档的最终选择" : "No final selection to archive")
                : (isZh ? "尚无候选假说" : "No candidate hypotheses yet")
            }
          />
        ) : null}
        {visibleCandidates.map((candidate) => {
          const checked = selectedIds.includes(candidate.hypothesis_id);
          const candidateExpanded = !compact || focusedCandidateId === candidate.hypothesis_id;
          const trailEntries = trailByCandidate.get(candidate.hypothesis_id) ?? [];
          const hasTrail = trailEntries.length > 0;
          const checkDisabled =
            recordMutation.isPending ||
            (checked && selectedIds.length <= HYPOTHESIS_SELECTION_MIN) ||
            (!checked && selectedIds.length >= HYPOTHESIS_SELECTION_MAX);
          return (
            <article
              className={css.candidateCard}
              data-expanded={candidateExpanded ? "true" : "false"}
              data-selected={checked ? "true" : "false"}
              key={candidate.hypothesis_id}
            >
              <div className={css.candidateTopline}>
                {reviewClosed ? null : (
                  <VCheckbox
                    aria-label={isZh ? `选择假说 ${candidate.hypothesis_id}` : `Select hypothesis ${candidate.hypothesis_id}`}
                    isDisabled={checkDisabled}
                    isSelected={checked}
                    onChange={(next) => toggleCandidate(candidate.hypothesis_id, next)}
                  />
                )}
                <div className={css.candidateLabel}>
                  <strong>{candidate.statement}</strong>
                  {!compact && candidate.mechanism ? <small>{candidate.mechanism}</small> : null}
                </div>
                {compact ? (
                  <VButton
                    aria-expanded={candidateExpanded}
                    aria-label={
                      candidateExpanded
                        ? (isZh ? `收起候选 ${candidate.hypothesis_id}` : `Collapse candidate ${candidate.hypothesis_id}`)
                        : (isZh ? `展开候选 ${candidate.hypothesis_id}` : `Expand candidate ${candidate.hypothesis_id}`)
                    }
                    className={css.candidateDisclosure}
                    density="compact"
                    onPress={() => {
                      setFocusedCandidateId((current) =>
                        current === candidate.hypothesis_id ? null : candidate.hypothesis_id,
                      );
                      setExpandedTrailCandidateId(null);
                    }}
                    variant="ghost"
                  >
                    {candidateExpanded
                      ? (isZh ? "收起" : "Collapse")
                      : (isZh ? "展开" : "Expand")}
                  </VButton>
                ) : null}
              </div>
              {candidateExpanded ? (
                <div className={css.candidateDetail}>
                  {compact && candidate.mechanism ? <p>{candidate.mechanism}</p> : null}
                  <div className={css.candidateMeta}>
                    {candidate.predictions.length > 0 ? (
                      <span>{isZh ? `预测 ${candidate.predictions.length} 条` : `${candidate.predictions.length} predictions`}</span>
                    ) : null}
                    {hasTrail ? (
                      <VButton
                        density="compact"
                        variant="ghost"
                        className={css.trailToggle}
                        aria-expanded={expandedTrailCandidateId === candidate.hypothesis_id}
                        onPress={() =>
                          setExpandedTrailCandidateId((current) =>
                            current === candidate.hypothesis_id ? null : candidate.hypothesis_id,
                          )
                        }
                      >
                        {expandedTrailCandidateId === candidate.hypothesis_id
                          ? (isZh ? "收起证据轨迹" : "Hide evidence trail")
                          : (isZh ? "查看证据轨迹" : "View evidence trail")}
                      </VButton>
                    ) : null}
                  </div>
                  {expandedTrailCandidateId === candidate.hypothesis_id && hasTrail ? (
                    <div className={css.evidenceTrail} data-testid="candidate-evidence-trail">
                      <ul className={css.trailList}>
                        {trailEntries.map((entry) => (
                          <li key={`${entry.meetingRoundId}:${entry.messageId}`}>
                            <span className={css.trailSource}>
                              {entry.meetingLabel} · {entry.speaker}
                            </span>
                            <p className={css.trailExcerpt}>{entry.excerpt}</p>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                </div>
              ) : null}
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
      {hideSubmit || reviewClosed ? null : (
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
