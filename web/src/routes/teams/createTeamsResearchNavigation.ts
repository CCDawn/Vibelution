/**
 * Research workspace / shell mode / team-pick URL navigation helpers.
 * Phase R2-h extract from useTeamsWorkbenchModel (behavior-conserving).
 */
import type { Dispatch, SetStateAction } from "react";
import type { SetURLSearchParams } from "react-router-dom";

import type { Team } from "../../api/types";
import {
  researchWorkspaceAnchorId,
  type ResearchWorkspaceView,
} from "./researchWorkspaceModel";
import { isResearchWorkflowTeam } from "./teamKindModel";
import type { TeamShellMode } from "./teamShellModel";

export type CreateTeamsResearchNavigationOptions = {
  searchParams: URLSearchParams;
  setSearchParams: SetURLSearchParams;
  effectiveTeamId: string;
  teamShellMode: TeamShellMode;
  researchWorkflowTeamSelected: boolean;
  researchWorkspaceView: ResearchWorkspaceView | string;
  setTeamShellMode: Dispatch<SetStateAction<TeamShellMode>>;
  setResearchWorkspaceView: Dispatch<SetStateAction<ResearchWorkspaceView>>;
  setSelectedTeamId: Dispatch<SetStateAction<string>>;
  setSelectedNodeId: Dispatch<SetStateAction<string>>;
};

export function createTeamsResearchNavigation(options: CreateTeamsResearchNavigationOptions) {
  const {
    searchParams,
    setSearchParams,
    effectiveTeamId,
    teamShellMode,
    researchWorkflowTeamSelected,
    researchWorkspaceView,
    setTeamShellMode,
    setResearchWorkspaceView,
    setSelectedTeamId,
    setSelectedNodeId,
  } = options;

  function selectResearchWorkspaceView(view: ResearchWorkspaceView) {
    setResearchWorkspaceView(view);
    // Keep URL in sync so stageStandalone / deep links / refresh match React state.
    const nextParams = new URLSearchParams(searchParams);
    if (effectiveTeamId) {
      nextParams.set("team", effectiveTeamId);
    }
    nextParams.set("researchView", view);
    if (view === "canvas") {
      setTeamShellMode("canvas");
      nextParams.set("teamMode", "canvas");
    } else {
      // Stage destinations (experiment / iteration / overview / KC) live on board shell.
      if (teamShellMode !== "board") {
        setTeamShellMode("board");
      }
      nextParams.set("teamMode", "board");
    }
    setSearchParams(nextParams, { replace: true });
    if (view === "canvas") {
      window.requestAnimationFrame(() => {
        document.getElementById(researchWorkspaceAnchorId(view))?.scrollIntoView({
          behavior: "smooth",
          block: "start",
        });
      });
    }
  }

  function selectTeamRecord(team: Team) {
    setSelectedTeamId(team.teamId);
    setSelectedNodeId("");
    if (isResearchWorkflowTeam(team)) {
      setResearchWorkspaceView(teamShellMode === "canvas" ? "canvas" : "overview");
    }
    const nextParams = new URLSearchParams();
    nextParams.set("team", team.teamId);
    nextParams.set("teamMode", teamShellMode);
    if (isResearchWorkflowTeam(team)) {
      nextParams.set("researchView", teamShellMode === "canvas" ? "canvas" : "overview");
    }
    setSearchParams(nextParams);
  }

  function selectTeamShellMode(mode: TeamShellMode) {
    setTeamShellMode(mode);
    const nextParams = new URLSearchParams(searchParams);
    nextParams.set("teamMode", mode);
    if (mode === "canvas") {
      if (researchWorkflowTeamSelected) {
        setResearchWorkspaceView("canvas");
        nextParams.set("researchView", "canvas");
      }
    } else {
      if (researchWorkspaceView === "canvas") {
        setResearchWorkspaceView("overview");
      }
      if (nextParams.get("researchView") === "canvas") {
        nextParams.set("researchView", "overview");
      }
    }
    setSearchParams(nextParams, { replace: true });
  }

  return {
    selectResearchWorkspaceView,
    selectTeamRecord,
    selectTeamShellMode,
  };
}
