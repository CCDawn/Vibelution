/** @vitest-environment happy-dom */
import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it } from "vitest";

import type { Team } from "../../api/types";
import type {
  UseTeamsShellCanvasWorkspaceInput,
} from "./useTeamsShellCanvasWorkspace";
import {
  useTeamsShellCanvasWorkspace,
  type TeamsShellCanvasWorkspaceApi,
} from "./useTeamsShellCanvasWorkspace";

const routeShellSource = readFileSync(resolve(import.meta.dirname, "TeamsRouteWorkbench.tsx"), "utf8");
const routeModelSource = readFileSync(resolve(import.meta.dirname, "useTeamsWorkbenchModel.tsx"), "utf8") + "\n" + readFileSync(resolve(import.meta.dirname, "useTeamsWorkbenchFoundation.tsx"), "utf8") + "\n" + readFileSync(resolve(import.meta.dirname, "useTeamsWorkbenchShellPhase.tsx"), "utf8");
const routeSource = `${routeShellSource}\n${routeModelSource}`;
const hookSource = readFileSync(resolve(import.meta.dirname, "useTeamsShellCanvasWorkspace.ts"), "utf8");

describe("useTeamsShellCanvasWorkspace Phase 3 contract", () => {
  it("TeamsRoute consumes shell + canvas projection hooks and no longer declares shell/canvas useState", () => {
    expect(routeSource).toContain("useTeamsShellCanvasWorkspace({");
    expect(routeSource).toContain("useTeamsCanvasProjection({");
    expect(routeSource).not.toContain('const [selectedTeamId, setSelectedTeamId] = useState("")');
    expect(routeSource).not.toContain("const [teamShellMode, setTeamShellMode] = useState");
    expect(routeSource).not.toContain("const [nodePositionDrafts, setNodePositionDrafts] = useState");
    expect(routeSource).not.toContain("const teamCanvasQuery = useQuery({");
    expect(routeSource).not.toContain("const durableCanvas = canvasFromTeamOrFallback");
  });

  it("hook module owns shell state, canvas query gate, and display projection", () => {
    expect(hookSource).toContain("export function useTeamsShellCanvasWorkspace");
    expect(hookSource).toContain("export function useTeamsCanvasProjection");
    expect(hookSource).toContain("resolveTeamCanvasQueryEnabled");
    expect(hookSource).toContain("autoLayoutResearchCanvasNodes");
    expect(hookSource).toContain("canvasFromTeamOrFallback");
    expect(hookSource).toContain("setNodePositionDrafts");
  });
});

function makeTeam(teamId: string, teamKind: Team["teamKind"], teamSource: string): Team {
  return {
    teamId,
    name: teamId,
    description: "",
    purpose: "",
    status: "active",
    teamKind,
    teamCategory: teamKind === "research" ? "research" : "general",
    teamSource,
    members: [],
    memberCount: 0,
    canvasPath: "",
    createdAt: "",
    updatedAt: "",
    canvas: { path: "", nodeCount: 0, edgeCount: 0 },
  } as Team;
}

const USER_TEAM_ID = "user-created-team";
const RESEARCH_TEAM_ID = "challenge-cup-research-team";
const userTeam = makeTeam(USER_TEAM_ID, "custom", "manual");
const researchTeam = makeTeam(RESEARCH_TEAM_ID, "research", "research_organization");

function baseInput(overrides: Partial<UseTeamsShellCanvasWorkspaceInput> = {}): UseTeamsShellCanvasWorkspaceInput {
  return {
    requestedResearchWorkspaceView: null,
    requestedTeamShellMode: null,
    requestedVisibleTeamId: "",
    requestedVisibleAgentTeamId: "",
    visibleTeamIds: new Set([USER_TEAM_ID, RESEARCH_TEAM_ID]),
    visibleTeams: [userTeam, researchTeam],
    fallbackVisibleTeamId: RESEARCH_TEAM_ID,
    ...overrides,
  };
}

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let capturedApi: TeamsShellCanvasWorkspaceApi | null = null;

function Probe({ input }: { input: UseTeamsShellCanvasWorkspaceInput }) {
  capturedApi = useTeamsShellCanvasWorkspace(input);
  return null;
}

let host: HTMLElement | null = null;
let root: Root | null = null;

function mountHook(input: UseTeamsShellCanvasWorkspaceInput): TeamsShellCanvasWorkspaceApi {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  act(() => {
    root?.render(createElement(Probe, { input }));
  });
  if (!capturedApi) {
    throw new Error("hook api not captured");
  }
  return capturedApi;
}

function rerenderHook(input: UseTeamsShellCanvasWorkspaceInput): TeamsShellCanvasWorkspaceApi {
  act(() => {
    root?.render(createElement(Probe, { input }));
  });
  if (!capturedApi) {
    throw new Error("hook api not captured");
  }
  return capturedApi;
}

