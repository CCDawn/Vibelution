/**
 * Source-collection controls / side-rail workspace body.
 * Wave 8M: extracted from TeamsRoute.tsx for domain componentization.
 */
import type { ReactNode, Ref } from "react";

import type { Team } from "../api/types";
import { TeamSourceCollectionControlsPanel } from "./TeamSourceCollectionControlsPanel";
import { TeamSourceCollectionRunSettingsPanel } from "./TeamSourceCollectionRunSettingsPanel";
import { TeamSourceCollectionFindingDetailsPanel } from "./TeamSourceCollectionFindingDetailsPanel";
import {
  sourceCollectionStatusLabel,
} from "./teams/source-collection/presentationModel";
import { sourceCollectionRunLabel } from "./teams/source-collection/runModel";
import type { SourceCollectionStageModuleId } from "./teams/source-collection/stageProjection";
import shellStyles from "./TeamsRoute.styles";
import workflowStyles from "./TeamsRoute.workflow.styles";

const styles = { ...shellStyles, ...workflowStyles } as Record<string, string>;

type Lang = "zh" | "en";

export type TeamSourceCollectionControlsWorkspacePanelProps = {
  lang: Lang;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionControlPanelRef: Ref<any>;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionStageModules: any[];
  selectedSourceCollectionStageId: SourceCollectionStageModuleId | string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectedSourceCollectionRun: any;
  sourceCollectionStageFocusLabel: string;
  workflowIngestionTone: (value: string) => string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionRunStatus: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  renderSourceCollectionSelectedSourcePanel: () => ReactNode;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionDraft: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  renderSourceCollectionModeFields: () => ReactNode;
  sourceCollectionCanStart: boolean;
  selectedTeamStartSourceCollectionPending: boolean;
  setSourceCollectionDraft: (updater: (current: any) => any) => void;
  selectedTeam: Team | null | undefined;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  startSourceCollectionRunMutation: any;
  selectedSourceCollectionRunEffectiveId: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionFindingRunOptions: any[];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionFindingAssignments: any[];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionFindingQueries: any[];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  renderSourceCollectionStorageActions: () => ReactNode;
  setSelectedSourceCollectionRunId: (runId: string) => void;
  setSourceCollectionOutputDraft: (updater: (current: any) => any) => void;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  renderSourceCollectionManualWritebackPanel: () => ReactNode;
  sourceCollectionDisplayedCandidateCountText: string;
  sourceCollectionProjectedAssessedCountText: string;
  sourceCollectionProjectedApprovedCountText: string;
  sourceCollectionRunPendingScreeningCountText: string;
  candidateGraphNodeCount: number | string;
  candidateGraphEdgeCount: number | string;
  sourceCollectionPrecheckCandidateCount: number | string;
  knowledgePendingReviewCount: number | string;
  formalKnowledgeItemCount: number | string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectedTeamKnowledgeCollectionIngestResult: any;
  selectedTeamKnowledgeCollectionIngestError: Error | null;
  selectedTeamStartSourceCollectionError: Error | null;
  selectedTeamRecordSourceCollectionOutputError: Error | null;
  selectedTeamExecuteSourceCollectionSearchError: Error | null;
  selectedTeamStartSourceCollectionStageTaskError: Error | null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectedTeamExecuteSourceCollectionSearchResult: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectedTeamRecordSourceCollectionOutputResult: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  renderSourceCollectionStageAgents: (stageId: any) => ReactNode;
};

