import { describe, expect, it } from "vitest";

import {
  buildCanonicalWorkflowSearch,
  canonicalHref,
  resolveLegacyResearchLocation,
} from "./researchLegacyRouteResolver";

describe("researchLegacyRouteResolver", () => {
  it("maps /research/flow-canvas to workflow panel=agents", () => {
    const result = resolveLegacyResearchLocation({
      pathname: "/research/flow-canvas",
      search: "?team=research-team",
    });
    expect(result.pathname).toBe("/teams");
    expect(result.searchParams.get("researchView")).toBe("workflow");
    expect(result.searchParams.get("panel")).toBe("agents");
    expect(result.wasCanonical).toBe(false);
  });

  it("maps stage views to nodes", () => {
    const kc = resolveLegacyResearchLocation({
      pathname: "/teams",
      search: "?team=t1&researchView=knowledge_collection",
    });
    expect(kc.searchParams.get("node")).toBe("source_finding");

    const ex = resolveLegacyResearchLocation({
      pathname: "/teams",
      search: "?researchView=experiment",
    });
    expect(ex.searchParams.get("node")).toBe("hypothesis_design");
  });

  it("maps collectionStage aliases", () => {
    const result = resolveLegacyResearchLocation({
      pathname: "/teams",
      search: "?collectionStage=extract",
    });
    // extract not in map as exact key — extraction is
    const extraction = resolveLegacyResearchLocation({
      pathname: "/teams",
      search: "?collectionStage=extraction",
    });
    expect(extraction.searchParams.get("node")).toBe("source_extraction");
    expect(result.searchParams.get("researchView")).toBe("workflow");
  });

  it("keeps workflow canonical", () => {
    const result = resolveLegacyResearchLocation({
      pathname: "/teams",
      search: "?researchView=workflow&runId=run-1&node=smoke_gate",
    });
    expect(result.wasCanonical).toBe(true);
    expect(result.searchParams.get("runId")).toBe("run-1");
    expect(result.searchParams.get("node")).toBe("smoke_gate");
  });

  it("builds canonical search string", () => {
    const href = canonicalHref({
      pathname: "/teams",
      searchParams: new URLSearchParams(
        buildCanonicalWorkflowSearch({ teamId: "t", runId: "r", node: "source_finding" }).replace(/^\?/, ""),
      ),
      wasCanonical: true,
      mappedFrom: "test",
    });
    expect(href).toContain("researchView=workflow");
    expect(href).toContain("node=source_finding");
  });
});
