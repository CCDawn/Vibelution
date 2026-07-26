/**
 * Source-collection screening / review workspace body.
 * Wave 8K: extracted from TeamsRoute.tsx for domain componentization.
 */
import type { ReactNode } from "react";
import { AlertTriangle, CheckCircle2, Eye, Plus, RefreshCw } from "lucide-react";

import type { Team } from "../api/types";
import { VButton, VNativeButton } from "../components/vui";
import { TeamCandidateCard } from "../components/vui/product/team-management";
import {
  sourceCollectionCandidateProvenance,
  sourceCollectionCandidateSourceCategory,
  sourceCollectionSourceFilterLabel,
} from "./teams/source-collection/evidenceModel";
import {
  candidateSourceQualityAssessmentSummary,
  formatTime,
  sourceCollectionResultTone,
  workflowIngestionStatusLabel,
} from "./teams/source-collection/presentationModel";
import type { SourceCollectionStageModuleId } from "./teams/source-collection/stageProjection";
import { TeamSourceCollectionScreeningPanel } from "./TeamSourceCollectionScreeningPanel";
import shellStyles from "./TeamsRoute.styles";
import workflowStyles from "./TeamsRoute.workflow.styles";

const styles = { ...shellStyles, ...workflowStyles } as Record<string, string>;

type Lang = "zh" | "en";

