import type { ComponentProps, ReactNode } from "react";

import { TeamSourceCollectionPhaseCloseGatePanel } from "../TeamSourceCollectionPhaseCloseGatePanel";
import { TeamWorkflowCandidatePreviewPanel } from "../TeamWorkflowCandidatePreviewPanel";
import type { TeamWorkflowCandidatePreviewItem } from "../TeamWorkflowCandidatePreviewPanel";
import {
  TeamWorkflowCandidateGraphStatusPanel,
  TeamWorkflowCoordinationStatusPanel,
  TeamWorkflowKnowledgeIngestionStatusPanel,
  TeamWorkflowPaperNoteChunkStatusPanel,
  TeamWorkflowSourceQualityStatusPanel,
} from "../TeamWorkflowStatusPanels";
import {
  SOURCE_COLLECTION_RESULT_PAGE_SIZE,
  workflowIngestionStatusLabel,
} from "./source-collection/presentationModel";
import {
  workflowCoordinationChannelLabel,
  workflowCoordinationStatusLabel,
  workflowStateLabel,
} from "./workflowPresentation";
import { TeamsSourceCollectionPanel } from "./TeamsSourceCollectionPanel";

type Lang = "zh" | "en";

type TeamsSourceCollectionPanelProps = ComponentProps<typeof TeamsSourceCollectionPanel>;
type PhaseCloseGateProps = ComponentProps<typeof TeamSourceCollectionPhaseCloseGatePanel>;
type CoordinationStatus = ComponentProps<typeof TeamWorkflowCoordinationStatusPanel>["status"];
type IngestionStatus = ComponentProps<typeof TeamWorkflowKnowledgeIngestionStatusPanel>["status"];
type GraphStatus = ComponentProps<typeof TeamWorkflowCandidateGraphStatusPanel>["graph"];
type GraphLayout = ComponentProps<typeof TeamWorkflowCandidateGraphStatusPanel>["layout"];
type SourceQualityStatus = ComponentProps<typeof TeamWorkflowSourceQualityStatusPanel>["status"];
type PaperNoteChunkStatus = ComponentProps<typeof TeamWorkflowPaperNoteChunkStatusPanel>["status"];

export type TeamResearchWorkflowStageModulesProps = {
  lang: Lang;
  visibility: {
    sourceCollection: boolean;
    coordination: boolean;
    ingestion: boolean;
    graph: boolean;
    candidates: boolean;
  };
  sourceCollection: {
    summary: TeamsSourceCollectionPanelProps["summary"];
    statusLabel: string;
    statusClassName: string;
    draft: TeamsSourceCollectionPanelProps["draft"];
    modeFields: ReactNode;
    canStart: boolean;
    startPending: boolean;
    selectedRunId: string;
    runs: TeamsSourceCollectionPanelProps["runs"];
    stats: TeamsSourceCollectionPanelProps["stats"];
    assignments: TeamsSourceCollectionPanelProps["assignments"];
    assignmentEmptyMessage: TeamsSourceCollectionPanelProps["assignmentEmptyMessage"];
    queries: TeamsSourceCollectionPanelProps["queries"];
    phaseCloseGate: PhaseCloseGateProps["gate"];
    phaseCloseGateLoading: boolean;
    onOpenStage: PhaseCloseGateProps["onOpenStage"];
    storageActions: ReactNode;
    plan: TeamsSourceCollectionPanelProps["plan"];
    manualWriteback: ReactNode;
    boundaryItems: TeamsSourceCollectionPanelProps["boundaryItems"];
    errorMessages: TeamsSourceCollectionPanelProps["errorMessages"];
    result: TeamsSourceCollectionPanelProps["result"];
    onDraftChange: TeamsSourceCollectionPanelProps["onDraftChange"];
    onStart: () => void;
    onRunChange: TeamsSourceCollectionPanelProps["onRunChange"];
    onAssignmentSelect: TeamsSourceCollectionPanelProps["onAssignmentSelect"];
  };
  coordination: {
    status: CoordinationStatus;
    loading: boolean;
    errorMessages: string[];
  };
  ingestion: {
    status: IngestionStatus;
    loading: boolean;
    errorMessages: string[];
  };
  graph: {
    graph: GraphStatus;
    layout: GraphLayout;
    loading: boolean;
    errorMessages: string[];
    actionLabel: string;
    actionDisabled: boolean;
    actionTitle?: string;
    onAction: () => void;
  };
  candidates: {
    sourceQualityStatus: SourceQualityStatus;
    sourceQualityLoading: boolean;
    sourceQualityErrors: string[];
    paperNoteChunkStatus: PaperNoteChunkStatus;
    paperNoteChunkLoading: boolean;
    paperNoteChunkErrors: string[];
    previewItems: TeamWorkflowCandidatePreviewItem[];
    canOpenLibrary: boolean;
    reviewDisabled: boolean;
    reviewTitle: string;
    candidateCount: number;
    onOpenLibrary: () => void;
    onOpenReview: () => void;
  };
};

