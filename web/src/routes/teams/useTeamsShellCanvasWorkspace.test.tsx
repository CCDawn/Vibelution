/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import type { Team } from "../../api/types";
import {
  useTeamsShellCanvasWorkspace,
  type TeamsShellCanvasWorkspaceApi,
  type UseTeamsShellCanvasWorkspaceInput,
} from "./useTeamsShellCanvasWorkspace";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const challengeCupTeamId = "research-team";
const knowledgeExpansionTeamId = "knowledge-expansion-team";

function team(teamId: string, teamKind: string): Team {
  return {
    teamId,
    name: teamId,
    description: "",
    purpose: "",
    status: "active",
    teamKind,
    teamCategory: "research",
    teamSource: teamKind === "research" ? "research_organization" : "knowledge_expansion",
    members: [],
    memberCount: 0,
    canvasPath: "",
    createdAt: "",
    updatedAt: "",
    canvas: { path: "", nodeCount: 0, edgeCount: 0 },
  };
}

describe("useTeamsShellCanvasWorkspace team selection sync", () => {
  let root: Root | null = null;
  let host: HTMLDivElement | null = null;
  let workspace: TeamsShellCanvasWorkspaceApi | null = null;

  function Probe(props: UseTeamsShellCanvasWorkspaceInput) {
    workspace = useTeamsShellCanvasWorkspace(props);
    return null;
  }

  afterEach(() => {
    if (root) {
      act(() => root?.unmount());
    }
    host?.remove();
    root = null;
    host = null;
    workspace = null;
  });

  function renderWorkspace(input: UseTeamsShellCanvasWorkspaceInput) {
    if (!root) {
      host = document.createElement("div");
      document.body.append(host);
      root = createRoot(host);
    }
    act(() => root?.render(<Probe {...input} />));
  }

  function input(requestedVisibleTeamId: string): UseTeamsShellCanvasWorkspaceInput {
    const visibleTeams = [team(challengeCupTeamId, "research"), team(knowledgeExpansionTeamId, "knowledge_expansion")];
    return {
      requestedResearchWorkspaceView: "workflow",
      requestedTeamShellMode: "board",
      requestedVisibleTeamId,
      requestedVisibleAgentTeamId: "",
      visibleTeamIds: new Set(visibleTeams.map(({ teamId }) => teamId)),
      visibleTeams,
      fallbackVisibleTeamId: challengeCupTeamId,
    };
  }

  it("keeps the new local selection while the old URL request is still in flight", () => {
    const oldRoute = input(challengeCupTeamId);
    renderWorkspace(oldRoute);
    expect(workspace?.selectedTeamId).toBe(challengeCupTeamId);

    // selectTeamRecord updates local state before React Router commits the new URL.
    act(() => workspace?.setSelectedTeamId(knowledgeExpansionTeamId));
    expect(workspace?.selectedTeamId).toBe(knowledgeExpansionTeamId);

    renderWorkspace(input(knowledgeExpansionTeamId));
    expect(workspace?.selectedTeamId).toBe(knowledgeExpansionTeamId);

    // Browser back/forward and external deep links remain authoritative after the route changes.
    renderWorkspace(oldRoute);
    expect(workspace?.selectedTeamId).toBe(challengeCupTeamId);
    renderWorkspace(input(knowledgeExpansionTeamId));
    expect(workspace?.selectedTeamId).toBe(knowledgeExpansionTeamId);
  });

  it("falls back to the visible default team when a route has no valid team", () => {
    renderWorkspace(input(""));
    expect(workspace?.selectedTeamId).toBe(challengeCupTeamId);
  });
});
