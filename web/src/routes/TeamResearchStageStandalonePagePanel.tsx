/**
 * Research stage standalone page — thin adapter over ExperimentStageComposer.
 */
import type { ReactNode } from "react";

import type { Team } from "../api/types";
import {
  type ExperimentPlanRecord,
  type ExperimentPlanningStatusPayload,
} from "./teams/experimentLoopModel";
import type {
  ResearchStagePhaseStatus,
  ResearchStageType,
} from "./teams/source-collection/stageProjection";
import type { ResearchStageUnlock } from "./teams/researchPrimaryActionModel";
import type { ResearchStageWorkspaceView, ResearchWorkspaceView } from "./teams/researchWorkspaceModel";
import { ExperimentStageComposer } from "./teams/ExperimentStageComposer";

type Lang = "zh" | "en";
type StageView = Exclude<ResearchStageWorkspaceView, "knowledge_collection">;

export type TeamResearchStageStandalonePagePanelProps = {
  stageView: StageView;
  lang: Lang;
  researchStagePhases: ResearchStagePhaseStatus[];
  experimentPlanningStatus: ExperimentPlanningStatusPayload | null | undefined;
  experimentPlanningStatusQuery: { isPending: boolean; isFetching: boolean };
  selectedTeam: Team | null | undefined;
  selectedTeamStartResearchStagePending: boolean;
  linkedChatRoomId: string;
  syncTeamChatRoomMutation: { mutate: (teamId: string) => void };
  activeTeamMemberCount: number;
  selectedTeamSyncPending: boolean;
  researchStageRoundStatusQuery: { isFetching: boolean; refetch: () => unknown };
  refreshStageWorkspace: () => void;
  renderResearchStageAgentPanel: (stageType: ResearchStageType, variant?: "compact" | "page") => ReactNode;
  launchResearchStage: (stageType: ResearchStageType, mode?: "continue_or_start" | "new_round") => void;
  selectedTeamStartResearchStageError: Error | null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectedTeamStartResearchStageResult: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  researchStageStartFeedbackText: (payload: any, lang: Lang, stageLabel?: string) => string;
  renderExperimentPlanningLedgerPanel: () => ReactNode;
  renderResearchLoopPanel: (activePlan: ExperimentPlanRecord | null, variant?: "experiment" | "iteration") => ReactNode;
  researchStageUnlock?: ResearchStageUnlock;
  onSelectResearchStage?: (view: ResearchWorkspaceView) => void;
  onBackToOverview?: () => void;
  embeddedInBoard?: boolean;
};

export function TeamResearchStageStandalonePagePanel(props: TeamResearchStageStandalonePagePanelProps) {
  const {
    stageView,
    lang,
    experimentPlanningStatus,
    experimentPlanningStatusQuery,
    selectedTeam,
    linkedChatRoomId,
    syncTeamChatRoomMutation,
    activeTeamMemberCount,
    selectedTeamSyncPending,
    researchStageRoundStatusQuery,
    refreshStageWorkspace,
    renderExperimentPlanningLedgerPanel,
    renderResearchLoopPanel,
    researchStageUnlock,
    onSelectResearchStage,
    onBackToOverview,
    embeddedInBoard = false,
  } = props;

  const unlock = researchStageUnlock || {
    knowledge_collection: true,
    experiment: true,
    iteration: true,
  };

  const body = stageView === "experiment"
    ? renderExperimentPlanningLedgerPanel()
    : renderResearchLoopPanel(experimentPlanningStatus?.activePlan ?? null, "iteration");

  return (
    <ExperimentStageComposer
      lang={lang}
      stageView={stageView}
      unlock={unlock}
      onSelectStage={(view) => onSelectResearchStage?.(view)}
      onOverview={() => onBackToOverview?.()}
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
        researchStageRoundStatusQuery.isFetching || experimentPlanningStatusQuery.isFetching
      }
      experimentPlanningStatus={experimentPlanningStatus}
      statusLoading={!experimentPlanningStatus && experimentPlanningStatusQuery.isPending}
      body={body}
      embeddedInBoard={embeddedInBoard}
    />
  );
}
