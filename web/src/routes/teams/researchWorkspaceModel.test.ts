import { describe, expect, it } from "vitest";

import { RESEARCH_TEAM_ID } from "../TeamsRoute.canvasData";
import { parseResearchProcessLocation } from "./research-workflow/researchProcessLocation";
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
  it("accepts only current workspace views and rejects legacy aliases", () => {
    expect(parseResearchWorkspaceView("source_collection")).toBeNull();
    expect(parseResearchWorkspaceView("experiment")).toBeNull();
    expect(parseResearchWorkspaceView("canvas")).toBeNull();
    expect(parseResearchWorkspaceView("workflow")).toBe("workflow");
    expect(parseResearchWorkspaceView("overview")).toBe("overview");
    expect(parseResearchWorkspaceView("not-a-view")).toBeNull();
  });

  it("builds stable Teams deep-link routes onto workflow canvas", () => {
    const home = teamWorkspaceRoute(RESEARCH_TEAM_ID);
    expect(home).toContain(`teamId=${encodeURIComponent(RESEARCH_TEAM_ID)}`);
    expect(home).not.toMatch(/[?&]team=/);
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

  it("builds a challenge question route the workflow parser can round-trip", () => {
    const route = challengeQuestionDetailRoute(RESEARCH_TEAM_ID, "SCI-096", "stage1-sci-096-v3");

    expect(route).toContain("teamId=research-team");
    expect(route).toContain("researchView=workflow");
    expect(route).toContain("workflowId=challenge-cup-research");
    expect(route).not.toContain("challengeQuestion=");
    expect(route).not.toContain("challengeRun=");

    // Contract: the helper's URL must reopen the same question panel.
    const parsed = parseResearchProcessLocation(new URLSearchParams(route.split("?")[1]));
    expect(parsed.panel).toBe("question");
    expect(parsed.questionId).toBe("SCI-096");
    expect(parsed.runId).toBe("stage1-sci-096-v3");
  });

  it("labels workspace views for zh and en", () => {
    expect(researchWorkspaceViewLabel("overview", "zh")).toContain("总览");
    expect(researchWorkspaceViewLabel("overview", "en").toLowerCase()).toContain("overview");
  });
});
