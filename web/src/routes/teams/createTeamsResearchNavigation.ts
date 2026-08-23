/**
 * Research workspace / shell mode / team-pick URL navigation helpers.
 * Phase R2-h extract from useTeamsWorkbenchModel (behavior-conserving).
 */
import type { Dispatch, SetStateAction } from "react";
import type { SetURLSearchParams } from "react-router-dom";

import type { Team } from "../../api/types";
import {
  canonicalChallengeCupWorkspaceRoute,
  canonicalChallengeCupWorkspaceRouteForEffectiveTeam,
  isSameChallengeCupWorkspaceTeam,
  teamWorkspaceRoute,
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
    const nextParams = new URLSearchParams(searchParams);
    if (effectiveTeamId) {
      nextParams.delete("team");
      nextParams.delete("team_id");
      nextParams.set("teamId", effectiveTeamId);
    }
    // Research teams always land on the process workspace (board + workflow).
    // Non-research teams keep org-canvas home for overview/canvas.
    if (view === "overview" || view === "canvas") {
      if (researchWorkflowTeamSelected) {
        setResearchWorkspaceView("workflow");
        setTeamShellMode("board");
        const params = new URLSearchParams(
          canonicalChallengeCupWorkspaceRouteForEffectiveTeam(effectiveTeamId, searchParams).split("?")[1] || "",
        );
        setSearchParams(params, { replace: true });
        return;
      }
      setResearchWorkspaceView("overview");
      nextParams.set("researchView", "overview");
      setTeamShellMode("canvas");
      nextParams.set("teamMode", "canvas");
    } else {
      setResearchWorkspaceView(view);
      nextParams.set("researchView", view);
      if (teamShellMode !== "board") {
        setTeamShellMode("board");
      }
      nextParams.set("teamMode", "board");
    }
    setSearchParams(nextParams, { replace: true });
  }

  function selectTeamRecord(team: Team) {
    setSelectedTeamId(team.teamId);
    setSelectedNodeId("");
    if (isResearchWorkflowTeam(team)) {
      setResearchWorkspaceView("workflow");
      setTeamShellMode("board");
      const sameChallengeCupWorkspaceTeam = isSameChallengeCupWorkspaceTeam(team.teamId, searchParams);
      const route = sameChallengeCupWorkspaceTeam
        ? canonicalChallengeCupWorkspaceRoute(team.teamId, searchParams)
        : teamWorkspaceRoute(team.teamId);
      const params = new URLSearchParams(
        route.split("?")[1] || "",
      );
      setSearchParams(params, { replace: sameChallengeCupWorkspaceTeam });
      return;
    }
    setResearchWorkspaceView("overview");
    setTeamShellMode("canvas");
    const query = teamWorkspaceRoute(team.teamId).split("?")[1] || "";
    setSearchParams(new URLSearchParams(query));
  }

  function selectTeamShellMode(mode: TeamShellMode) {
    setTeamShellMode(mode);
    const nextParams = new URLSearchParams(searchParams);
    nextParams.set("teamMode", mode);
    if (mode === "canvas") {
      if (researchWorkflowTeamSelected) {
        setResearchWorkspaceView("workflow");
        setTeamShellMode("board");
        const params = new URLSearchParams(
          canonicalChallengeCupWorkspaceRouteForEffectiveTeam(effectiveTeamId, searchParams).split("?")[1] || "",
        );
        setSearchParams(params, { replace: true });
        return;
      }
    } else if (
      researchWorkspaceView === "canvas"
      || researchWorkspaceView === "overview"
    ) {
      // Board without a stage target still keeps overview params; stage pages set their own view.
      setResearchWorkspaceView("overview");
      nextParams.set("researchView", "overview");
    }
    setSearchParams(nextParams, { replace: true });
  }

  return {
    selectResearchWorkspaceView,
    selectTeamRecord,
    selectTeamShellMode,
  };
}
