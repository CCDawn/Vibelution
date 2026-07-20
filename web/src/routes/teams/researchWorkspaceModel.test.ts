import { describe, expect, it } from "vitest";

import { RESEARCH_TEAM_ID } from "../TeamsRoute.canvasData";
import {
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
    expect(parseResearchWorkspaceView("not-a-view")).toBeNull();
  });

  it("builds stable Teams deep-link routes", () => {
    expect(teamWorkspaceRoute(RESEARCH_TEAM_ID)).toContain(`team=${encodeURIComponent(RESEARCH_TEAM_ID)}`);
    expect(researchSourceCollectionRoute(RESEARCH_TEAM_ID)).toContain("researchView=knowledge_collection");
    expect(researchWorkspaceStageRoute(RESEARCH_TEAM_ID, "iteration")).toContain("researchView=iteration");
    expect(researchCanvasRoute(RESEARCH_TEAM_ID)).toContain("researchView=canvas");
  });

  it("labels workspace views for zh and en", () => {
    expect(researchWorkspaceViewLabel("overview", "zh")).toContain("总览");
    expect(researchWorkspaceViewLabel("overview", "en").toLowerCase()).toContain("overview");
  });
});
