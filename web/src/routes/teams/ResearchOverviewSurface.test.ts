import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const surfaceSource = readFileSync(new URL("./ResearchOverviewSurface.tsx", import.meta.url), "utf8");
const primarySource = readFileSync(new URL("./ResearchPrimaryActionBar.tsx", import.meta.url), "utf8");
const routeSource = [
  readFileSync(new URL("./TeamsRouteWorkbench.tsx", import.meta.url), "utf8"),
  readFileSync(new URL("./useTeamsWorkbenchModel.tsx", import.meta.url), "utf8") + "\n" + readFileSync(new URL("./useTeamsWorkbenchFoundation.tsx", import.meta.url), "utf8") + "\n" + readFileSync(new URL("./useTeamsWorkbenchShellPhase.tsx", import.meta.url), "utf8"),
].join("\n");
const primaryRenderersSource = readFileSync(
  new URL("./teamResearchPrimarySurfaceRenderers.tsx", import.meta.url),
  "utf8",
);

describe("ResearchOverviewSurface product contract", () => {
  it("keeps end-user IA: flow control only (stage-nav + CTA); canvas owns main body", () => {
    expect(surfaceSource).toContain('data-testid="research-overview-flow"');
    expect(surfaceSource).toContain('data-testid="research-overview-stage-nav"');
    expect(surfaceSource).toContain('data-testid="research-overview-hero"');
    // No kanban / advanced wall on overview strip.
    expect(surfaceSource).not.toContain("ResearchOverviewSecondary");
    expect(surfaceSource).not.toContain("ResearchBoardKanban");
    expect(surfaceSource).not.toContain('data-testid="research-overview-stages"');
    expect(surfaceSource).toContain('data-overview-density="flow-only"');
    expect(surfaceSource).toContain("流程控制");
    expect(surfaceSource).toContain("research-overview-trailing-actions");
    expect(surfaceSource).toContain("trailingActions");
    expect(surfaceSource).toContain("sideSlot");
    // Stage nav + layout tools are inside the next-step card (headerSlot), not a free row above.
    expect(surfaceSource).toContain("headerSlot={headerSlot}");
    expect(primarySource).toContain("researchPrimaryHeroHeader");
    expect(primarySource).toContain("research-primary-header-slot");
    expect(primarySource).toContain("researchPrimaryHeroSplit");
    expect(primarySource).toContain("research-primary-side-slot");
  });

  it("wires research overview through primary renderers without board kanban", () => {
    expect(primaryRenderersSource).toContain("ResearchOverviewSurface");
    expect(primaryRenderersSource).not.toContain("ResearchBoardKanban");
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
    // Overview progressive fill is owned by the primary-surface factory extract (CTA metrics only).
    expect(primaryRenderersSource).toContain("loading: overviewWorkflowPending");
    expect(primaryRenderersSource).not.toMatch(
      /function renderResearchOverviewSurface\(\) \{\s*if \(!teamWorkflow\)/,
    );
    expect(routeSource).not.toContain("function renderResearchOverviewSurface(");
  });
});
