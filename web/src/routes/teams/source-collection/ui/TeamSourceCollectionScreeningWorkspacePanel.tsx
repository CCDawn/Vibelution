/**
 * Source-collection screening / review workspace body.
 * Wave 8K: extracted from TeamsRoute.tsx for domain componentization.
 */
import type { ReactNode } from "react";
import { AlertTriangle, CheckCircle2, Eye, Plus, RefreshCw } from "lucide-react";

import type { Team, TeamWorkflowCandidate } from "../../../../api/types";
import { VButton, VNativeButton } from "../../../../components/vui";
import { TeamCandidateCard } from "../../../../components/vui/product/team-management";
import {
  sourceCollectionCandidateProvenance,
  sourceCollectionCandidateSourceCategory,
  sourceCollectionCandidateVersionFamily,
  sourceCollectionIndependentSourceCount,
  sourceCollectionEvidenceLedgerCardLabel,
  sourceCollectionEvidenceLedgerSummary,
  sourceCollectionEvidenceLedgerTone,
  sourceCollectionSourceFilterLabel,
} from "../evidenceModel";
import type { SourceCollectionSourceFilter } from "../evidenceModel";
import {
  candidateSourceQualityAssessmentSummary,
  formatTime,
  sourceCollectionResultTone,
  sourceCollectionSimpleCandidateStatusPresentation,
} from "../presentationModel";
import type { SourceCollectionActionReadiness, SourceCollectionStageModuleId } from "../stageProjection";
import type { TeamWorkflowSourceQualityStatus } from "../../useResearchWorkflowResources";
import type { useTeamSourceCollectionMutations } from "../../useTeamSourceCollectionMutations";
import type {
  candidatePaperNoteChunkPlanSummary as candidatePaperNoteChunkPlanSummaryFn,
  sourceCandidateHasCompletedExtraction as sourceCandidateHasCompletedExtractionFn,
} from "../../teamRouteShellModel";
import { TeamSourceCollectionScreeningPanel } from "./TeamSourceCollectionScreeningPanel";
import shellStyles from "../../../TeamsRoute.styles";
import workflowStyles from "../../../TeamsRoute.workflow.styles";

const styles = { ...shellStyles, ...workflowStyles } as Record<string, string>;

type Lang = "zh" | "en";

type SourceCollectionMutations = ReturnType<typeof useTeamSourceCollectionMutations>;

export type TeamSourceCollectionScreeningWorkspacePanelProps = {
  lang: Lang;
  sourceCollectionFilteredRunCandidates: TeamWorkflowCandidate[];
  sourceCollectionPageItems: <T>(stageId: SourceCollectionStageModuleId, items: T[]) => { items: T[]; start: number; end: number };
  sourceCollectionSourceFilter: string;
  sourceCollectionDisplayedCandidateCount: number;
  sourceCollectionCountText: (loading: boolean, count: number) => string;
  sourceCollectionPrimaryDataLoading: boolean;
  sourceCollectionDataSyncText: string;
  sourceCollectionFocusedPanelId: string;
  selectedSourceCollectionStageId: string;
  sourceCollectionExpandedPanelId: string;
  setSourceCollectionExpandedPanelId: (id: string) => void;
  sourceCollectionExtractionDefaultPanelId: string;
  sourceCollectionScreeningStepState: string;
  sourceCollectionDisplayedCandidateFilterCounts: Record<SourceCollectionSourceFilter, number>;
  renderSourceCollectionFilterBar: (counts: Record<SourceCollectionSourceFilter, number>, label: string, loading?: boolean) => ReactNode;
  sourceCollectionDisplayedCandidateCountText: string;
  sourceCollectionProjectedAssessedCountText: string;
  sourceCollectionProjectedApprovedCountText: string;
  sourceCollectionRunPendingScreeningCountText: string;
  sourceCollectionEvidenceReadyCandidateCount: number | string;
  sourceCollectionMissingEvidenceAnchorCount: number | string;
  runSourceCollectionScreeningAction: () => void;
  sourceCollectionScreeningDisabled: boolean;
  selectedTeamSourceQualityPending: boolean;
  sourceCollectionActionDisabledTitle: (readiness: SourceCollectionActionReadiness, label: string) => string | undefined;
  sourceCollectionScreeningActionReadiness: SourceCollectionActionReadiness;
  sourceCollectionScreeningButtonText: string;
  sourceCollectionScreeningButtonTitle?: string;
  sourceCollectionScreeningStatusText?: string | null;
  sourceCollectionQualityBatchFeedback?: string | null;
  /** When true, quality review is demoted: materials must be repaired first. */
  sourceCollectionQualityReviewIsSecondary?: boolean;
  sourceCollectionRecommendedNextHint?: string | null;
  openSourceCollectionScreeningPanel: () => void;
  renderSourceCollectionPagination: (stageId: SourceCollectionStageModuleId, total: number) => ReactNode;
  teamWorkflowSourceQualityStatus: TeamWorkflowSourceQualityStatus | null | undefined;
  teamWorkflowSourceQualityStatusQuery: { error?: unknown };
  workflowIngestionTone: (value: string) => string;
  selectedTeamSourceQualityError: Error | null;
  selectedSourceCollectionCandidateId: string;
  selectSourceCollectionCandidate: (candidate: TeamWorkflowCandidate) => void;
  selectedTeam: Team | null | undefined;
  selectedTeamAssessSourceQualityPending: boolean;
  assessSourceQualityMutation: SourceCollectionMutations["assessSourceQualityMutation"];
  selectedTeamPlanPaperNoteChunksPending: boolean;
  planPaperNoteChunksMutation: SourceCollectionMutations["planPaperNoteChunksMutation"];
  sourceCandidateHasCompletedExtraction: typeof sourceCandidateHasCompletedExtractionFn;
  candidatePaperNoteChunkPlanSummary: typeof candidatePaperNoteChunkPlanSummaryFn;
};