/**
 * Stage-specific research workflow modules (source collection / coordination /
 * ingestion / graph / candidates). Mounted once under TeamResearchWorkflowPanelHost.
 */
export function TeamResearchWorkflowStageModules({
  lang,
  visibility,
  sourceCollection,
  coordination,
  ingestion,
  graph,
  candidates,
}: TeamResearchWorkflowStageModulesProps) {
  return (
    <>
      {visibility.sourceCollection ? (
        <TeamsSourceCollectionPanel
          lang={lang}
          title={lang === "zh" ? "资料搜索执行" : "Source collection"}
          summary={sourceCollection.summary}
          statusLabel={sourceCollection.statusLabel || (lang === "zh" ? "未启动" : "not started")}
          statusClassName={sourceCollection.statusClassName}
          draft={sourceCollection.draft}
          modeFields={sourceCollection.modeFields}
          canStart={sourceCollection.canStart}
          startPending={sourceCollection.startPending}
          selectedRunId={sourceCollection.selectedRunId}
          runs={sourceCollection.runs}
          stats={sourceCollection.stats}
          assignments={sourceCollection.assignments}
          assignmentEmptyMessage={sourceCollection.assignmentEmptyMessage}
          queries={sourceCollection.queries}
          phaseCloseGate={(
            <TeamSourceCollectionPhaseCloseGatePanel
              lang={lang}
              selectedRunId={sourceCollection.selectedRunId}
              gate={sourceCollection.phaseCloseGate}
              loading={sourceCollection.phaseCloseGateLoading}
              onOpenStage={sourceCollection.onOpenStage}
            />
          )}
          storageActions={sourceCollection.storageActions}
          plan={sourceCollection.plan}
          manualWriteback={sourceCollection.manualWriteback}
          boundaryItems={sourceCollection.boundaryItems}
          errorMessages={sourceCollection.errorMessages}
          result={sourceCollection.result}
          onDraftChange={sourceCollection.onDraftChange}
          onStart={sourceCollection.onStart}
          onRunChange={sourceCollection.onRunChange}
          onAssignmentSelect={sourceCollection.onAssignmentSelect}
        />
      ) : null}
      {visibility.coordination ? (
        <TeamWorkflowCoordinationStatusPanel
          lang={lang}
          status={coordination.status}
          loading={coordination.loading}
          errorMessages={coordination.errorMessages}
          statusLabel={(value) => workflowCoordinationStatusLabel(value, lang)}
          channelLabel={(value) => workflowCoordinationChannelLabel(value, lang)}
          stateLabel={(value) => workflowStateLabel(value, lang)}
        />
      ) : null}
      {visibility.ingestion ? (
        <TeamWorkflowKnowledgeIngestionStatusPanel
          lang={lang}
          status={ingestion.status}
          loading={ingestion.loading}
          errorMessages={ingestion.errorMessages}
          statusLabel={(value) => workflowIngestionStatusLabel(value, lang)}
        />
      ) : null}
      {visibility.graph ? (
        <TeamWorkflowCandidateGraphStatusPanel
          lang={lang}
          graph={graph.graph}
          layout={graph.layout}
          loading={graph.loading}
          errorMessages={graph.errorMessages}
          actionLabel={graph.actionLabel}
          actionDisabled={graph.actionDisabled}
          actionTitle={graph.actionTitle ?? ""}
          stateLabel={(value) => workflowStateLabel(value, lang)}
          onAction={graph.onAction}
        />
      ) : null}
      {visibility.candidates ? (
        <>
          <TeamWorkflowSourceQualityStatusPanel
            lang={lang}
            status={candidates.sourceQualityStatus}
            loading={candidates.sourceQualityLoading}
            errorMessages={candidates.sourceQualityErrors}
            statusLabel={(value) => workflowIngestionStatusLabel(value, lang)}
          />
          <TeamWorkflowPaperNoteChunkStatusPanel
            lang={lang}
            status={candidates.paperNoteChunkStatus}
            loading={candidates.paperNoteChunkLoading}
            errorMessages={candidates.paperNoteChunkErrors}
            statusLabel={(value) => workflowIngestionStatusLabel(value, lang)}
          />
          <TeamWorkflowCandidatePreviewPanel
            lang={lang}
            items={candidates.previewItems}
            canOpenLibrary={candidates.canOpenLibrary}
            reviewDisabled={candidates.reviewDisabled}
            reviewTitle={candidates.reviewTitle}
            listNeedsScrollHint={candidates.candidateCount > SOURCE_COLLECTION_RESULT_PAGE_SIZE}
            emptyMessage={
              lang === "zh"
                ? "候选仓库还没有资料、笔记或机制候选。"
                : "No sources, notes, or mechanism candidates yet."
            }
            onOpenLibrary={candidates.onOpenLibrary}
            onOpenReview={candidates.onOpenReview}
          />
        </>
      ) : null}
    </>
  );
}
