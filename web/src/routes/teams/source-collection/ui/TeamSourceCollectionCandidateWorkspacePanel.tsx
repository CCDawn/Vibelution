/**
 * Source-collection extracted-candidates workspace body.
 * Wave 8L: extracted from TeamsRoute.tsx for domain componentization.
 */
import { memo, useCallback, useEffect, useRef, type ReactNode } from "react";

import { TeamCandidateCard } from "../../../../components/vui/product/team-management";
import {
  sourceCollectionCandidateProvenance,
  sourceCollectionCandidateSourceCategory,
  sourceCollectionEvidenceLedgerCardLabel,
  sourceCollectionEvidenceLedgerSummary,
  sourceCollectionEvidenceLedgerTone,
  sourceCollectionSourceFilterLabel,
  sourceCollectionCandidateEmptyStateText,
} from "../evidenceModel";
import {
  candidateSourceQualityAssessmentSummary,
  sourceCollectionResultTone,
  sourceCollectionSimpleCandidateStatusPresentation,
} from "../presentationModel";
import type { SourceCollectionStageModuleId } from "../stageProjection";
import { TeamSourceCollectionCandidatePanel } from "./TeamSourceCollectionCandidatePanel";

type Lang = "zh" | "en";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type CandidateRow = any;

type SourceCollectionCandidateCardProps = {
  candidate: CandidateRow;
  lang: Lang;
  selected: boolean;
  onSelect: (candidate: CandidateRow) => void;
};