export type TeamSourceCollectionScreeningWorkspacePanelProps = {
  lang: Lang;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionFilteredRunCandidates: any[];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionPageItems: (stageId: SourceCollectionStageModuleId, items: any[]) => { items: any[]; start: number; end: number };
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
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionDisplayedCandidateFilterCounts: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  renderSourceCollectionFilterBar: (...args: any[]) => ReactNode;
  sourceCollectionDisplayedCandidateCountText: string;
  sourceCollectionProjectedAssessedCountText: string;
  sourceCollectionProjectedApprovedCountText: string;
  sourceCollectionRunPendingScreeningCountText: string;
  sourceCollectionEvidenceReadyCandidateCount: number | string;
  sourceCollectionMissingEvidenceAnchorCount: number | string;
  runSourceCollectionScreeningAction: () => void;
  sourceCollectionScreeningDisabled: boolean;
  selectedTeamSourceQualityPending: boolean;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionActionDisabledTitle: (readiness: any, label: string) => string | undefined;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionScreeningActionReadiness: any;
  sourceCollectionScreeningButtonText: string;
  openSourceCollectionScreeningPanel: () => void;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  renderSourceCollectionPagination: (stageId: SourceCollectionStageModuleId, total: number) => ReactNode;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  teamWorkflowSourceQualityStatus: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  teamWorkflowSourceQualityStatusQuery: { error?: unknown };
  workflowIngestionTone: (value: string) => string;
  selectedTeamSourceQualityError: Error | null;
  selectedSourceCollectionCandidateId: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectSourceCollectionCandidate: (candidate: any) => void;
  selectedTeam: Team | null | undefined;
  selectedTeamAssessSourceQualityPending: boolean;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  assessSourceQualityMutation: any;
  selectedTeamPlanPaperNoteChunksPending: boolean;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  planPaperNoteChunksMutation: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCandidateHasCompletedExtraction: (candidate: any) => boolean;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  candidatePaperNoteChunkPlanSummary: (candidate: any) => any;
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
    openSourceCollectionScreeningPanel,
    renderSourceCollectionPagination,
    teamWorkflowSourceQualityStatus,
    teamWorkflowSourceQualityStatusQuery,
    workflowIngestionTone,
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
          { key: "filtered", label: lang === "zh" ? "当前过滤" : "filtered", value: screeningPanelFilteredCountText },
          { key: "reviewed", label: lang === "zh" ? "已审查" : "reviewed", value: sourceCollectionProjectedAssessedCountText },
          { key: "approved", label: lang === "zh" ? "通过" : "approved", value: sourceCollectionProjectedApprovedCountText },
          { key: "pending", label: lang === "zh" ? "待 Agent 复核" : "pending agent review", value: sourceCollectionRunPendingScreeningCountText },
          { key: "evidence-ready", label: "evidence_ready", value: sourceCollectionEvidenceReadyCandidateCount },
          { key: "missing-evidence-anchor", label: "missing_evidence_anchor", value: sourceCollectionMissingEvidenceAnchorCount },
        ]}
        actions={<>
          <VButton
            type="button"
            density="compact"
            variant="primary"
            icon={<CheckCircle2 size={13} />}
            onPress={runSourceCollectionScreeningAction}
            isDisabled={sourceCollectionScreeningDisabled || selectedTeamSourceQualityPending}
            title={sourceCollectionActionDisabledTitle(sourceCollectionScreeningActionReadiness, sourceCollectionScreeningButtonText)}
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
            ? (lang === "zh" ? "正在加载资料提炼复核候选..." : "Loading review candidates...")
            : sourceCollectionDisplayedCandidateCount
              ? (lang === "zh" ? "当前过滤条件下没有候选资料。" : "No candidates match this filter.")
              : (lang === "zh" ? "本轮还没有候选资料。先完成搜索资料并导入候选。" : "No candidates from this run yet.")
        }
        pagination={renderSourceCollectionPagination("extraction", filteredScreeningCandidates.length)}
        statusItems={teamWorkflowSourceQualityStatus?.actionItems.length
          ? teamWorkflowSourceQualityStatus.actionItems.slice(0, 3).map((item: any) => (
            <span key={`${item.code}-${item.candidateId}`} className={workflowIngestionTone(item.severity)}>
              {workflowIngestionStatusLabel(item.severity, lang)} · {item.message}
            </span>
          ))
          : null}
        errors={<>
          {teamWorkflowSourceQualityStatusQuery.error instanceof Error ? (
            <div className={styles.messageError}>{teamWorkflowSourceQualityStatusQuery.error.message}</div>
          ) : null}
          {selectedTeamSourceQualityError ? (
            <div className={styles.messageError}>{selectedTeamSourceQualityError.message}</div>
          ) : null}
        </>}
      >
        {screeningCandidates.map((candidate: any) => {
                const chunkPlanSummary = candidatePaperNoteChunkPlanSummary(candidate);
                const sourceQualitySummary = candidateSourceQualityAssessmentSummary(candidate);
                const provenance = sourceCollectionCandidateProvenance(candidate, lang);
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
                    tone={sourceCollectionResultTone(candidate.qualityStatus)}
                    statusLabel={
                      sourceQualitySummary
                        ? workflowIngestionStatusLabel(sourceQualitySummary.decision, lang)
                        : (lang === "zh" ? "待 Agent 复核" : "pending agent review")
                    }
                    title={candidate.title || candidate.candidateId}
                    summary={candidate.summary || candidate.candidateType}
                    meta={[
                      { key: "category", label: sourceCollectionSourceFilterLabel(sourceCollectionCandidateSourceCategory(candidate, lang), lang) },
                      { key: "updated", label: formatTime(candidate.updatedAt, lang) },
                      ...(sourceQualitySummary
                        ? [{ key: "score", label: `${lang === "zh" ? "评分" : "score"} ${sourceQualitySummary.overallScore}/100` }]
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
                          if (!selectedTeam?.teamId || selectedTeamSourceQualityPending) {
                            return;
                          }
                          assessSourceQualityMutation.mutate({
                            teamId: selectedTeam.teamId,
                            candidateId: candidate.candidateId,
                            decision: "approved",
                          });
                        }}
                        disabled={!selectedTeam?.teamId || selectedTeamSourceQualityPending}
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
                          if (!selectedTeam?.teamId || selectedTeamSourceQualityPending) {
                            return;
                          }
                          assessSourceQualityMutation.mutate({
                            teamId: selectedTeam.teamId,
                            candidateId: candidate.candidateId,
                            decision: "needs_revision",
                          });
                        }}
                        disabled={!selectedTeam?.teamId || selectedTeamSourceQualityPending}
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
                          if (!selectedTeam?.teamId || !canPlanPaperNoteChunks || planPaperNoteChunksMutation.isPending) {
                            return;
                          }
                          planPaperNoteChunksMutation.mutate({
                            teamId: selectedTeam.teamId,
                            candidateId: candidate.candidateId,
                          });
                        }}
                        disabled={!selectedTeam?.teamId || !canPlanPaperNoteChunks || planPaperNoteChunksMutation.isPending}
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
