/**
 * R2-q: workbench research surface bag wiring.
 * Keeps createTeamsResearchSurfaces call out of the workbench model body.
 */
/* eslint-disable @typescript-eslint/no-explicit-any */
import { createTeamsResearchSurfaces } from "./createTeamsResearchSurfaces";

export function createTeamsWorkbenchResearchSurfaces(ctx: {
  scComposition: Record<string, any>;
  [key: string]: any;
}) {
  const { scComposition, ...extras } = ctx;
  return createTeamsResearchSurfaces({
    ...scComposition,
    ...extras,
  });
}
