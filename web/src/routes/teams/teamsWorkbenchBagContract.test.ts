/**
 * Structural contracts against the bag-drop class of bugs that crashed the workbench:
 * - foundation destructures SC layer fields but forgets to return them
 * - research surface bag rebuilt via allow-list drops experiment/loop drafts
 * - shell expects flat fields that never leave foundation
 */
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const foundationSource = readFileSync(new URL("./useTeamsWorkbenchFoundation.tsx", import.meta.url), "utf8");
const shellSource = readFileSync(new URL("./useTeamsWorkbenchShellPhase.tsx", import.meta.url), "utf8");
const researchBagSource = readFileSync(new URL("./buildTeamsWorkbenchResearchSurfacesFromBag.ts", import.meta.url), "utf8");
const scLayerSource = readFileSync(new URL("./useTeamsWorkbenchScLayer.ts", import.meta.url), "utf8");

/** Critical flat fields shell / research panels require from the foundation bag. */
const CRITICAL_BAG_FIELDS = [
  "searchParams",
  "setSearchParams",
  "experimentBaselineArtifactDraft",
  "setExperimentBaselineArtifactDraft",
  "experimentSmokeResultDraft",
  "setExperimentSmokeResultDraft",
  "experimentFullRunResultDraft",
  "setExperimentFullRunResultDraft",
  "experimentKnowledgeIngestionDraft",
  "setExperimentKnowledgeIngestionDraft",
  "researchLoopCreateDraft",
  "setResearchLoopCreateDraft",
  "researchLoopEvidenceDraft",
  "setResearchLoopEvidenceDraft",
  "researchLoopDecisionDraft",
  "setResearchLoopDecisionDraft",
  "createExperimentPlanFromWorkspace",
  "createResearchLoopFromWorkspace",
  "renderSourceCollectionStandalonePage",
  "sourceCollectionDisplayState",
] as const;

function foundationReturnBody(source: string): string {
  const marker = "\n  return {";
  const start = source.lastIndexOf(marker);
  expect(start).toBeGreaterThan(0);
  return source.slice(start);
}

describe("teams workbench bag wiring contracts", () => {
  it("foundation returns SC layer via spread (not destructure-only locals)", () => {
    const ret = foundationReturnBody(foundationSource);
    expect(ret).toContain("...scLayer");
    expect(scLayerSource).toContain("renderSourceCollectionStandalonePage");
    expect(scLayerSource).toContain("sourceCollectionDisplayState");
  });

  it("foundation returns critical shell/panel bag fields", () => {
    const ret = foundationReturnBody(foundationSource);
    for (const field of CRITICAL_BAG_FIELDS) {
      const inReturn =
        new RegExp(`^\\s{4}${field}\\s*[,:]`, "m").test(ret)
        || (ret.includes("...scLayer") && scLayerSource.includes(field));
      // drafts live on foundation body return, not only scLayer
      const inFoundationBody = foundationSource.includes(field);
      expect(inReturn || (inFoundationBody && new RegExp(`^\\s{4}${field}\\s*[,:]`, "m").test(ret)), field).toBe(true);
    }
  });

  it("research surface bag builder does not allow-list strip d.* fields", () => {
    // Regression: explicit d.foo: d.foo maps dropped experiment drafts → artifactPath crash.
    expect(researchBagSource).toMatch(/createTeamsWorkbenchResearchSurfaces\(\s*d\s*\)/);
    expect(researchBagSource).not.toMatch(/experimentBaselineArtifactDraft:\s*d\.experimentBaselineArtifactDraft/);
    const dFieldPicks = researchBagSource.match(/\bd\.[A-Za-z_]/g) ?? [];
    expect(dFieldPicks.length).toBeLessThan(5);
  });

  it("shell consumes foundation bag for standalone SC and searchParams", () => {
    expect(shellSource).toContain("renderSourceCollectionStandalonePage");
    expect(shellSource).toContain("searchParams");
    expect(shellSource).toMatch(/buildTeamsWorkbenchResearchSurfacesFromBag\(\s*\{\s*\.\.\.d/);
  });
});
