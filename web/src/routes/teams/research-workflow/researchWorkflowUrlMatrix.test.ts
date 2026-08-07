/**
 * Task 10: disposition-table URL matrix — pure resolution evidence (no browser).
 */
import { describe, expect, it } from "vitest";

import {
  researchCanvasRoute,
  researchSourceCollectionRoute,
  researchWorkspaceStageRoute,
  teamWorkspaceRoute,
} from "../researchWorkspaceModel";
import { canonicalHref, resolveLegacyResearchLocation } from "./researchLegacyRouteResolver";

const TEAM = "research-team";

describe("researchWorkflowUrlMatrix (disposition)", () => {
  const cases: Array<{ name: string; pathname: string; search: string; expectContains: string[] }> = [
    { name: "/research", pathname: "/research", search: "", expectContains: ["researchView=workflow"] },
    {
      name: "/research/flow-canvas",
      pathname: "/research/flow-canvas",
      search: `?team=${TEAM}`,
      expectContains: ["researchView=workflow", "panel=agents"],
    },
    {
      name: "overview",
      pathname: "/teams",
      search: `?team=${TEAM}&researchView=overview`,
      expectContains: ["researchView=workflow"],
    },
    {
      name: "canvas",
      pathname: "/teams",
      search: `?team=${TEAM}&researchView=canvas`,
      expectContains: ["researchView=workflow", "panel=agents"],
    },
    {
      name: "knowledge_collection",
      pathname: "/teams",
      search: `?team=${TEAM}&researchView=knowledge_collection`,
      expectContains: ["node=source_finding"],
    },
    {
      name: "experiment",
      pathname: "/teams",
      search: `?team=${TEAM}&researchView=experiment`,
      expectContains: ["node=hypothesis_design"],
    },
    {
      name: "iteration",
      pathname: "/teams",
      search: `?team=${TEAM}&researchView=iteration`,
      expectContains: ["node=controlled_run"],
    },
    {
      name: "coordination",
      pathname: "/teams",
      search: `?team=${TEAM}&researchView=coordination`,
      expectContains: ["panel=team"],
    },
    {
      name: "collectionStage=extraction",
      pathname: "/teams",
      search: `?team=${TEAM}&collectionStage=extraction`,
      expectContains: ["node=source_extraction"],
    },
  ];

  for (const item of cases) {
    it(`resolves ${item.name} to one canonical workflow URL`, () => {
      const resolved = resolveLegacyResearchLocation({
        pathname: item.pathname,
        search: item.search,
        teamId: TEAM,
      });
      const href = canonicalHref(resolved);
      expect(href.startsWith("/teams")).toBe(true);
      expect(resolved.searchParams.get("researchView")).toBe("workflow");
      for (const part of item.expectContains) {
        expect(href).toContain(part);
      }
    });
  }

  it("internal builders only emit workflow canonical links", () => {
    expect(teamWorkspaceRoute(TEAM)).toContain("researchView=workflow");
    expect(researchCanvasRoute(TEAM)).toContain("panel=agents");
    expect(researchSourceCollectionRoute(TEAM)).toContain("node=source_finding");
    expect(researchWorkspaceStageRoute(TEAM, "experiment")).toContain("node=hypothesis_design");
    expect(researchWorkspaceStageRoute(TEAM, "iteration")).toContain("node=controlled_run");
  });
});
