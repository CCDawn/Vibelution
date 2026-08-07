import { describe, expect, it } from "vitest";

import { RESEARCH_TEAM_ID } from "../TeamsRoute.canvasData";
import {
  challengeQuestionDetailRoute,
  parseResearchWorkspaceView,
  researchCanvasRoute,
  researchSourceCollectionRoute,
  researchWorkspaceStageRoute,
  researchWorkspaceViewLabel,
  teamWorkspaceRoute,
} from "./researchWorkspaceModel";

describe("researchWorkspaceModel", () => {
  it("maps legacy source_collection deep links onto knowledge collection", () => {
    expect(parseResearchWorkspaceView("source_collection")).toBe("knowledge_collection");
    expect(parseResearchWorkspaceView("experiment")).toBe("experiment");
    // canvas is not a separate page — maps to workflow shell.
    expect(parseResearchWorkspaceView("canvas")).toBe("workflow");
    expect(parseResearchWorkspaceView("workflow")).toBe("workflow");
    expect(parseResearchWorkspaceView("not-a-view")).toBeNull();
  });

  it("builds stable Teams deep-link routes onto workflow canvas", () => {
    const home = teamWorkspaceRoute(RESEARCH_TEAM_ID);
    expect(home).toContain(`team=${encodeURIComponent(RESEARCH_TEAM_ID)}`);
    expect(home).toContain("researchView=workflow");
    expect(home).toContain("workflowId=challenge-cup-research");
    expect(researchSourceCollectionRoute(RESEARCH_TEAM_ID)).toContain("researchView=workflow");
    expect(researchSourceCollectionRoute(RESEARCH_TEAM_ID)).toContain("node=source_finding");
    expect(researchWorkspaceStageRoute(RESEARCH_TEAM_ID, "iteration")).toContain("researchView=workflow");
    expect(researchWorkspaceStageRoute(RESEARCH_TEAM_ID, "iteration")).toContain("node=controlled_run");
    expect(researchWorkspaceStageRoute(RESEARCH_TEAM_ID, "experiment")).toContain("node=hypothesis_design");
    // canvas route opens agents panel on the same workflow shell.
    expect(researchCanvasRoute(RESEARCH_TEAM_ID)).toContain("researchView=workflow");
    expect(researchCanvasRoute(RESEARCH_TEAM_ID)).toContain("panel=agents");
  });

  it("builds an explicit challenge question route without opening the active project workspace", () => {
    const route = challengeQuestionDetailRoute(RESEARCH_TEAM_ID, "SCI-096", "stage1-sci-096-v3");

    expect(route).toContain("team=research-team");
    expect(route).toContain("challengeQuestion=SCI-096");
    expect(route).toContain("challengeRun=stage1-sci-096-v3");
    expect(route).not.toContain("researchView=knowledge_collection");
  });

  it("labels workspace views for zh and en", () => {
    expect(researchWorkspaceViewLabel("overview", "zh")).toContain("总览");
    expect(researchWorkspaceViewLabel("overview", "en").toLowerCase()).toContain("overview");
  });
});
