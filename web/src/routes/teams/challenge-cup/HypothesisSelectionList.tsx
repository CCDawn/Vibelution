import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  executeHypothesisFirstCommand,
  fetchCandidateEvidenceTrail,
  fetchHypothesisSelectionContext,
  fetchHypothesisFirstStateV2,
  isHypothesisFirstCommandStateConflict,
  isHypothesisFirstStateV2EndpointUnavailable,
  recordHypothesisSelection,
} from "../../../api/hypothesisFirst";
import { queryKeys } from "../../../api/queryKeys";
import {
  observeHypothesisLegacyFallback,
  trackHypothesisSelectionRecord,
} from "../challengeCupTelemetry";
import type {
  CommandAction,
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
import { projectHypothesisFirstSelection } from "../research-workflow/hypothesisFirstStateV2Adapter";
import { invalidateHypothesisFirstQueries } from "../research-workflow/useHypothesisFirstChain";
import css from "./HypothesisSelectionList.styles";

export const HYPOTHESIS_SELECTION_MIN = 2;
export const HYPOTHESIS_SELECTION_MAX = 16;

export type HypothesisSelectionListProps = {
  teamId: string;
  questionId: string;
  runId?: string;
  lang?: "zh" | "en";
  compact?: boolean;
  hideSubmit?: boolean;
  canonicalAction?: Extract<CommandAction, { command: "record_selection" }>;
  allowLegacyMutation?: boolean;
};

function sameIdSet(left: string[], right: string[]): boolean {
  if (left.length !== right.length) return false;
  const rightSet = new Set(right);
  return left.every((id) => rightSet.has(id));
}

export function HypothesisSelectionList({
  teamId,
  questionId,
  runId = "",
  lang = "zh",
  compact = false,
  hideSubmit = false,
  canonicalAction,
  allowLegacyMutation = false,
}: HypothesisSelectionListProps) {
  const isZh = lang === "zh";
  const queryClient = useQueryClient();
  const contextQuery = useQuery({
    queryKey: queryKeys.hypothesisFirstSelectionContext(teamId, questionId, runId),
    queryFn: () => fetchHypothesisSelectionContext(teamId, questionId, { runId }),
    enabled: Boolean(teamId && questionId),
    staleTime: 15_000,
  });
  const context: HypothesisSelectionContext | undefined = contextQuery.data;
  const stateV2Query = useQuery({
    queryKey: queryKeys.hypothesisFirstChainStateV2(teamId, questionId, runId),
    queryFn: ({ signal }) => fetchHypothesisFirstStateV2(teamId, questionId, { signal, runId }),
    enabled: Boolean(teamId && questionId),
    retry: false,
    staleTime: 15_000,
    refetchOnWindowFocus: "always",
    refetchOnReconnect: "always",
  });
  const selectionProjection = useMemo(
    () => projectHypothesisFirstSelection({
      state: stateV2Query.data,
      loading: stateV2Query.isPending,
      error: stateV2Query.error,
      expectedTeamId: teamId,
      expectedQuestionId: questionId,
    }),
    [questionId, stateV2Query.data, stateV2Query.error, stateV2Query.isPending, teamId],
  );
  const v2EndpointUnavailable = isHypothesisFirstStateV2EndpointUnavailable(stateV2Query.error);
  const useLegacyFallback = Boolean(
    allowLegacyMutation
    && !stateV2Query.data
    && v2EndpointUnavailable,
  );
  // Bounded degradation evidence: the V2 chain endpoint is the canonical path;
  // falling back to the legacy mutation signals backend API degradation.
  const legacyFallbackObservedRef = useRef(false);
  useEffect(() => {
    if (legacyFallbackObservedRef.current || !useLegacyFallback) return;
    legacyFallbackObservedRef.current = true;
    observeHypothesisLegacyFallback({ teamId, questionId });
  }, [useLegacyFallback, teamId, questionId]);
  const canonicalSelection = selectionProjection.status === "editable"
    ? selectionProjection.canonicalAction
    : undefined;
  const mutationCanonicalAction = canonicalSelection
    ?? (useLegacyFallback ? canonicalAction : undefined);
  const serverBaseline = useMemo(() => {
    if (useLegacyFallback) {
      return context?.latestSelection?.selectedCandidateIds
        ?? context?.defaultSelectedCandidateIds
        ?? [];
    }
    if (selectionProjection.status === "editable") {
      // V2 owns whether mutation is allowed; the selection-context default is
      // only the initial local draft. It must not be written back into V2 or
      // mistaken for an already committed selection.
      return context?.defaultSelectedCandidateIds ?? [];
    }
    if (selectionProjection.selectedCandidateIds.length > 0) {
      return selectionProjection.selectedCandidateIds;
    }
    // Loading, degraded, and ambiguous states remain mutation-locked. Only a
    // persisted latestSelection may be shown here; default selections are
    // draft suggestions and must not be presented as already committed.
    return context?.latestSelection?.selectedCandidateIds ?? [];
  }, [context, selectionProjection.selectedCandidateIds, selectionProjection.status, useLegacyFallback]);
  const [selectedIds, setSelectedIds] = useState<string[]>(serverBaseline);
  const previousServerBaseline = useRef<string[]>(serverBaseline);
  useEffect(() => {
    if (sameIdSet(previousServerBaseline.current, serverBaseline)) return;
    previousServerBaseline.current = [...serverBaseline];
    setSelectedIds([...serverBaseline]);
  }, [serverBaseline]);

  const recordMutation = useMutation<
    unknown,
    Error,
    HypothesisSelectionRecordPayload,
    { telemetry: ReturnType<typeof trackHypothesisSelectionRecord> }
  >({
    onMutate: (input) => ({
      telemetry: trackHypothesisSelectionRecord({
        teamId,
        questionId,
        selectedCount: input.selectedCandidateIds.length,
        candidateCount: context?.candidates.length ?? 0,
        path: mutationCanonicalAction ? "canonical" : (useLegacyFallback ? "legacy" : "unavailable"),
        previousSelectionId: input.previousSelectionId,
      }),
    }),
    mutationFn: (input: HypothesisSelectionRecordPayload) => {
      if (mutationCanonicalAction) {
        return executeHypothesisFirstCommand(teamId, questionId, mutationCanonicalAction, {
          candidateIds: input.selectedCandidateIds,
        }, { runId });
      }
      if (useLegacyFallback) return recordHypothesisSelection(teamId, input);
      return Promise.reject(new Error("canonical_action_unavailable"));
    },
    onSuccess: (_data, _vars, ctx) => {
      ctx?.telemetry?.succeeded();
      invalidateHypothesisFirstQueries(queryClient, teamId, questionId, runId);
    },
    onError: (error, _vars, ctx) => {
      ctx?.telemetry?.failed(error, {
        stateConflict: isHypothesisFirstCommandStateConflict(error),
      });
      if (isHypothesisFirstCommandStateConflict(error)) {
        invalidateHypothesisFirstQueries(queryClient, teamId, questionId, runId);
      }
    },
  });

  const candidates = context?.candidates ?? [];
  const reviewClosed = context?.reviewMeeting?.status === "closed";
  const effectiveSelectedIds = serverBaseline;
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
    queryKey: ["hypothesis-first", "candidate-evidence-trail", teamId, questionId, runId],
    queryFn: ({ signal }) => fetchCandidateEvidenceTrail(teamId, questionId, { signal, runId }),
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
  const mutationAuthorized = Boolean(mutationCanonicalAction) || useLegacyFallback;
  const withinBounds =
    selectedIds.length >= HYPOTHESIS_SELECTION_MIN &&
    selectedIds.length <= HYPOTHESIS_SELECTION_MAX;
  const selectionMinimumHint = selectedIds.length <= HYPOTHESIS_SELECTION_MIN
    && mutationAuthorized
    ? (isZh
      ? `已达到最低选择数（${HYPOTHESIS_SELECTION_MIN} 条）；如需更换，请先勾选另一条，再取消当前选择。`
      : `The minimum is ${HYPOTHESIS_SELECTION_MIN} selections. To replace one, select another first, then remove the current one.`)
    : null;

  const toggleCandidate = (candidateId: string, next: boolean) => {
    if (!mutationAuthorized) return;
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
      workflowRunId: runId,
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
                || !mutationAuthorized
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
            !mutationAuthorized ||
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
            isHypothesisFirstCommandStateConflict(recordMutation.error)
              ? (isZh ? "状态已更新，请重新确认。" : "The workflow state changed. Review it and confirm again.")
              : recordMutation.error instanceof Error
              ? recordMutation.error.message
              : "record_hypothesis_selection_failed"
          }
        />
      ) : null}
      {hideSubmit || reviewClosed ? null : (
        <div
          className={compact ? css.stickyActions : css.actions}
          data-current-task-action={compact ? "true" : undefined}
        >
          <VButton
            density="compact"
            disabledReason={
              !withinBounds
                ? (isZh
                  ? `选择数量需在 ${HYPOTHESIS_SELECTION_MIN}–${HYPOTHESIS_SELECTION_MAX} 之间`
                  : `Select between ${HYPOTHESIS_SELECTION_MIN} and ${HYPOTHESIS_SELECTION_MAX}`)
                : !mutationAuthorized
                  ? (isZh ? "当前状态没有可执行的已签名操作，请刷新状态" : "No signed action is available for the current state; refresh it")
                : !dirty
                  ? (isZh ? "选择未发生变化" : "Selection unchanged")
                  : undefined
            }
            isDisabled={!withinBounds || !dirty || !mutationAuthorized}
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
