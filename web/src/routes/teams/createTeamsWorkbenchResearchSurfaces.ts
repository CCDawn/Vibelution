/**
 * R2-q: workbench research surface bag wiring.
 * Keeps createTeamsResearchSurfaces call out of the workbench model body.
 */
import { createTeamsResearchSurfaces } from "./createTeamsResearchSurfaces";
import type { useTeamsScComposition } from "./useTeamsScComposition";

export function createTeamsWorkbenchResearchSurfaces(ctx: {
  scComposition: ReturnType<typeof useTeamsScComposition>;
  // Foundation shell extras boundary: extra bag keys stay unknown until Phase 9+ foundation typing.
  [key: string]: unknown;
}) {
  const { scComposition, ...extras } = ctx;
  return createTeamsResearchSurfaces({
    ...scComposition,
    ...extras,
  });
}
