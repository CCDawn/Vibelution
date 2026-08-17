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
  challengeCupResearchTeamSelected?: boolean;
};

export type TeamWorkflowResourceDemand = {
  processCanvasHome: boolean;
  sourceCollectionNeedsCandidateList: boolean;
  teamWorkflowOrchestrationEnabled: boolean;
  teamWorkflowCandidateListEnabled: boolean;
  teamWorkflowGraphEnabled: boolean;
  teamWorkflowKnowledgeIngestionEnabled: boolean;
  teamWorkflowSourceQualityEnabled: boolean;
  researchStageRoundStatusEnabled: boolean;
};

/** Process-flow canvas is the Challenge Cup home; it must not wait on legacy orchestration. */
export function isResearchProcessCanvasHome(input: {
  researchWorkspaceView: ResearchWorkspaceView | string;
  challengeCupResearchTeamSelected?: boolean;
}): boolean {
  return input.researchWorkspaceView === "workflow"
    || (Boolean(input.challengeCupResearchTeamSelected) && input.researchWorkspaceView === "overview");
}

export function resolveTeamWorkflowResourceDemand(
  input: TeamWorkflowResourceDemandInput,
): TeamWorkflowResourceDemand {
  const {
    effectiveTeamId,
    researchWorkflowTeamSelected,
    researchWorkspaceView,
    sourceCollectionWorkspaceSelected,
    selectedSourceCollectionStageId,
    challengeCupResearchTeamSelected,
  } = input;

  const processCanvasHome = isResearchProcessCanvasHome({
    researchWorkspaceView,
    challengeCupResearchTeamSelected,
  });
  const sourceCollectionNeedsCandidateList = sourceCollectionWorkspaceSelected;
  const teamWorkflowOrchestrationEnabled = Boolean(
    effectiveTeamId && researchWorkflowTeamSelected && !processCanvasHome,
  );
  const teamWorkflowCandidateListEnabled = Boolean(
    effectiveTeamId
    && researchWorkflowTeamSelected
    && !processCanvasHome
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
    && !sourceCollectionWorkspaceSelected
    && !processCanvasHome,
  );

  return {
    processCanvasHome,
    sourceCollectionNeedsCandidateList,
    teamWorkflowOrchestrationEnabled,
    teamWorkflowCandidateListEnabled,
    teamWorkflowGraphEnabled,
    teamWorkflowKnowledgeIngestionEnabled,
    teamWorkflowSourceQualityEnabled,
    researchStageRoundStatusEnabled,
  };
}
