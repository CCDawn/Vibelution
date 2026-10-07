import { describe, expect, it } from "vitest";

import {
  parseTeamShellMode,
  shouldShowResearchWorkflowPanel,
  teamShellModeFromResearchView,
  teamShellModeLabel,
} from "./teamShellModel";

describe("teamShellModel", () => {
  it("parses board and canvas aliases", () => {
    expect(parseTeamShellMode("board")).toBe("board");
    expect(parseTeamShellMode("kanban")).toBe("board");
    expect(parseTeamShellMode("canvas")).toBe("canvas");
    expect(parseTeamShellMode("graph")).toBe("canvas");
    expect(parseTeamShellMode("nope")).toBeNull();
  });

  it("maps research view to shell mode", () => {
    expect(teamShellModeFromResearchView("canvas")).toBe("canvas");
    // End-user home (overview) uses org canvas + flow strip.
    expect(teamShellModeFromResearchView("overview")).toBe("canvas");
    expect(teamShellModeFromResearchView("experiment")).toBe("board");
    expect(teamShellModeFromResearchView("iteration")).toBe("board");
  });

  it("labels modes in zh/en", () => {
    expect(teamShellModeLabel("board", "zh")).toContain("看板");
    expect(teamShellModeLabel("canvas", "en")).toBe("Canvas");
  });

  it("hides the research workflow panel for a development team", () => {
    expect(shouldShowResearchWorkflowPanel({
      aiSearchScopeTeamSelected: false,
      researchWorkflowTeamSelected: false,
      researchCanvasVisible: true,
      researchWorkspaceView: "overview",
      processWorkflowView: false,
    })).toBe(false);
  });

  it("keeps research stage modules for a research team outside the process workspace", () => {
    expect(shouldShowResearchWorkflowPanel({
      aiSearchScopeTeamSelected: false,
      researchWorkflowTeamSelected: true,
      researchCanvasVisible: false,
      researchWorkspaceView: "coordination",
      processWorkflowView: false,
    })).toBe(true);
    expect(shouldShowResearchWorkflowPanel({
      aiSearchScopeTeamSelected: false,
      researchWorkflowTeamSelected: true,
      researchCanvasVisible: false,
      researchWorkspaceView: "workflow",
      processWorkflowView: true,
    })).toBe(false);
  });
});
