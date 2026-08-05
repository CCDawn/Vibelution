/**
 * Pure gates for research workflow resource demand (candidates/graph/quality/…).
 * Extracted from useTeamsWorkbenchModel (behavior-conserving).
 */
import type { ResearchWorkspaceView } from "./researchWorkspaceModel";
import type { SourceCollectionStageModuleId } from "./source-collection/stageProjection";

export type TeamWorkflowResourceDemandInput = {
  effectiveTeamId: string;
  researchWorkflowTeamSelected: boolean;
  researchWorkspaceView: ResearchWorkspaceView | string;
  sourceCollectionWorkspaceSelected: boolean;
  selectedSourceCollectionStageId: SourceCollectionStageModuleId | string | null | undefined;
};

export type TeamWorkflowResourceDemand = {
  sourceCollectionNeedsCandidateList: boolean;
  teamWorkflowCandidateListEnabled: boolean;
  teamWorkflowGraphEnabled: boolean;
  teamWorkflowKnowledgeIngestionEnabled: boolean;
  teamWorkflowSourceQualityEnabled: boolean;
  researchStageRoundStatusEnabled: boolean;
};

export function resolveTeamWorkflowResourceDemand(
  input: TeamWorkflowResourceDemandInput,
): TeamWorkflowResourceDemand {
  const {
    effectiveTeamId,
    researchWorkflowTeamSelected,
    researchWorkspaceView,
    sourceCollectionWorkspaceSelected,
    selectedSourceCollectionStageId,
  } = input;

  const sourceCollectionNeedsCandidateList = sourceCollectionWorkspaceSelected;
  const teamWorkflowCandidateListEnabled = Boolean(
    effectiveTeamId
    && researchWorkflowTeamSelected
    && (
      researchWorkspaceView === "overview"
      || researchWorkspaceView === "candidates"
      || sourceCollectionNeedsCandidateList
    ),
  );
  const teamWorkflowGraphEnabled = Boolean(
    effectiveTeamId
    && researchWorkflowTeamSelected
    && (
      researchWorkspaceView === "graph"
      || (
        sourceCollectionWorkspaceSelected
        && (selectedSourceCollectionStageId === "relations" || selectedSourceCollectionStageId === "ingestion")
      )
    ),
  );
  const teamWorkflowKnowledgeIngestionEnabled = Boolean(
    effectiveTeamId
    && researchWorkflowTeamSelected
    && (
      researchWorkspaceView === "ingestion"
      || (sourceCollectionWorkspaceSelected && selectedSourceCollectionStageId === "ingestion")
    ),
  );
  const teamWorkflowSourceQualityEnabled = Boolean(
    effectiveTeamId
    && researchWorkflowTeamSelected
    && (
      researchWorkspaceView === "graph"
      || (
        sourceCollectionWorkspaceSelected
        && (
          selectedSourceCollectionStageId === "extraction"
          || selectedSourceCollectionStageId === "relations"
          || selectedSourceCollectionStageId === "ingestion"
        )
      )
    ),
  );
  const researchStageRoundStatusEnabled = Boolean(
    effectiveTeamId
    && researchWorkflowTeamSelected
    && !sourceCollectionWorkspaceSelected,
  );

  return {
    sourceCollectionNeedsCandidateList,
    teamWorkflowCandidateListEnabled,
    teamWorkflowGraphEnabled,
    teamWorkflowKnowledgeIngestionEnabled,
    teamWorkflowSourceQualityEnabled,
    researchStageRoundStatusEnabled,
  };
}
