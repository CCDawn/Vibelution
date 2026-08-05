/**
 * R2-s close-out: research surface deps bag for shell phase.
 *
 * Pass the shell bag through intact. A field allow-list previously dropped
 * experiment drafts / workspace actions (e.g. experimentBaselineArtifactDraft),
 * which crashed the experiment ledger on `.artifactPath`.
 */
/* eslint-disable @typescript-eslint/no-explicit-any */
import { createTeamsWorkbenchResearchSurfaces } from "./createTeamsWorkbenchResearchSurfaces";

export function buildTeamsWorkbenchResearchSurfacesFromBag(d: any) {
  return createTeamsWorkbenchResearchSurfaces(d);
}
