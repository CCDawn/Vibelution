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
    // canvas is not a separate page — maps to overview home.
    expect(parseResearchWorkspaceView("canvas")).toBe("overview");
    expect(parseResearchWorkspaceView("not-a-view")).toBeNull();
  });

  it("builds stable Teams deep-link routes", () => {
    const home = teamWorkspaceRoute(RESEARCH_TEAM_ID);
    expect(home).toContain(`team=${encodeURIComponent(RESEARCH_TEAM_ID)}`);
    // Canonical end-user home = overview + canvas (flow strip + org graph).
    expect(home).toContain("researchView=overview");
    expect(home).toContain("teamMode=canvas");
    expect(researchSourceCollectionRoute(RESEARCH_TEAM_ID)).toContain("researchView=knowledge_collection");
    expect(researchSourceCollectionRoute(RESEARCH_TEAM_ID)).toContain("teamMode=board");
    expect(researchWorkspaceStageRoute(RESEARCH_TEAM_ID, "iteration")).toContain("researchView=iteration");
    expect(researchWorkspaceStageRoute(RESEARCH_TEAM_ID, "iteration")).toContain("teamMode=board");
    // canvas route is an alias of home — not a second competing page.
    expect(researchCanvasRoute(RESEARCH_TEAM_ID)).toBe(home);
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
