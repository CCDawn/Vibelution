import { describe, expect, it } from "vitest";

import {
  buildCanonicalWorkflowSearch,
  canonicalHref,
  resolveLegacyResearchLocation,
} from "./researchLegacyRouteResolver";
import { CHALLENGE_CUP_NODE_IDS } from "../../../api/types/researchWorkflow";

describe("researchWorkflowNavigation", () => {
  it("canonical teams workflow is reachable shape", () => {
    const href = buildCanonicalWorkflowSearch({
      teamId: "research-team",
      runId: "run-1",
      node: "source_finding",
      panel: "node",
    });
    expect(href).toContain("researchView=workflow");
    expect(href).toContain("team=research-team");
    expect(href).toContain("node=source_finding");
  });

  it("maps every collectionStage alias used in disposition table", () => {
    const aliases: Array<[string, string]> = [
      ["search", "source_finding"],
      ["collection", "source_finding"],
      ["finding", "source_finding"],
      ["review", "source_extraction"],
      ["candidate", "source_extraction"],
      ["screening", "source_extraction"],
      ["extraction", "source_extraction"],
      ["graph", "evidence_relations"],
      ["relations", "evidence_relations"],
      ["ingest", "knowledge_ingestion"],
      ["memory", "knowledge_ingestion"],
      ["ingestion", "knowledge_ingestion"],
    ];
    for (const [alias, node] of aliases) {
      const resolved = resolveLegacyResearchLocation({
        pathname: "/teams",
        search: `?collectionStage=${alias}&team=t1`,
      });
      expect(resolved.searchParams.get("node"), alias).toBe(node);
      expect(resolved.searchParams.get("researchView")).toBe("workflow");
    }
  });

  it("maps stage researchViews to fixed nodes", () => {
    expect(
      resolveLegacyResearchLocation({
        pathname: "/teams",
        search: "?researchView=experiment",
      }).searchParams.get("node"),
    ).toBe("hypothesis_design");
    expect(
      resolveLegacyResearchLocation({
        pathname: "/teams",
        search: "?researchView=iteration",
      }).searchParams.get("node"),
    ).toBe("controlled_run");
  });

  it("only allows fixed challenge cup nodes in canonical search", () => {
    const bad = buildCanonicalWorkflowSearch({ node: "not-real" });
    expect(bad).not.toContain("node=not-real");
    for (const node of CHALLENGE_CUP_NODE_IDS) {
      expect(buildCanonicalWorkflowSearch({ node })).toContain(`node=${node}`);
    }
  });

  it("flow-canvas path becomes agents panel on teams", () => {
    const loc = resolveLegacyResearchLocation({
      pathname: "/research/flow-canvas",
      search: "?team=research-team",
    });
    expect(canonicalHref(loc)).toContain("/teams?");
    expect(loc.searchParams.get("panel")).toBe("agents");
    expect(loc.searchParams.get("researchView")).toBe("workflow");
  });
});
