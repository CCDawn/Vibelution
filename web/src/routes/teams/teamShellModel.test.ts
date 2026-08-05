import { describe, expect, it } from "vitest";

import {
  parseTeamShellMode,
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
});
