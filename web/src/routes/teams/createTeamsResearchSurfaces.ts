/**
 * R1-b: Research surface renderers composition (workspace + primary + workflow).
 * Pure factory (no hooks). Workbench passes a dep bag; returns all render* handles.
 */
import { createTeamsWorkspacePanelRenderers } from "./teamsWorkspacePanelRenderers";
import { createResearchPrimarySurfaceRenderers } from "./teamResearchPrimarySurfaceRenderers";
import { createResearchWorkflowSurfaceRenderers } from "./teamResearchWorkflowSurfaceRenderers";

export type TeamsResearchSurfacesContext = {
  // Foundation bag boundary: dep-bag keys stay unknown until Phase 9+ foundation typing.
  [key: string]: unknown;
  lang?: "zh" | "en";
  styles?: Record<string, string>;
};

export function createTeamsResearchSurfaces(ctx: TeamsResearchSurfacesContext) {
  const workspacePanels = createTeamsWorkspacePanelRenderers(ctx);
  const primarySurfaces = createResearchPrimarySurfaceRenderers({
    ...ctx,
    ...workspacePanels,
  });
  const workflowSurfaces = createResearchWorkflowSurfaceRenderers({
    ...ctx,
    ...workspacePanels,
    ...primarySurfaces,
  });
  return {
    ...workspacePanels,
    ...primarySurfaces,
    ...workflowSurfaces,
  };
}
