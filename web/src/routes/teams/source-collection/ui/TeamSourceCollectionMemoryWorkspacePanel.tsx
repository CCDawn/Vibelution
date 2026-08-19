/**
 * Source-collection memory / knowledge-ingestion workspace body.
 * Wave 8L: extracted from TeamsRoute.tsx for domain componentization.
 */
import type { ReactNode } from "react";

import type {
  TeamWorkflowCandidate,
  TeamWorkflowKnowledgeIngestionActionItem,
  TeamWorkflowKnowledgeIngestionStatus,
} from "../../../../api/types";
import { TeamCandidateCard } from "../../../../components/vui/product/team-management";
import {
  sourceCollectionCandidateProvenance,
  sourceCollectionCandidateSourceCategory,
  sourceCollectionSourceFilterLabel,
} from "../evidenceModel";
import type { SourceCollectionSourceFilter } from "../evidenceModel";
import {
  candidateSourceQualityAssessmentSummary,
  formatTime,
  sourceCollectionCandidateQualityState,
  sourceCollectionResultTone,
  workflowIngestionStatusLabel,
} from "../presentationModel";
import type { SourceCollectionStageModuleId } from "../stageProjection";
import { workflowStateLabel } from "../../workflowPresentation";
import { TeamSourceCollectionMemoryPanel } from "./TeamSourceCollectionMemoryPanel";
import shellStyles from "../../../TeamsRoute.styles";
import workflowStyles from "../../../TeamsRoute.workflow.styles";

const styles = { ...shellStyles, ...workflowStyles } as Record<string, string>;

type Lang = "zh" | "en";

export type TeamSourceCollectionMemoryWorkspacePanelProps = {
  lang: Lang;
  teamWorkflowKnowledgeIngestionStatus: TeamWorkflowKnowledgeIngestionStatus | null | undefined;
  sourceCollectionFilteredRunCandidates: TeamWorkflowCandidate[];
  sourceCollectionPageItems: <T>(stageId: SourceCollectionStageModuleId, items: T[]) => { items: T[]; start: number; end: number };
  teamWorkflowCandidatesById: Map<string, TeamWorkflowCandidate>;
  sourceCollectionFocusedPanelId: string;
  selectedSourceCollectionStageId: string;
  sourceCollectionExpandedPanelId: string;
  setSourceCollectionExpandedPanelId: (id: string) => void;
  sourceCollectionMemoryStepState: string | null | undefined;
  sourceCollectionCandidateFilterCounts: Record<SourceCollectionSourceFilter, number>;
  renderSourceCollectionFilterBar: (counts: Record<SourceCollectionSourceFilter, number>, label: string) => ReactNode;
  knowledgePendingReviewCount: number | string;
  formalKnowledgeItemCount: number | string;
  sourceCollectionApprovedCount: number | string;
  renderSourceCollectionPagination: (stageId: SourceCollectionStageModuleId, total: number) => ReactNode;
  workflowIngestionTone: (value: string) => string;
  teamWorkflowKnowledgeIngestionStatusQuery: { error?: unknown };
  selectedSourceCollectionCandidateId: string;
  selectSourceCollectionCandidate: (candidate: TeamWorkflowCandidate) => void;
};

