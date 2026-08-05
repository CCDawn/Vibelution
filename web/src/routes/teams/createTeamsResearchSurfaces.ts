/**
 * R1-b: Research surface renderers composition (workspace + primary + workflow).
 * Pure factory (no hooks). Workbench passes a dep bag; returns all render* handles.
 */
/* eslint-disable @typescript-eslint/no-explicit-any */
import { createTeamsWorkspacePanelRenderers } from "./teamsWorkspacePanelRenderers";
import { createResearchPrimarySurfaceRenderers } from "./teamResearchPrimarySurfaceRenderers";
import { createResearchWorkflowSurfaceRenderers } from "./teamResearchWorkflowSurfaceRenderers";

export type TeamsResearchSurfacesContext = {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  [key: string]: any;
  lang?: "zh" | "en";
  styles?: Record<string, string>;
};

export function createTeamsResearchSurfaces(ctx: TeamsResearchSurfacesContext) {
  const workspacePanels = createTeamsWorkspacePanelRenderers(ctx as any);
  const primarySurfaces = createResearchPrimarySurfaceRenderers({
    ...ctx,
    ...workspacePanels,
  } as any);
  const workflowSurfaces = createResearchWorkflowSurfaceRenderers({
    ...ctx,
    ...workspacePanels,
    ...primarySurfaces,
  } as any);
  return {
    ...workspacePanels,
    ...primarySurfaces,
    ...workflowSurfaces,
  };
}