// Memoized row: the list re-renders on every summary poll (1.5s while a run is
// active); React Query structural sharing keeps unchanged candidate identities
// stable, so unchanged rows skip the derive+render work entirely.
const SourceCollectionCandidateCard = memo(function SourceCollectionCandidateCard({
  candidate,
  lang,
  selected,
  onSelect,
}: SourceCollectionCandidateCardProps) {
  const sourceQualitySummary = candidateSourceQualityAssessmentSummary(candidate);
  const evidenceLedgerSummary = sourceCollectionEvidenceLedgerSummary(candidate);
  const provenance = sourceCollectionCandidateProvenance(candidate, lang);
  const qualityPresentation = sourceCollectionSimpleCandidateStatusPresentation(candidate, lang);
  const scoreText = sourceQualitySummary
    ? `${sourceQualitySummary.overallScore}/100`
    : (lang === "zh" ? "待审" : "review");
  return (
    <TeamCandidateCard
      tone={evidenceLedgerSummary ? sourceCollectionEvidenceLedgerTone(evidenceLedgerSummary) : sourceCollectionResultTone(candidate.qualityStatus)}
      statusLabel={qualityPresentation.label}
      statusTitle={qualityPresentation.title}
      title={
        <span title={[candidate.title || candidate.candidateId, candidate.summary || ""].filter(Boolean).join("\n")}>
          {candidate.title || candidate.candidateId}
        </span>
      }
      meta={[
        { key: "category", label: sourceCollectionSourceFilterLabel(sourceCollectionCandidateSourceCategory(candidate, lang), lang) },
        { key: "score", label: scoreText },
        ...(evidenceLedgerSummary
          ? [{ key: "evidence-ledger", label: sourceCollectionEvidenceLedgerCardLabel(evidenceLedgerSummary, lang) }]
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
      onActivate={() => onSelect(candidate)}
      activateTitle={lang === "zh" ? "点击查看来源详情" : "Open source detail"}
    />
  );
});

export type TeamSourceCollectionCandidateWorkspacePanelProps = {
  lang: Lang;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionFilteredRunCandidates: any[];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionPageItems: (stageId: SourceCollectionStageModuleId, items: any[]) => { items: any[]; start: number; end: number };
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionCandidateProjection: any;
  sourceCollectionSourceFilter: string;
  sourceCollectionDisplayedCandidateCount: number;
  sourceCollectionCountText: (loading: boolean, count: number) => string;
  sourceCollectionPrimaryDataLoading: boolean;
  sourceCollectionDataSyncText: string;
  sourceCollectionRunCandidateCount: number;
  sourceCollectionFocusedPanelId: string;
  selectedSourceCollectionStageId: string;
  sourceCollectionExpandedPanelId: string;
  setSourceCollectionExpandedPanelId: (id: string) => void;
  sourceCollectionExtractionDefaultPanelId: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionCandidateStepState: any;
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
  sourceCollectionProjectedCollectedCount: number;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  renderSourceCollectionPagination: (stageId: SourceCollectionStageModuleId, total: number) => ReactNode;
  selectedSourceCollectionCandidateId: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectSourceCollectionCandidate: (candidate: any) => void;
};

export function TeamSourceCollectionCandidateWorkspacePanel(props: TeamSourceCollectionCandidateWorkspacePanelProps) {
  const {
    lang,
    sourceCollectionFilteredRunCandidates,
    sourceCollectionPageItems,
    sourceCollectionCandidateProjection,
    sourceCollectionSourceFilter,
    sourceCollectionDisplayedCandidateCount,
    sourceCollectionCountText,
    sourceCollectionPrimaryDataLoading,
    sourceCollectionDataSyncText,
    sourceCollectionRunCandidateCount,
    sourceCollectionFocusedPanelId,
    selectedSourceCollectionStageId,
    sourceCollectionExpandedPanelId,
    setSourceCollectionExpandedPanelId,
    sourceCollectionExtractionDefaultPanelId,
    sourceCollectionCandidateStepState,
    sourceCollectionDisplayedCandidateFilterCounts,
    renderSourceCollectionFilterBar,
    sourceCollectionDisplayedCandidateCountText,
    sourceCollectionProjectedAssessedCountText,
    sourceCollectionProjectedApprovedCountText,
    sourceCollectionRunPendingScreeningCountText,
    sourceCollectionEvidenceReadyCandidateCount,
    sourceCollectionMissingEvidenceAnchorCount,
    sourceCollectionProjectedCollectedCount,
    renderSourceCollectionPagination,
    selectedSourceCollectionCandidateId,
    selectSourceCollectionCandidate,
  } = props;


    const filteredCandidates = sourceCollectionFilteredRunCandidates;
    const pagedCandidates = sourceCollectionPageItems("extraction", filteredCandidates);
    const visibleCandidates = pagedCandidates.items;
    const candidateListNeedsScrollHint = visibleCandidates.length > 4;
    // The select handler arrives as an unstable closure from the (hook-free)
    // action-handlers factory; mirror it into a ref so memoized rows get a
    // stable onSelect identity.
    const selectCandidateRef = useRef(selectSourceCollectionCandidate);
    useEffect(() => {
      selectCandidateRef.current = selectSourceCollectionCandidate;
    });
    const stableSelectCandidate = useCallback(
      (candidate: CandidateRow) => selectCandidateRef.current(candidate),
      [],
    );
    const candidateProjection = sourceCollectionCandidateProjection;
    const candidatePanelFilteredCount = sourceCollectionSourceFilter === "all"
      ? sourceCollectionDisplayedCandidateCount
      : filteredCandidates.length;
    const candidatePanelFilteredCountText = sourceCollectionCountText(sourceCollectionPrimaryDataLoading, candidatePanelFilteredCount);
    const candidatePanelRange = sourceCollectionPrimaryDataLoading
      ? sourceCollectionDataSyncText
      : visibleCandidates.length
      ? `${pagedCandidates.start}-${pagedCandidates.end}/${filteredCandidates.length}`
      : `0/${candidatePanelFilteredCount}`;
    const candidateListAwaitingRefresh = !sourceCollectionRunCandidateCount && sourceCollectionDisplayedCandidateCount > 0;
    return (
      <TeamSourceCollectionCandidatePanel
        lang={lang}
        focused={sourceCollectionFocusedPanelId === "source-collection-candidates-panel"}
        open={
          (
            selectedSourceCollectionStageId === "extraction"
            && !sourceCollectionExpandedPanelId
            && sourceCollectionExtractionDefaultPanelId === "source-collection-candidates-panel"
          )
          || sourceCollectionExpandedPanelId === "source-collection-candidates-panel"
          || sourceCollectionCandidateStepState === "active"
        }
        onToggle={(event) => {
          if (!event.currentTarget.open && sourceCollectionExpandedPanelId === "source-collection-candidates-panel") {
            setSourceCollectionExpandedPanelId("");
          }
        }}
        rangeText={candidatePanelRange}
        filterBar={renderSourceCollectionFilterBar(sourceCollectionDisplayedCandidateFilterCounts, lang === "zh" ? "提炼资料过滤" : "Extracted source filters", sourceCollectionPrimaryDataLoading)}
        stats={[
          { key: "candidate", label: lang === "zh" ? "本轮候选" : "run candidates", value: sourceCollectionDisplayedCandidateCountText },
          { key: "filtered", label: lang === "zh" ? "当前过滤" : "filtered", value: candidatePanelFilteredCountText },
          { key: "reviewed", label: lang === "zh" ? "已审查" : "reviewed", value: sourceCollectionProjectedAssessedCountText },
          { key: "approved", label: lang === "zh" ? "通过" : "approved", value: sourceCollectionProjectedApprovedCountText },
          { key: "pending", label: lang === "zh" ? "待质量审查" : "pending quality review", value: sourceCollectionRunPendingScreeningCountText },
          { key: "evidence-ready", label: "evidence_ready", value: sourceCollectionEvidenceReadyCandidateCount },
          { key: "missing-evidence-anchor", label: "missing_evidence_anchor", value: sourceCollectionMissingEvidenceAnchorCount },
        ]}
        loading={sourceCollectionPrimaryDataLoading}
        hasCandidates={Boolean(visibleCandidates.length)}
        listNeedsScrollHint={candidateListNeedsScrollHint}
        emptyMessage={sourceCollectionCandidateEmptyStateText({
          lang,
          loading: sourceCollectionPrimaryDataLoading,
          awaitingRefresh: candidateListAwaitingRefresh,
          displayedCandidateCount: sourceCollectionDisplayedCandidateCount,
          filteredCandidateCount: candidatePanelFilteredCount,
          rawRecordCount: sourceCollectionProjectedCollectedCount,
          projection: candidateProjection,
        })}
        pagination={renderSourceCollectionPagination("extraction", filteredCandidates.length)}
      >
        {visibleCandidates.map((candidate: CandidateRow) => (
          <SourceCollectionCandidateCard
            key={candidate.candidateId}
            candidate={candidate}
            lang={lang}
            selected={selectedSourceCollectionCandidateId === candidate.candidateId}
            onSelect={stableSelectCandidate}
          />
        ))}
      </TeamSourceCollectionCandidatePanel>
    );

}
