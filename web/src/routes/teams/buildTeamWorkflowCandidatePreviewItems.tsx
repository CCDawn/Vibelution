/**
 * R2-b: Team workflow candidate preview cards (quality / chunk actions).
 */
/* eslint-disable @typescript-eslint/no-explicit-any */
import { AlertTriangle, CheckCircle2, Plus, RefreshCw } from "lucide-react";

import { VNativeButton } from "../../components/vui";
import type { TeamWorkflowCandidatePreviewItem } from "../TeamWorkflowCandidatePreviewPanel";
import {
  candidateSourceQualityAssessmentSummary,
  formatTime,
  sourceCollectionResultTone,
  workflowIngestionStatusLabel,
} from "./source-collection/presentationModel";
import {
  sourceCollectionEvidenceLedgerCardLabel,
  sourceCollectionEvidenceLedgerSummary,
} from "./source-collection/evidenceModel";
import {
  candidatePaperNoteChunkPlanSummary,
  sourceCandidateHasCompletedExtraction,
} from "./teamRouteShellModel";
import { workflowStateLabel } from "./workflowPresentation";

export type BuildTeamWorkflowCandidatePreviewArgs = {
  lang: "zh" | "en";
  teamWorkflowCandidates: any[];
  selectedTeam: { teamId?: string } | null | undefined;
  selectedTeamAssessSourceQualityPending: boolean;
  selectedTeamPlanPaperNoteChunksPending: boolean;
  selectedTeamSourceQualityPending: boolean;
  assessSourceQualityMutation: any;
  planPaperNoteChunksMutation: any;
};

export function buildTeamWorkflowCandidatePreviewItems(
  args: BuildTeamWorkflowCandidatePreviewArgs,
): TeamWorkflowCandidatePreviewItem[] {
  const {
    lang,
    teamWorkflowCandidates,
    selectedTeam,
    selectedTeamAssessSourceQualityPending,
    selectedTeamPlanPaperNoteChunksPending,
    selectedTeamSourceQualityPending,
    assessSourceQualityMutation,
    planPaperNoteChunksMutation,
  } = args;

  return teamWorkflowCandidates.map((candidate) => {
    const chunkPlanSummary = candidatePaperNoteChunkPlanSummary(candidate);
    const sourceQualitySummary = candidateSourceQualityAssessmentSummary(candidate);
    const evidenceLedgerSummary = sourceCollectionEvidenceLedgerSummary(candidate);
    const canPlanPaperNoteChunks = sourceCandidateHasCompletedExtraction(candidate);
    const candidateQualityPending =
      selectedTeamAssessSourceQualityPending
      && assessSourceQualityMutation.variables?.candidateId === candidate.candidateId;
    const candidatePlanPending =
      selectedTeamPlanPaperNoteChunksPending
      && planPaperNoteChunksMutation.variables?.candidateId === candidate.candidateId;
    return {
      id: candidate.candidateId,
      tone: evidenceLedgerSummary?.missingAnchor ? "warning" : sourceCollectionResultTone(candidate.qualityStatus),
      statusLabel: workflowStateLabel(candidate.currentState, lang),
      title: candidate.title || candidate.candidateId,
      summary: candidate.summary || candidate.candidateType,
      meta: [
        { key: "type", label: candidate.candidateType },
        { key: "quality", label: candidate.qualityStatus },
        { key: "updated", label: formatTime(candidate.updatedAt, lang) },
        ...(sourceQualitySummary
          ? [{ key: "decision", label: `${lang === "zh" ? "质量判断" : "source quality"} ${workflowIngestionStatusLabel(sourceQualitySummary.decision, lang)} · ${sourceQualitySummary.overallScore}/100` }]
          : candidate.candidateType === "source_manifest"
            ? [{ key: "decision", label: lang === "zh" ? "待质量审查" : "pending quality review" }]
            : []),
        ...(chunkPlanSummary
          ? [{ key: "chunks", label: `paper_note chunks ${chunkPlanSummary.completedChunkCount}/${chunkPlanSummary.chunkCount}` }]
          : canPlanPaperNoteChunks
            ? [{ key: "chunks", label: lang === "zh" ? "可生成 paper_note 分块" : "ready for paper_note chunks" }]
            : []),
        ...(evidenceLedgerSummary
          ? [{ key: "evidence-ledger", label: sourceCollectionEvidenceLedgerCardLabel(evidenceLedgerSummary, lang) }]
          : []),
      ],
      actions: candidate.candidateType === "source_manifest" ? (
        <>
          <VNativeButton
            type="button"
            onClick={() => {
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
            title={lang === "zh" ? "由资料提炼 Agent 标记为可保留" : "Mark this source as approved by the source extraction Agent"}
          >
            <CheckCircle2 size={13} />
            {candidateQualityPending && assessSourceQualityMutation.variables?.decision === "approved"
              ? (lang === "zh" ? "筛选中" : "Assessing")
              : (lang === "zh" ? "通过复核" : "Approve source")}
          </VNativeButton>
          <VNativeButton
            type="button"
            onClick={() => {
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
            title={lang === "zh" ? "退回资料寻找 Agent 补资料" : "Return this source to the source finder for repair"}
          >
            <AlertTriangle size={13} />
            {candidateQualityPending && assessSourceQualityMutation.variables?.decision === "needs_revision"
              ? (lang === "zh" ? "退回中" : "Returning")
              : (lang === "zh" ? "退回补资料" : "Needs repair")}
          </VNativeButton>
          <VNativeButton
            type="button"
            onClick={() => {
              if (!selectedTeam?.teamId || !canPlanPaperNoteChunks || planPaperNoteChunksMutation.isPending) {
                return;
              }
              planPaperNoteChunksMutation.mutate({
                teamId: selectedTeam.teamId,
                candidateId: candidate.candidateId,
              });
            }}
            disabled={!selectedTeam?.teamId || !canPlanPaperNoteChunks || planPaperNoteChunksMutation.isPending}
            title={
              canPlanPaperNoteChunks
                ? (lang === "zh" ? "生成或重建 paper_note 分块计划" : "Generate or rebuild the paper_note chunk plan")
                : (lang === "zh" ? "需要先完成 source extraction" : "Complete source extraction first")
            }
          >
            {chunkPlanSummary ? <RefreshCw size={13} /> : <Plus size={13} />}
            {candidatePlanPending
              ? (lang === "zh" ? "规划中" : "Planning")
              : chunkPlanSummary
                ? (lang === "zh" ? "重建分块计划" : "Rebuild chunk plan")
                : (lang === "zh" ? "生成分块计划" : "Generate chunk plan")}
          </VNativeButton>
        </>
      ) : undefined,
    };
  });
}
