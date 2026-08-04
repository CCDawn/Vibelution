import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const surfaceSource = readFileSync(new URL("./ResearchOverviewSurface.tsx", import.meta.url), "utf8");
const primarySource = readFileSync(new URL("./ResearchPrimaryActionBar.tsx", import.meta.url), "utf8");
const routeSource = readFileSync(new URL("../TeamsRoute.tsx", import.meta.url), "utf8");
const primaryRenderersSource = readFileSync(
  new URL("./teamResearchPrimarySurfaceRenderers.tsx", import.meta.url),
  "utf8",
);

describe("ResearchOverviewSurface product contract", () => {
  it("keeps project-progress → single-CTA → stages → advanced order in JSX body", () => {
    const progressLabel = surfaceSource.indexOf("项目推进");
    const hero = surfaceSource.indexOf('data-testid="research-overview-hero"');
    const stages = surfaceSource.indexOf('data-testid="research-overview-stages"');
    // Secondary is the last composition slot (not the import line).
    const secondarySlot = surfaceSource.indexOf("{advanced ? (");
    expect(progressLabel).toBeGreaterThan(-1);
    expect(hero).toBeGreaterThan(progressLabel);
    expect(stages).toBeGreaterThan(hero);
    expect(secondarySlot).toBeGreaterThan(stages);
    expect(surfaceSource.slice(secondarySlot)).toContain("ResearchOverviewSecondary");
    expect(surfaceSource).toContain("阶段看板");
  });

  it("primary CTA uses monochrome ink accent, not teal brand wash", () => {
    expect(primarySource).toContain("monochrome ink accent");
    expect(primarySource).toContain("shadow-[inset_3px_0_0_0_var(--fg-primary)]");
    expect(primarySource).not.toContain("accent-cool");
  });

  it("wires production overview through ResearchOverviewSurface only", () => {
    expect(routeSource).toContain("renderResearchOverviewSurface");
    // Composition lives in the extracted primary-surface factory (not inline in TeamsRoute).
    expect(primaryRenderersSource).toContain("ResearchOverviewSurface");
    expect(primaryRenderersSource).toContain("ResearchBoardKanban");
    expect(routeSource).not.toContain("function renderResearchOverviewSurface(");
    // Must not re-embed a second hero CTA bar under the workflow panel.
    expect(routeSource).not.toMatch(/showResearchOverview\s*\?\s*\(\s*<div[^>]*research-overview-hero/);
  });

  it("primary bar is a single solid CTA with no sibling ghost open-stage control", () => {
    expect(primarySource).toContain('data-testid="research-primary-cta"');
    expect(primarySource).toContain("Single solid CTA");
    expect(primarySource).not.toContain("打开对应阶段工作台");
    expect(primarySource).toContain("research-stage-handoff-banner");
    // CTA text + arrow must use trailingIcon, not multi-child label slot (truncation breaks layout).
    expect(primarySource).toContain("trailingIcon=");
    expect(primarySource).not.toContain("<span>{buttonLabel}</span>");
  });

  it("keeps progressive skeleton contract: fixed geometry loading, not fill swap", () => {
    expect(surfaceSource).toContain("progressive-fill");
    expect(primarySource).toContain("loading");
    expect(primarySource).toContain("research-primary-cta-skeleton");
    expect(primarySource).toContain("data-loading");
    const kanbanSource = readFileSync(new URL("./ResearchBoardKanban.tsx", import.meta.url), "utf8");
    expect(kanbanSource).toContain("loading");
    expect(kanbanSource).toContain("research-board-column-skeleton");
    // Overview progressive fill is owned by the primary-surface factory extract.
    expect(primaryRenderersSource).toContain("loading: overviewWorkflowPending");
    expect(primaryRenderersSource).toContain("loading={overviewWorkflowPending}");
    expect(primaryRenderersSource).not.toMatch(
      /function renderResearchOverviewSurface\(\) \{\s*if \(!teamWorkflow\)/,
    );
    expect(routeSource).not.toContain("function renderResearchOverviewSurface(");
  });
});