describe("useTeamsShellCanvasWorkspace non-research shell ownership", () => {
  afterEach(() => {
    if (root) {
      act(() => root?.unmount());
    }
    host?.remove();
    host = null;
    root = null;
    capturedApi = null;
  });

  it("seeds the canvas shell in the initial state when the requested team is non-research", () => {
    const api = mountHook(baseInput({ requestedVisibleTeamId: USER_TEAM_ID }));
    expect(api.teamShellMode).toBe("canvas");
    // The researchView param is not part of the user-team state system.
    expect(api.researchWorkspaceView).toBe("workflow");
  });

  it("never forces a selected non-research team back to board for workflow/overview views", () => {
    for (const requestedResearchWorkspaceView of ["workflow", "overview"] as const) {
      const api = mountHook(baseInput({
        requestedVisibleTeamId: USER_TEAM_ID,
        requestedResearchWorkspaceView,
        requestedTeamShellMode: "canvas",
      }));
      expect(api.teamShellMode).toBe("canvas");
    }
  });

  it("flips a stranded board shell back to canvas once the team resolves as non-research", () => {
    // Team catalog still loading: legacy research bootstrap forces the board shell.
    const api = mountHook(baseInput({
      requestedVisibleTeamId: USER_TEAM_ID,
      requestedResearchWorkspaceView: "workflow",
      visibleTeamIds: new Set(),
      visibleTeams: [],
    }));
    expect(api.teamShellMode).toBe("board");

    // Catalog entry lands: the user team must land on the org canvas, not board.
    const next = rerenderHook(baseInput({
      requestedVisibleTeamId: USER_TEAM_ID,
      requestedResearchWorkspaceView: "workflow",
    }));
    expect(next.teamShellMode).toBe("canvas");
  });

  it("recovers an explicit canvas URL after catalog loading forced the board shell", () => {
    const api = mountHook(baseInput({
      requestedVisibleTeamId: USER_TEAM_ID,
      requestedResearchWorkspaceView: "workflow",
      requestedTeamShellMode: "canvas",
      visibleTeamIds: new Set(),
      visibleTeams: [],
    }));
    expect(api.teamShellMode).toBe("board");

    const next = rerenderHook(baseInput({
      requestedVisibleTeamId: USER_TEAM_ID,
      requestedResearchWorkspaceView: "workflow",
      requestedTeamShellMode: "canvas",
    }));
    expect(next.teamShellMode).toBe("canvas");
  });

  it("keeps an explicit teamMode=board for a non-research team", () => {
    const api = mountHook(baseInput({
      requestedVisibleTeamId: USER_TEAM_ID,
      requestedTeamShellMode: "board",
    }));
    expect(api.teamShellMode).toBe("board");
  });

  it("ignores researchView changes while a non-research team is selected", () => {
    const api = mountHook(baseInput({ requestedVisibleTeamId: USER_TEAM_ID }));
    expect(api.researchWorkspaceView).toBe("workflow");
    const next = rerenderHook(baseInput({
      requestedVisibleTeamId: USER_TEAM_ID,
      requestedResearchWorkspaceView: "overview",
    }));
    expect(next.researchWorkspaceView).toBe("workflow");
    expect(next.teamShellMode).toBe("canvas");
  });
});

describe("useTeamsShellCanvasWorkspace research team behavior (regression)", () => {
  afterEach(() => {
    if (root) {
      act(() => root?.unmount());
    }
    host?.remove();
    host = null;
    root = null;
    capturedApi = null;
  });

  it("keeps research teams on the board shell for workflow/overview and forces board back", () => {
    for (const requestedResearchWorkspaceView of ["workflow", "overview"] as const) {
      const api = mountHook(baseInput({
        requestedVisibleTeamId: RESEARCH_TEAM_ID,
        requestedResearchWorkspaceView,
      }));
      expect(api.teamShellMode).toBe("board");
      act(() => {
        api.setTeamShellMode("canvas");
      });
      expect(api.teamShellMode).toBe("board");
    }
  });

  it("keeps the research bootstrap on board while the team catalog is unresolved", () => {
    const api = mountHook(baseInput({
      requestedResearchWorkspaceView: "workflow",
      visibleTeamIds: new Set<string>(),
      visibleTeams: [],
      fallbackVisibleTeamId: "",
    }));
    act(() => {
      api.setTeamShellMode("canvas");
    });
    expect(api.teamShellMode).toBe("board");
  });

  it("still forces research teams back to board even when the URL requests teamMode=canvas", () => {
    const api = mountHook(baseInput({
      requestedVisibleTeamId: RESEARCH_TEAM_ID,
      requestedResearchWorkspaceView: "workflow",
      requestedTeamShellMode: "canvas",
    }));
    expect(api.teamShellMode).toBe("board");
  });
});
