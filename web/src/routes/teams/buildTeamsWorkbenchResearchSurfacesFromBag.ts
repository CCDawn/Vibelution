/**
 * R2-s close-out: research surface deps bag for shell phase.
 *
 * Pass the shell bag through intact. A field allow-list previously dropped
 * experiment drafts / workspace actions (e.g. experimentBaselineArtifactDraft),
 * which crashed the experiment ledger on `.artifactPath`.
 */
import { createTeamsWorkbenchResearchSurfaces } from "./createTeamsWorkbenchResearchSurfaces";

export function buildTeamsWorkbenchResearchSurfacesFromBag(
  d: Parameters<typeof createTeamsWorkbenchResearchSurfaces>[0],
) {
  return createTeamsWorkbenchResearchSurfaces(d);
}