export function TeamSourceCollectionMemoryWorkspacePanel(props: TeamSourceCollectionMemoryWorkspacePanelProps) {
  const {
    lang,
    teamWorkflowKnowledgeIngestionStatus,
    sourceCollectionFilteredRunCandidates,
    sourceCollectionPageItems,
    teamWorkflowCandidatesById,
    sourceCollectionFocusedPanelId,
    selectedSourceCollectionStageId,
    sourceCollectionExpandedPanelId,
    setSourceCollectionExpandedPanelId,
    sourceCollectionMemoryStepState,
    sourceCollectionCandidateFilterCounts,
    renderSourceCollectionFilterBar,
    knowledgePendingReviewCount,
    formalKnowledgeItemCount,
    sourceCollectionApprovedCount,
    renderSourceCollectionPagination,
    workflowIngestionTone,
    teamWorkflowKnowledgeIngestionStatusQuery,
    selectedSourceCollectionCandidateId,
    selectSourceCollectionCandidate,
  } = props;


    const actionItems = teamWorkflowKnowledgeIngestionStatus?.actionItems ?? [];
    const actionItemsByCandidateId = new Map<string, TeamWorkflowKnowledgeIngestionActionItem[]>();
    actionItems.forEach((item) => {
      if (!item.candidateId) {
        return;
      }
      const current = actionItemsByCandidateId.get(item.candidateId) ?? [];
      current.push(item);
      actionItemsByCandidateId.set(item.candidateId, current);
    });
    const memoryCandidates = sourceCollectionFilteredRunCandidates.filter((candidate) =>
      sourceCollectionCandidateQualityState(candidate).approved || actionItemsByCandidateId.has(candidate.candidateId),
    );
    const visibleMemoryCandidates = memoryCandidates;
    const pagedMemoryCandidates = sourceCollectionPageItems("ingestion", visibleMemoryCandidates);
    const orphanActionItems = actionItems.filter((item) => !item.candidateId || !teamWorkflowCandidatesById.has(item.candidateId));
    return (
      <TeamSourceCollectionMemoryPanel
        lang={lang}
        focused={sourceCollectionFocusedPanelId === "source-collection-memory-panel"}
        open={
          selectedSourceCollectionStageId === "ingestion"
          || sourceCollectionExpandedPanelId === "source-collection-memory-panel"
          || sourceCollectionMemoryStepState === "active"
        }
        onToggle={(event) => {
          if (!event.currentTarget.open && sourceCollectionExpandedPanelId === "source-collection-memory-panel") {
            setSourceCollectionExpandedPanelId("");
          }
        }}
        rangeText={`${pagedMemoryCandidates.start}-${pagedMemoryCandidates.end}/${visibleMemoryCandidates.length}`}
        filterBar={renderSourceCollectionFilterBar(sourceCollectionCandidateFilterCounts, lang === "zh" ? "入库资料过滤" : "Ingestion source filters")}
        stats={[
          { key: "pending", label: lang === "zh" ? "待审" : "pending", value: knowledgePendingReviewCount },
          { key: "formal", label: lang === "zh" ? "正式" : "formal", value: formalKnowledgeItemCount },
          { key: "approved", label: lang === "zh" ? "通过候选" : "approved", value: sourceCollectionApprovedCount },
          { key: "filtered", label: lang === "zh" ? "当前过滤" : "filtered", value: visibleMemoryCandidates.length },
        ]}
        hasCandidates={Boolean(visibleMemoryCandidates.length)}
        emptyMessage={lang === "zh" ? "当前过滤条件下没有入库资料。" : "No ingestion items match this filter."}
        pagination={renderSourceCollectionPagination("ingestion", visibleMemoryCandidates.length)}
        statusItems={orphanActionItems.length
          ? orphanActionItems.map((item) => (
            <span key={`${item.code}-${item.message}`} className={workflowIngestionTone(item.severity)}>
              {workflowIngestionStatusLabel(item.severity, lang)} · {item.message}
            </span>
          ))
          : null}
        error={teamWorkflowKnowledgeIngestionStatusQuery.error instanceof Error ? (
          <div className={styles.messageError}>{teamWorkflowKnowledgeIngestionStatusQuery.error.message}</div>
        ) : null}
      >
        {pagedMemoryCandidates.items.map((candidate) => {
              const provenance = sourceCollectionCandidateProvenance(candidate, lang);
              const sourceQualitySummary = candidateSourceQualityAssessmentSummary(candidate);
              const candidateActionItems = actionItemsByCandidateId.get(candidate.candidateId) ?? [];
              const selected = selectedSourceCollectionCandidateId === candidate.candidateId;
              return (
                <TeamCandidateCard
                  key={`memory-${candidate.candidateId}`}
                  tone={sourceCollectionResultTone(candidate.qualityStatus)}
                  statusLabel={
                    sourceQualitySummary
                      ? workflowIngestionStatusLabel(sourceQualitySummary.decision, lang)
                      : workflowStateLabel(candidate.currentState, lang)
                  }
                  title={candidate.title || candidate.candidateId}
                  summary={candidate.summary || candidate.candidateId}
                  meta={[
                    { key: "category", label: sourceCollectionSourceFilterLabel(sourceCollectionCandidateSourceCategory(candidate, lang), lang) },
                    ...(sourceQualitySummary
                      ? [{ key: "score", label: `${lang === "zh" ? "评分" : "score"} ${sourceQualitySummary.overallScore}/100` }]
                      : []),
                    { key: "updated", label: formatTime(candidate.updatedAt, lang) },
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
                  actions={candidateActionItems.length ? (
                    <div className={styles.workflowIngestionActions}>
                      {candidateActionItems.map((item) => (
                        <span key={`${item.code}-${item.message}`} className={workflowIngestionTone(item.severity)}>
                          {workflowIngestionStatusLabel(item.severity, lang)} · {item.message}
                        </span>
                      ))}
                    </div>
                  ) : undefined}
                />
              );
            })}
      </TeamSourceCollectionMemoryPanel>
    );

}
