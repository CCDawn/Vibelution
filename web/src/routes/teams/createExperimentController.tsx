/**
 * Clarity P5/F4 — Experiment domain controller.
 * Owns refresh + standalone/embedded experiment-iteration page composition.
 * TeamsRoute / primary surface renderers pass deps; do not inline stage chrome.
 */
import type { ReactNode } from "react";

import { ExperimentStageComposer } from "./ExperimentStageComposer";
import type { ExperimentPlanRecord, ExperimentPlanningStatusPayload } from "./experimentLoopModel";
import type { ResearchStageUnlock } from "./researchPrimaryActionModel";
import type { ResearchStageWorkspaceView, ResearchWorkspaceView } from "./researchWorkspaceModel";

export type ExperimentControllerContext = {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  [key: string]: any;
};

export function createExperimentController(ctx: ExperimentControllerContext) {
  const {
    lang,
    selectedTeam,
    linkedChatRoomId,
    syncTeamChatRoomMutation,
    activeTeamMemberCount,
    selectedTeamSyncPending,
    researchStageRoundStatusQuery,
    experimentPlanningStatusQuery,
    experimentPlanningStatus,
    researchStageUnlock,
    selectResearchWorkspaceView,
    createExperimentPlanMutation,
    materializeEngineeringProxyHypothesisMutation,
    completeScientificHypothesisFromDesignMutation,
    reviewExperimentHypothesisMutation,
    createExperimentHypothesisRevisionMutation,
    freezeExperimentDesignMutation,
    registerExperimentBaselineArtifactMutation,
    runExperimentSmokeMutation,
    registerExperimentSmokeResultMutation,
    registerExperimentFullRunResultMutation,
    requestExperimentKnowledgeIngestionMutation,
    createResearchLoopMutation,
    recordResearchLoopEvidenceMutation,
    recordResearchLoopDecisionMutation,
    materializeResearchLoopIterationDesignMutation,
    researchLoopTemplatesQuery,
    researchLoopStatusQuery,
    experimentMethodCatalogQuery,
    renderExperimentPlanningLedgerPanel,
    renderResearchLoopPanel,
  } = ctx;

  function refreshStageWorkspace() {
    createExperimentPlanMutation?.reset?.();
    materializeEngineeringProxyHypothesisMutation?.reset?.();
    completeScientificHypothesisFromDesignMutation?.reset?.();
    reviewExperimentHypothesisMutation?.reset?.();
    createExperimentHypothesisRevisionMutation?.reset?.();
    freezeExperimentDesignMutation?.reset?.();
    registerExperimentBaselineArtifactMutation?.reset?.();
    runExperimentSmokeMutation?.reset?.();
    registerExperimentSmokeResultMutation?.reset?.();
    registerExperimentFullRunResultMutation?.reset?.();
    requestExperimentKnowledgeIngestionMutation?.reset?.();
    createResearchLoopMutation?.reset?.();
    recordResearchLoopEvidenceMutation?.reset?.();
    recordResearchLoopDecisionMutation?.reset?.();
    materializeResearchLoopIterationDesignMutation?.reset?.();
    void Promise.all([
      researchStageRoundStatusQuery?.refetch?.(),
      experimentPlanningStatusQuery?.refetch?.(),
      experimentMethodCatalogQuery?.refetch?.(),
      researchLoopTemplatesQuery?.refetch?.(),
      researchLoopStatusQuery?.refetch?.(),
    ]);
  }

  function renderStandalonePage(
    stageView: Exclude<ResearchStageWorkspaceView, "knowledge_collection">,
    options?: { embeddedInBoard?: boolean },
  ): ReactNode {
    const unlock: ResearchStageUnlock = researchStageUnlock || {
      knowledge_collection: true,
      experiment: true,
      iteration: true,
    };
    const body = stageView === "experiment"
      ? renderExperimentPlanningLedgerPanel()
      : renderResearchLoopPanel(
        (experimentPlanningStatus as ExperimentPlanningStatusPayload | null | undefined)?.activePlan as ExperimentPlanRecord | null ?? null,
        "iteration",
      );

    return (
      <ExperimentStageComposer
        lang={lang}
        stageView={stageView}
        unlock={unlock}
        onSelectStage={(view: ResearchWorkspaceView) => selectResearchWorkspaceView(view)}
        onOverview={() => selectResearchWorkspaceView("overview")}
        teamId={selectedTeam?.teamId}
        linkedChatRoomId={linkedChatRoomId || undefined}
        onSyncChat={
          selectedTeam?.teamId
            ? () => syncTeamChatRoomMutation.mutate(selectedTeam.teamId)
            : undefined
        }
        chatSyncPending={selectedTeamSyncPending}
        chatSyncDisabled={!selectedTeam || activeTeamMemberCount === 0}
        onRefresh={refreshStageWorkspace}
        refreshDisabled={
          Boolean(researchStageRoundStatusQuery?.isFetching)
          || Boolean(experimentPlanningStatusQuery?.isFetching)
        }
        experimentPlanningStatus={experimentPlanningStatus}
        statusLoading={!experimentPlanningStatus && Boolean(experimentPlanningStatusQuery?.isPending)}
        body={body}
        embeddedInBoard={options?.embeddedInBoard ?? false}
      />
    );
  }

  return {
    refreshStageWorkspace,
    renderStandalonePage,
  };
}