export function TeamSourceCollectionScreeningWorkspacePanel(props: TeamSourceCollectionScreeningWorkspacePanelProps) {
  const {
    lang,
    sourceCollectionFilteredRunCandidates,
    sourceCollectionPageItems,
    sourceCollectionSourceFilter,
    sourceCollectionDisplayedCandidateCount,
    sourceCollectionCountText,
    sourceCollectionPrimaryDataLoading,
    sourceCollectionDataSyncText,
    sourceCollectionFocusedPanelId,
    selectedSourceCollectionStageId,
    sourceCollectionExpandedPanelId,
    setSourceCollectionExpandedPanelId,
    sourceCollectionExtractionDefaultPanelId,
    sourceCollectionScreeningStepState,
    sourceCollectionDisplayedCandidateFilterCounts,
    renderSourceCollectionFilterBar,
    sourceCollectionDisplayedCandidateCountText,
    sourceCollectionProjectedAssessedCountText,
    sourceCollectionProjectedApprovedCountText,
    sourceCollectionRunPendingScreeningCountText,
    sourceCollectionEvidenceReadyCandidateCount,
    sourceCollectionMissingEvidenceAnchorCount,
    runSourceCollectionScreeningAction,
    sourceCollectionScreeningDisabled,
    selectedTeamSourceQualityPending,
    sourceCollectionActionDisabledTitle,
    sourceCollectionScreeningActionReadiness,
    sourceCollectionScreeningButtonText,
    sourceCollectionScreeningButtonTitle,
    sourceCollectionScreeningStatusText,
    sourceCollectionQualityBatchFeedback,
    sourceCollectionQualityReviewIsSecondary = false,
    sourceCollectionRecommendedNextHint = null,
    openSourceCollectionScreeningPanel,
    renderSourceCollectionPagination,
    teamWorkflowSourceQualityStatusQuery,
    selectedTeamSourceQualityError,
    selectedSourceCollectionCandidateId,
    selectSourceCollectionCandidate,
    selectedTeam,
    selectedTeamAssessSourceQualityPending,
    assessSourceQualityMutation,
    selectedTeamPlanPaperNoteChunksPending,
    planPaperNoteChunksMutation,
    sourceCandidateHasCompletedExtraction,
    candidatePaperNoteChunkPlanSummary,
  } = props;


    const filteredScreeningCandidates = sourceCollectionFilteredRunCandidates;
    const pagedScreeningCandidates = sourceCollectionPageItems("extraction", filteredScreeningCandidates);
    const screeningCandidates = pagedScreeningCandidates.items;
    const screeningListNeedsScrollHint = screeningCandidates.length > 3;
    const screeningPanelFilteredCount = sourceCollectionSourceFilter === "all"
      ? sourceCollectionDisplayedCandidateCount
      : filteredScreeningCandidates.length;
    const screeningPanelFilteredCountText = sourceCollectionCountText(sourceCollectionPrimaryDataLoading, screeningPanelFilteredCount);
    const screeningIndependentSourceCount = sourceCollectionIndependentSourceCount(filteredScreeningCandidates);
    const hasVersionFamilies = filteredScreeningCandidates.some((candidate) => Boolean(candidate.sourceVersionFamily?.versionLabel));
    const screeningPanelRange = sourceCollectionPrimaryDataLoading
      ? sourceCollectionDataSyncText
      : screeningCandidates.length
      ? `${pagedScreeningCandidates.start}-${pagedScreeningCandidates.end}/${filteredScreeningCandidates.length}`
      : `0/${screeningPanelFilteredCount}`;
    return (
      <TeamSourceCollectionScreeningPanel
        lang={lang}
        focused={sourceCollectionFocusedPanelId === "source-collection-screening-panel"}
        open={
          (
            selectedSourceCollectionStageId === "extraction"
            && !sourceCollectionExpandedPanelId
            && sourceCollectionExtractionDefaultPanelId === "source-collection-screening-panel"
          )
          || sourceCollectionExpandedPanelId === "source-collection-screening-panel"
          || sourceCollectionScreeningStepState === "active"
          || sourceCollectionScreeningStepState === "pending"
        }
        onToggle={(event) => {
          if (!event.currentTarget.open && sourceCollectionExpandedPanelId === "source-collection-screening-panel") {
            setSourceCollectionExpandedPanelId("");
          }
        }}
        rangeText={screeningPanelRange}
        filterBar={renderSourceCollectionFilterBar(sourceCollectionDisplayedCandidateFilterCounts, lang === "zh" ? "审查资料过滤" : "Review source filters", sourceCollectionPrimaryDataLoading)}
        stats={[
          { key: "candidate", label: lang === "zh" ? "本轮候选" : "run candidates", value: sourceCollectionDisplayedCandidateCountText },
          ...(hasVersionFamilies
            ? [{
              key: "independent-source",
              label: lang === "zh" ? "独立来源" : "independent sources",
              value: sourceCollectionCountText(sourceCollectionPrimaryDataLoading, screeningIndependentSourceCount),
            }]
            : []),
          { key: "filtered", label: lang === "zh" ? "当前过滤" : "filtered", value: screeningPanelFilteredCountText },
          { key: "reviewed", label: lang === "zh" ? "已审查" : "reviewed", value: sourceCollectionProjectedAssessedCountText },
          { key: "approved", label: lang === "zh" ? "通过" : "approved", value: sourceCollectionProjectedApprovedCountText },
          { key: "pending", label: lang === "zh" ? "待质量审查" : "pending quality review", value: sourceCollectionRunPendingScreeningCountText },
          { key: "evidence-ready", label: lang === "zh" ? "证据就绪" : "evidence ready", value: sourceCollectionEvidenceReadyCandidateCount },
          { key: "missing-evidence-anchor", label: lang === "zh" ? "缺证据锚点" : "missing evidence anchor", value: sourceCollectionMissingEvidenceAnchorCount },
        ]}
        actions={<>
          <VButton
            type="button"
            density="compact"
            variant={sourceCollectionQualityReviewIsSecondary ? "secondary" : "primary"}
            icon={<CheckCircle2 size={13} />}
            onPress={runSourceCollectionScreeningAction}
            isDisabled={sourceCollectionScreeningDisabled || selectedTeamSourceQualityPending}
            title={sourceCollectionActionDisabledTitle(sourceCollectionScreeningActionReadiness, sourceCollectionScreeningButtonText)
              || sourceCollectionScreeningButtonTitle
              || (sourceCollectionQualityReviewIsSecondary
                ? (lang === "zh" ? "请先在右侧点主按钮补材料，再审查" : "Repair materials with the right-stage primary button first")
                : sourceCollectionScreeningButtonText)}
          >
            {sourceCollectionScreeningButtonText}
          </VButton>
          <VButton
            type="button"
            density="compact"
            variant="secondary"
            icon={<Eye size={13} />}
            onPress={openSourceCollectionScreeningPanel}
            isDisabled={sourceCollectionScreeningDisabled}
            title={sourceCollectionActionDisabledTitle(sourceCollectionScreeningActionReadiness, lang === "zh" ? "查看筛选结果" : "View results")}
          >
            {lang === "zh" ? "查看筛选结果" : "View results"}
          </VButton>
        </>}
        hasCandidates={Boolean(screeningCandidates.length)}
        listNeedsScrollHint={screeningListNeedsScrollHint}
        emptyMessage={
          sourceCollectionPrimaryDataLoading
            ? (lang === "zh" ? "正在加载质量审查候选..." : "Loading quality-review candidates...")
            : sourceCollectionDisplayedCandidateCount
              ? (lang === "zh" ? "当前过滤条件下没有候选资料。" : "No candidates match this filter.")
              : (lang === "zh" ? "本轮还没有候选资料。先完成搜索资料并导入候选。" : "No candidates from this run yet.")
        }
        pagination={renderSourceCollectionPagination("extraction", filteredScreeningCandidates.length)}
        statusItems={(sourceCollectionRecommendedNextHint || sourceCollectionScreeningStatusText) ? (
          <div className={styles.messageResult} role="status">
            {sourceCollectionRecommendedNextHint
              ? sourceCollectionRecommendedNextHint
              : `${lang === "zh" ? "当前状态：" : "Status: "}${sourceCollectionScreeningStatusText}`}
          </div>
        ) : null}
        errors={<>
          {teamWorkflowSourceQualityStatusQuery.error instanceof Error ? (
            <div className={styles.messageError}>{teamWorkflowSourceQualityStatusQuery.error.message}</div>
          ) : null}
          {selectedTeamSourceQualityError ? (
            <div className={styles.messageError}>{selectedTeamSourceQualityError.message}</div>
          ) : null}
          {sourceCollectionQualityBatchFeedback ? (
            <div className={styles.messageResult} role="status">
              {sourceCollectionQualityBatchFeedback}
            </div>
          ) : null}
        </>}
      >
        {screeningCandidates.map((candidate) => {
                const chunkPlanSummary = candidatePaperNoteChunkPlanSummary(candidate);
                const sourceQualitySummary = candidateSourceQualityAssessmentSummary(candidate);
                const qualityPresentation = sourceQualitySummary
                  ? sourceCollectionSimpleCandidateStatusPresentation(candidate, lang)
                  : null;
                const evidenceLedgerSummary = sourceCollectionEvidenceLedgerSummary(candidate);
                const provenance = sourceCollectionCandidateProvenance(candidate, lang);
                const versionFamily = sourceCollectionCandidateVersionFamily(candidate, lang);
                const canPlanPaperNoteChunks = sourceCandidateHasCompletedExtraction(candidate);
                const candidateQualityPending =
                  selectedTeamAssessSourceQualityPending
                  && assessSourceQualityMutation.variables?.candidateId === candidate.candidateId;
                const candidatePlanPending =
                  selectedTeamPlanPaperNoteChunksPending
                  && planPaperNoteChunksMutation.variables?.candidateId === candidate.candidateId;
                const selected = selectedSourceCollectionCandidateId === candidate.candidateId;
                return (
                  <TeamCandidateCard
                    key={candidate.candidateId}
                    tone={evidenceLedgerSummary
                      ? sourceCollectionEvidenceLedgerTone(evidenceLedgerSummary)
                      : sourceCollectionResultTone(candidate.qualityStatus)}
                    statusLabel={
                      versionFamily?.isSuperseded
                        ? versionFamily.statusLabel
                        : qualityPresentation
                        ? qualityPresentation.label
                        : (lang === "zh" ? "待质量审查" : "pending quality review")
                    }
                    statusTitle={
                      versionFamily?.isSuperseded
                        ? versionFamily.reviewDisabledReason
                        : qualityPresentation?.title
                    }
                    title={candidate.title || candidate.candidateId}
                    summary={candidate.summary || candidate.candidateType}
                    meta={[
                      { key: "category", label: sourceCollectionSourceFilterLabel(sourceCollectionCandidateSourceCategory(candidate, lang), lang) },
                      { key: "updated", label: formatTime(candidate.updatedAt, lang) },
                      ...(versionFamily
                        ? [
                          { key: "version-chain", label: versionFamily.chainLabel },
                          { key: "version-evidence-policy", label: versionFamily.evidenceLabel },
                        ]
                        : []),
                      ...(sourceQualitySummary
                        ? [{ key: "score", label: `${lang === "zh" ? "评分" : "score"} ${sourceQualitySummary.overallScore}/100` }]
                        : []),
                      ...(evidenceLedgerSummary
                        ? [{ key: "evidence-ledger", label: sourceCollectionEvidenceLedgerCardLabel(evidenceLedgerSummary, lang) }]
                        : []),
                      ...(chunkPlanSummary
                        ? [{ key: "chunks", label: `paper_note ${chunkPlanSummary.completedChunkCount}/${chunkPlanSummary.chunkCount}` }]
                        : canPlanPaperNoteChunks
                          ? [{ key: "chunks", label: lang === "zh" ? "可分块" : "chunk ready" }]
                          : []),
                    ]}
                    source={{
                      label: provenance.label,
                      value: provenance.value,
                      href: provenance.href,
                      title: provenance.href || provenance.value,
                      missing: provenance.kind === "missing",
                    }}
                    selected={selected}
                    onActivate={() => selectSourceCollectionCandidate(candidate)}
                    activateTitle={lang === "zh" ? "点击查看来源详情" : "Open source detail"}
                    actions={<>
                      <VNativeButton
                        type="button"
                        onClick={(event) => {
                          event.stopPropagation();
                          if (!selectedTeam?.teamId || selectedTeamSourceQualityPending || versionFamily?.isSuperseded) {
                            return;
                          }
                          assessSourceQualityMutation.mutate({
                            teamId: selectedTeam.teamId,
                            candidateId: candidate.candidateId,
                            decision: "approved",
                          });
                        }}
                        disabled={!selectedTeam?.teamId || selectedTeamSourceQualityPending || versionFamily?.isSuperseded}
                        title={versionFamily?.reviewDisabledReason || undefined}
                      >
                        <CheckCircle2 size={13} />
                        {candidateQualityPending && assessSourceQualityMutation.variables?.decision === "approved"
                          ? (lang === "zh" ? "筛选中" : "Assessing")
                          : (lang === "zh" ? "通过复核" : "Approve")}
                      </VNativeButton>
                      <VNativeButton
                        type="button"
                        onClick={(event) => {
                          event.stopPropagation();
                          if (!selectedTeam?.teamId || selectedTeamSourceQualityPending || versionFamily?.isSuperseded) {
                            return;
                          }
                          assessSourceQualityMutation.mutate({
                            teamId: selectedTeam.teamId,
                            candidateId: candidate.candidateId,
                            decision: "needs_revision",
                          });
                        }}
                        disabled={!selectedTeam?.teamId || selectedTeamSourceQualityPending || versionFamily?.isSuperseded}
                        title={versionFamily?.reviewDisabledReason || undefined}
                      >
                        <AlertTriangle size={13} />
                        {candidateQualityPending && assessSourceQualityMutation.variables?.decision === "needs_revision"
                          ? (lang === "zh" ? "退回中" : "Returning")
                          : (lang === "zh" ? "退回补资料" : "Repair")}
                      </VNativeButton>
                      <VNativeButton
                        type="button"
                        onClick={(event) => {
                          event.stopPropagation();
                          if (
                            !selectedTeam?.teamId
                            || !canPlanPaperNoteChunks
                            || planPaperNoteChunksMutation.isPending
                            || versionFamily?.isSuperseded
                          ) {
                            return;
                          }
                          planPaperNoteChunksMutation.mutate({
                            teamId: selectedTeam.teamId,
                            candidateId: candidate.candidateId,
                          });
                        }}
                        disabled={
                          !selectedTeam?.teamId
                          || !canPlanPaperNoteChunks
                          || planPaperNoteChunksMutation.isPending
                          || versionFamily?.isSuperseded
                        }
                        title={versionFamily?.reviewDisabledReason || undefined}
                      >
                        {chunkPlanSummary ? <RefreshCw size={13} /> : <Plus size={13} />}
                        {candidatePlanPending
                          ? (lang === "zh" ? "规划中" : "Planning")
                          : chunkPlanSummary
                            ? (lang === "zh" ? "重建分块" : "Rebuild chunks")
                            : (lang === "zh" ? "生成分块" : "Plan chunks")}
                      </VNativeButton>
                    </>}
                  />
                );
              })}
      </TeamSourceCollectionScreeningPanel>
    );

}
