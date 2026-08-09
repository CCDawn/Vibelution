import { describe, expect, it } from "vitest";

import {
  researchCanvasRoute,
  researchSourceCollectionRoute,
  researchWorkspaceStageRoute,
  teamWorkspaceRoute,
} from "../researchWorkspaceModel";

const TEAM = "research-team";

describe("researchWorkflowUrlMatrix", () => {
  it.each([
    ["team home", teamWorkspaceRoute(TEAM), "researchView=workflow"],
    ["agents", researchCanvasRoute(TEAM), "panel=agents"],
    ["knowledge", researchSourceCollectionRoute(TEAM), "node=source_finding"],
    ["experiment", researchWorkspaceStageRoute(TEAM, "experiment"), "node=hypothesis_design"],
    ["iteration", researchWorkspaceStageRoute(TEAM, "iteration"), "node=controlled_run"],
  ])("emits one canonical URL for %s", (_name, href, expected) => {
    expect(href).toContain("/teams?");
    expect(href).toContain("teamId=research-team");
    expect(href).toContain(expected);
    expect(href).not.toMatch(/[?&]team=/);
    expect(href).not.toContain("team_id=");
  });
});