export function TeamSourceCollectionControlsWorkspacePanel(props: TeamSourceCollectionControlsWorkspacePanelProps) {
  const {
    lang,
    sourceCollectionControlPanelRef,
    sourceCollectionStageModules,
    selectedSourceCollectionStageId,
    selectedSourceCollectionRun,
    sourceCollectionStageFocusLabel,
    workflowIngestionTone,
    sourceCollectionRunStatus,
    renderSourceCollectionSelectedSourcePanel,
    sourceCollectionDraft,
    renderSourceCollectionModeFields,
    sourceCollectionCanStart,
    selectedTeamStartSourceCollectionPending,
    setSourceCollectionDraft,
    selectedTeam,
    startSourceCollectionRunMutation,
    selectedSourceCollectionRunEffectiveId,
    sourceCollectionFindingRunOptions,
    sourceCollectionFindingAssignments,
    sourceCollectionFindingQueries,
    renderSourceCollectionStorageActions,
    setSelectedSourceCollectionRunId,
    setSourceCollectionOutputDraft,
    renderSourceCollectionManualWritebackPanel,
    sourceCollectionDisplayedCandidateCountText,
    sourceCollectionProjectedAssessedCountText,
    sourceCollectionProjectedApprovedCountText,
    sourceCollectionRunPendingScreeningCountText,
    candidateGraphNodeCount,
    candidateGraphEdgeCount,
    sourceCollectionPrecheckCandidateCount,
    knowledgePendingReviewCount,
    formalKnowledgeItemCount,
    selectedTeamKnowledgeCollectionIngestResult,
    selectedTeamKnowledgeCollectionIngestError,
    selectedTeamStartSourceCollectionError,
    selectedTeamRecordSourceCollectionOutputError,
    selectedTeamExecuteSourceCollectionSearchError,
    selectedTeamStartSourceCollectionStageTaskError,
    selectedTeamExecuteSourceCollectionSearchResult,
    selectedTeamRecordSourceCollectionOutputResult,
    renderSourceCollectionStageAgents,
  } = props;


    const activeModule =
      sourceCollectionStageModules.find((module: any) => module.id === selectedSourceCollectionStageId)
      ?? sourceCollectionStageModules[0];
    return (
      <TeamSourceCollectionControlsPanel
        ref={sourceCollectionControlPanelRef}
        lang={lang}
        activeRunText={
          selectedSourceCollectionRun
            ? `${sourceCollectionRunLabel(selectedSourceCollectionRun.runId)} · ${sourceCollectionStageFocusLabel}`
            : lang === "zh" ? "等待启动搜集批次" : "Waiting for a collection run"
        }
        statusClassName={workflowIngestionTone(sourceCollectionRunStatus?.runStatus || selectedSourceCollectionRun?.status || "")}
        statusLabel={sourceCollectionStatusLabel(sourceCollectionRunStatus?.runStatus || selectedSourceCollectionRun?.status || "pending", lang)}
        selectedSourcePanel={renderSourceCollectionSelectedSourcePanel()}
      >
        {selectedSourceCollectionStageId === "finding" ? (
        <>
        <TeamSourceCollectionRunSettingsPanel
          lang={lang}
          draft={sourceCollectionDraft}
          modeFields={renderSourceCollectionModeFields()}
          open={!selectedSourceCollectionRun}
          canStart={sourceCollectionCanStart}
          startPending={selectedTeamStartSourceCollectionPending}
          onDraftChange={(patch) => setSourceCollectionDraft((current) => ({ ...current, ...patch }))}
          onSubmit={() => {
            if (!selectedTeam?.teamId || !sourceCollectionCanStart || selectedTeamStartSourceCollectionPending) {
              return;
            }
            startSourceCollectionRunMutation.mutate({
              teamId: selectedTeam.teamId,
              draft: sourceCollectionDraft,
            });
          }}
        />
        <TeamSourceCollectionFindingDetailsPanel
          lang={lang}
          selectedRunId={selectedSourceCollectionRunEffectiveId}
          runs={sourceCollectionFindingRunOptions}
          assignments={sourceCollectionFindingAssignments}
          queries={sourceCollectionFindingQueries}
          storageActions={renderSourceCollectionStorageActions()}
          onRunChange={setSelectedSourceCollectionRunId}
          onAssignmentSelect={(assignmentId) => setSourceCollectionOutputDraft((current) => ({ ...current, assignmentId }))}
        />
        {renderSourceCollectionManualWritebackPanel()}
        </>
        ) : null}
        {selectedSourceCollectionStageId === "extraction" ? (
          <div className={styles.workflowSourceQualityStats}>
            <span>{lang === "zh" ? "本轮候选" : "run candidates"} <strong>{sourceCollectionDisplayedCandidateCountText}</strong></span>
            <span>{lang === "zh" ? "已审查" : "reviewed"} <strong>{sourceCollectionProjectedAssessedCountText}</strong></span>
            <span>{lang === "zh" ? "通过" : "approved"} <strong>{sourceCollectionProjectedApprovedCountText}</strong></span>
            <span>{lang === "zh" ? "待 Agent 复核" : "pending agent review"} <strong>{sourceCollectionRunPendingScreeningCountText}</strong></span>
          </div>
        ) : null}
        {selectedSourceCollectionStageId === "extraction" ? renderSourceCollectionStorageActions() : null}
        {selectedSourceCollectionStageId === "relations" ? (
          <div className={styles.workflowSourceQualityStats}>
            <span>{lang === "zh" ? "节点" : "nodes"} <strong>{candidateGraphNodeCount}</strong></span>
            <span>{lang === "zh" ? "边" : "edges"} <strong>{candidateGraphEdgeCount}</strong></span>
          </div>
        ) : null}
        {selectedSourceCollectionStageId === "ingestion" ? (
          <>
            <div className={styles.workflowSourceQualityStats}>
              <span>{lang === "zh" ? "通过资料" : "approved sources"} <strong>{sourceCollectionPrecheckCandidateCount}</strong></span>
              <span>{lang === "zh" ? "待入库" : "pending"} <strong>{knowledgePendingReviewCount}</strong></span>
              <span>{lang === "zh" ? "正式知识" : "formal items"} <strong>{formalKnowledgeItemCount}</strong></span>
              <span>{lang === "zh" ? "关系节点" : "map nodes"} <strong>{candidateGraphNodeCount}</strong></span>
            </div>
            {selectedTeamKnowledgeCollectionIngestResult ? (
              <div className={styles.messageResult}>
                <strong>
                  {selectedTeamKnowledgeCollectionIngestResult.status === "completed"
                    ? (lang === "zh" ? "资料已写入团队知识库" : "Sources ingested into Team Knowledge")
                    : selectedTeamKnowledgeCollectionIngestResult.status === "agent_notified"
                      ? (lang === "zh" ? "已通知资料入库 Agent" : "Source ingestion Agent notified")
                    : selectedTeamKnowledgeCollectionIngestResult.status === "agent_wake_pending"
                      ? (lang === "zh" ? "已发送，等待唤醒 Agent" : "Sent; waiting to wake Agent")
                    : sourceCollectionStatusLabel(selectedTeamKnowledgeCollectionIngestResult.status, lang)}
                </strong>
                <span>
                  {selectedTeamKnowledgeCollectionIngestResult.status === "completed"
                    ? (lang === "zh"
                        ? `${selectedTeamKnowledgeCollectionIngestResult.summary.approvedSourceCandidateCount} 条资料通过审查，${selectedTeamKnowledgeCollectionIngestResult.summary.formalKnowledgeItemCount} 条正式知识可用于后续实验。`
                        : `${selectedTeamKnowledgeCollectionIngestResult.summary.approvedSourceCandidateCount} sources approved; ${selectedTeamKnowledgeCollectionIngestResult.summary.formalKnowledgeItemCount} formal items are ready for experiments.`)
                    : (lang === "zh"
                        ? `${selectedTeamKnowledgeCollectionIngestResult.summary.approvedSourceCandidateCount} 条资料通过审查，待入库知识包已发送给资料入库 Agent；当前正式知识 ${selectedTeamKnowledgeCollectionIngestResult.summary.formalKnowledgeItemCount} 条。`
                        : `${selectedTeamKnowledgeCollectionIngestResult.summary.approvedSourceCandidateCount} sources approved; the ingestion pack was sent to the steward Agent. Current formal items: ${selectedTeamKnowledgeCollectionIngestResult.summary.formalKnowledgeItemCount}.`)}
                </span>
              </div>
            ) : null}
            {selectedTeamKnowledgeCollectionIngestError ? (
              <div className={styles.messageError}>{selectedTeamKnowledgeCollectionIngestError.message}</div>
            ) : null}
          </>
        ) : null}
        {selectedSourceCollectionStageId === "finding" ? (
          <>
            {selectedTeamStartSourceCollectionError ? (
              <div className={styles.messageError}>{selectedTeamStartSourceCollectionError.message}</div>
            ) : null}
            {selectedTeamRecordSourceCollectionOutputError ? (
              <div className={styles.messageError}>{selectedTeamRecordSourceCollectionOutputError.message}</div>
            ) : null}
            {selectedTeamExecuteSourceCollectionSearchError ? (
              <div className={styles.messageError}>{selectedTeamExecuteSourceCollectionSearchError.message}</div>
            ) : null}
            {selectedTeamStartSourceCollectionStageTaskError ? (
              <div className={styles.messageError}>{selectedTeamStartSourceCollectionStageTaskError.message}</div>
            ) : null}
            {selectedTeamExecuteSourceCollectionSearchResult ? (
              <div className={styles.messageResult}>
                <strong>
                  {selectedTeamExecuteSourceCollectionSearchResult.accepted
                    ? (lang === "zh" ? "搜索已转后台" : "Search queued in background")
                    : (lang === "zh" ? "搜索执行已回写" : "Search execution written")}
                </strong>
                {selectedTeamExecuteSourceCollectionSearchResult.accepted ? (
                  <span>{lang === "zh" ? "页面可继续操作，结果会自动刷新。" : "You can keep working; results will refresh automatically."}</span>
                ) : (
                  <span>
                    {selectedTeamExecuteSourceCollectionSearchResult.executedQueryCount} {lang === "zh" ? "条搜索" : "queries"} / {selectedTeamExecuteSourceCollectionSearchResult.recordCount} {lang === "zh" ? "条资料记录" : "DataRecord"} / {selectedTeamExecuteSourceCollectionSearchResult.importedCount} {lang === "zh" ? "个候选" : "candidate"}{selectedTeamExecuteSourceCollectionSearchResult.skippedDuplicateCount ? ` / ${selectedTeamExecuteSourceCollectionSearchResult.skippedDuplicateCount} ${lang === "zh" ? "条重复跳过" : "duplicates skipped"}` : ""}{selectedTeamExecuteSourceCollectionSearchResult.filteredExcludedCount ? ` / ${selectedTeamExecuteSourceCollectionSearchResult.filteredExcludedCount} ${lang === "zh" ? "条无效来源已过滤" : "excluded sources filtered"}` : ""}{selectedTeamExecuteSourceCollectionSearchResult.hasMore ? ` / ${selectedTeamExecuteSourceCollectionSearchResult.remainingQueryCount ?? 0} ${lang === "zh" ? "条待继续" : "remaining"}` : ""}
                  </span>
                )}
              </div>
            ) : null}
            {selectedTeamRecordSourceCollectionOutputResult ? (
              <div className={styles.messageResult}>
                <strong>{lang === "zh" ? "已回写" : "Written"}</strong>
                <span>
                  {selectedTeamRecordSourceCollectionOutputResult.output.createdRecords.length} {lang === "zh" ? "条资料记录" : "DataRecord"} / {selectedTeamRecordSourceCollectionOutputResult.imported.length} {lang === "zh" ? "个候选" : "candidate"}
                </span>
              </div>
            ) : null}
          </>
        ) : null}
        {renderSourceCollectionStageAgents(activeModule.id)}
      </TeamSourceCollectionControlsPanel>
    );

}
