/**
 * @deprecated Removed single secondary pack (Wave 8N pack-split).
 * Use path-scoped barrels instead:
 * - `teamSharedPanels.ts`
 * - `teamResearchPanels.ts` (core stages/loop)
 * - `teamResearchExperimentPanels.ts` (U4 experiment + workflow status)
 * - `teamResearchSearchPanels.ts` (U4 AI search + memory index)
 * - `teamSourceCollectionPanels.ts`
 *
 * This file intentionally does not re-export UI to prevent the old mono-chunk from returning.
 */
export {};
