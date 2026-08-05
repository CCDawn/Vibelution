/**
 * Research stage launch + primary/advance action handlers.
 * Phase R2-i extract from useTeamsWorkbenchModel (behavior-conserving).
 *
 * `getSelectedTeamStartResearchStagePending` / `getResearchStageCanLaunch` are getters
 * because SC composition both consumes launch handlers and produces those flags.
 */
import type { NavigateFunction } from "react-router-dom";
import type { Dispatch, SetStateAction } from "react";

import type { Team } from "../../api/types";
import {
  researchAdvanceSuccessMessage,
  type ResearchPrimaryAction,
} from "./researchPrimaryActionModel";
import { researchWorkspaceStageRoute, type ResearchWorkspaceView } from "./researchWorkspaceModel";
import type { SourceCollectionDraft } from "./source-collection/presentationModel";
import type { ResearchStageType } from "./source-collection/stageProjection";

export type ResearchStageProjectAgentTasks = {
  startTask: (
    taskKind: "experiment_design" | "iteration_decision",
    options: { returnTo: string; returnLabel: string },
  ) => Promise<{ chatRoute?: string | null }>;
};

export type CreateResearchStageLaunchHandlersOptions = {
  lang: "zh" | "en";
  selectedTeam: Team | null;
  sourceCollectionDraft: SourceCollectionDraft;
  /** Late-bound: produced by SC composition after handlers are created. */
  getSelectedTeamStartResearchStagePending: () => boolean;
  getResearchStageCanLaunch: () => boolean;
  challengeCupResearchTeamSelected: boolean;
  researchStageProjectAgentTasks: ResearchStageProjectAgentTasks;
  startResearchStageRoundMutation: {
    mutateAsync: (payload: {
      teamId: string;
      stageType: ResearchStageType;
      mode: "continue_or_start" | "new_round";
      draft: SourceCollectionDraft;
    }) => Promise<unknown>;
  };
  navigate: NavigateFunction;
  selectResearchWorkspaceView: (view: ResearchWorkspaceView) => void;
  setResearchAdvanceNotice: Dispatch<SetStateAction<string>>;
};

export function createResearchStageLaunchHandlers(options: CreateResearchStageLaunchHandlersOptions) {
  const {
    lang,
    selectedTeam,
    sourceCollectionDraft,
    getSelectedTeamStartResearchStagePending,
    getResearchStageCanLaunch,
    challengeCupResearchTeamSelected,
    researchStageProjectAgentTasks,
    startResearchStageRoundMutation,
    navigate,
    selectResearchWorkspaceView,
    setResearchAdvanceNotice,
  } = options;

  async function launchResearchStage(
    stageType: ResearchStageType,
    mode: "continue_or_start" | "new_round" = "continue_or_start",
  ) {
    if (!selectedTeam?.teamId || getSelectedTeamStartResearchStagePending()) {
      return;
    }
    if (stageType === "knowledge_collection" && !getResearchStageCanLaunch()) {
      return;
    }
    try {
      await startResearchStageRoundMutation.mutateAsync({
        teamId: selectedTeam.teamId,
        stageType,
        mode,
        draft: sourceCollectionDraft,
      });
      if (stageType !== "knowledge_collection" && challengeCupResearchTeamSelected) {
        const taskKind = stageType === "experiment" ? "experiment_design" : "iteration_decision";
        const agentTask = await researchStageProjectAgentTasks.startTask(taskKind, {
          returnTo: researchWorkspaceStageRoute(selectedTeam.teamId, stageType),
          returnLabel: stageType === "experiment" ? "返回实验设计" : "返回执行与迭代",
        });
        if (agentTask.chatRoute) {
          navigate(agentTask.chatRoute);
        }
      }
    } catch {
      // Both mutations expose their typed error state to the stage panel.
    }
  }

  async function handleResearchPrimaryAction(action: ResearchPrimaryAction) {
    if (action.blocked || !selectedTeam?.teamId) {
      return;
    }
    selectResearchWorkspaceView(action.navigateView);
    if (action.launchStageType) {
      await launchResearchStage(action.launchStageType, action.launchMode || "continue_or_start");
    }
  }

  async function handleResearchAdvanceAction(action: ResearchPrimaryAction) {
    if (action.blocked || !selectedTeam?.teamId) {
      return;
    }
    await handleResearchPrimaryAction(action);
    setResearchAdvanceNotice(researchAdvanceSuccessMessage(action, lang));
    window.setTimeout(() => {
      setResearchAdvanceNotice((current) => (
        current === researchAdvanceSuccessMessage(action, lang) ? "" : current
      ));
    }, 5000);
  }

  return {
    launchResearchStage,
    handleResearchPrimaryAction,
    handleResearchAdvanceAction,
  };
}
