import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const surfaceSource = readFileSync(new URL("./ResearchOverviewSurface.tsx", import.meta.url), "utf8");
const primarySource = readFileSync(new URL("./ResearchPrimaryActionBar.tsx", import.meta.url), "utf8");
const routeSource = readFileSync(new URL("../TeamsRoute.tsx", import.meta.url), "utf8");

describe("ResearchOverviewSurface product contract", () => {
  it("keeps single-CTA → stages → advanced order in JSX body", () => {
    const hero = surfaceSource.indexOf('data-testid="research-overview-hero"');
    const stages = surfaceSource.indexOf('data-testid="research-overview-stages"');
    // Secondary is the last composition slot (not the import line).
    const secondarySlot = surfaceSource.indexOf("{advanced ? (");
    expect(hero).toBeGreaterThan(-1);
    expect(stages).toBeGreaterThan(hero);
    expect(secondarySlot).toBeGreaterThan(stages);
    expect(surfaceSource.slice(secondarySlot)).toContain("ResearchOverviewSecondary");
    expect(surfaceSource).toContain("阶段看板");
  });

  it("wires production overview through ResearchOverviewSurface only", () => {
    expect(routeSource).toContain("ResearchOverviewSurface");
    expect(routeSource).toContain("renderResearchOverviewSurface");
    expect(routeSource).toContain("ResearchBoardKanban");
    // Must not re-embed a second hero CTA bar under the workflow panel.
    expect(routeSource).not.toMatch(/showResearchOverview\s*\?\s*\(\s*<div[^>]*research-overview-hero/);
  });

  it("primary bar is a single solid CTA with no sibling ghost open-stage control", () => {
    expect(primarySource).toContain('data-testid="research-primary-cta"');
    expect(primarySource).toContain("Single solid CTA");
    expect(primarySource).not.toContain("打开对应阶段工作台");
    expect(primarySource).toContain("research-stage-handoff-banner");
  });
});
