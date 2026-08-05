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
  it("keeps project-progress → stage-nav → continue/advance CTA → stages → advanced order", () => {
    const progressLabel = surfaceSource.indexOf("项目推进");
    const stageNav = surfaceSource.indexOf('data-testid="research-overview-stage-nav"');
    const hero = surfaceSource.indexOf('data-testid="research-overview-hero"');
    const stages = surfaceSource.indexOf('data-testid="research-overview-stages"');
    // Secondary is the last composition slot (not the import line).
    const secondarySlot = surfaceSource.indexOf("{advanced ? (");
    expect(progressLabel).toBeGreaterThan(-1);
    expect(stageNav).toBeGreaterThan(progressLabel);
    expect(hero).toBeGreaterThan(stageNav);
    expect(stages).toBeGreaterThan(hero);
    expect(secondarySlot).toBeGreaterThan(stages);
    expect(surfaceSource.slice(secondarySlot)).toContain("ResearchOverviewSecondary");
    expect(surfaceSource).toContain("阶段看板");
    expect(surfaceSource).toContain("主按钮继续当前");
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

  it("primary bar continues current stage; advance is a separate secondary CTA", () => {
    expect(primarySource).toContain('data-testid="research-primary-cta"');
    expect(primarySource).toContain('data-testid="research-advance-cta"');
    expect(primarySource).toContain("continue current stage");
    expect(primarySource).not.toContain("打开对应阶段工作台");
    expect(primarySource).toContain("research-stage-handoff-banner");
    // CTA text + arrow must use trailingIcon, not multi-child label slot (truncation breaks layout).
    expect(primarySource).toContain("trailingIcon=");
    expect(primarySource).not.toContain("handoff?.action ?? action");
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
