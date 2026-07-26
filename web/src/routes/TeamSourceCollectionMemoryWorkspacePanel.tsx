/**
 * Source-collection memory / knowledge-ingestion workspace body.
 * Wave 8L: extracted from TeamsRoute.tsx for domain componentization.
 */
import type { ReactNode } from "react";

import { TeamCandidateCard } from "../components/vui/product/team-management";
import {
  sourceCollectionCandidateProvenance,
  sourceCollectionCandidateSourceCategory,
  sourceCollectionSourceFilterLabel,
} from "./teams/source-collection/evidenceModel";
import {
  candidateSourceQualityAssessmentSummary,
  formatTime,
  sourceCollectionCandidateQualityState,
  sourceCollectionResultTone,
  workflowIngestionStatusLabel,
} from "./teams/source-collection/presentationModel";
import type { SourceCollectionStageModuleId } from "./teams/source-collection/stageProjection";
import { workflowStateLabel } from "./teams/workflowPresentation";
import { TeamSourceCollectionMemoryPanel } from "./TeamSourceCollectionMemoryPanel";
import shellStyles from "./TeamsRoute.styles";
import workflowStyles from "./TeamsRoute.workflow.styles";

const styles = { ...shellStyles, ...workflowStyles } as Record<string, string>;

type Lang = "zh" | "en";

export type TeamSourceCollectionMemoryWorkspacePanelProps = {
  lang: Lang;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  teamWorkflowKnowledgeIngestionStatus: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionFilteredRunCandidates: any[];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionPageItems: (stageId: SourceCollectionStageModuleId, items: any[]) => { items: any[]; start: number; end: number };
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  teamWorkflowCandidatesById: Map<string, any>;
  sourceCollectionFocusedPanelId: string;
  selectedSourceCollectionStageId: string;
  sourceCollectionExpandedPanelId: string;
  setSourceCollectionExpandedPanelId: (id: string) => void;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionMemoryStepState: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionCandidateFilterCounts: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  renderSourceCollectionFilterBar: (...args: any[]) => ReactNode;
  knowledgePendingReviewCount: number | string;
  formalKnowledgeItemCount: number | string;
  sourceCollectionApprovedCount: number | string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  renderSourceCollectionPagination: (stageId: SourceCollectionStageModuleId, total: number) => ReactNode;
  workflowIngestionTone: (value: string) => string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  teamWorkflowKnowledgeIngestionStatusQuery: { error?: unknown };
  selectedSourceCollectionCandidateId: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectSourceCollectionCandidate: (candidate: any) => void;
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
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const actionItemsByCandidateId = new Map<string, any[]>();
    actionItems.forEach((item: any) => {
      if (!item.candidateId) {
        return;
      }
      const current = actionItemsByCandidateId.get(item.candidateId) ?? [];
      current.push(item);
      actionItemsByCandidateId.set(item.candidateId, current);
    });
    const memoryCandidates = sourceCollectionFilteredRunCandidates.filter((candidate: any) =>
      sourceCollectionCandidateQualityState(candidate).approved || actionItemsByCandidateId.has(candidate.candidateId),
    );
    const visibleMemoryCandidates = memoryCandidates;
    const pagedMemoryCandidates = sourceCollectionPageItems("ingestion", visibleMemoryCandidates);
    const orphanActionItems = actionItems.filter((item: any) => !item.candidateId || !teamWorkflowCandidatesById.has(item.candidateId));
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
          ? orphanActionItems.map((item: any) => (
            <span key={`${item.code}-${item.message}`} className={workflowIngestionTone(item.severity)}>
              {workflowIngestionStatusLabel(item.severity, lang)} · {item.message}
            </span>
          ))
          : null}
        error={teamWorkflowKnowledgeIngestionStatusQuery.error instanceof Error ? (
          <div className={styles.messageError}>{teamWorkflowKnowledgeIngestionStatusQuery.error.message}</div>
        ) : null}
      >
        {pagedMemoryCandidates.items.map((candidate: any) => {
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
                      {candidateActionItems.map((item: any) => (
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
