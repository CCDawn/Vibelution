import { lazy, type ComponentType } from "react";

/**
 * Lazy registry for companion-mode surfaces inside the chat workbench. All
 * three render only when a verified companion is attached to the session
 * (`verifiedCompanionMode` / `activeCompanion`), so the chat route chunk keeps
 * its ordinary first paint free of the companion surface family and fetches it
 * only when companion mode is actually active.
 */

/**
 * React.lazy wrapper that keeps the picked component's exact prop types: the
 * module promise's named export becomes the lazy default.
 */
function lazyNamed<M extends object, K extends keyof M>(module: Promise<M>, pick: K): M[K] {
  return lazy(async () => {
    const loaded = await module;
    return { default: loaded[pick] as ComponentType<any> };
  }) as unknown as M[K];
}

export const CompanionLifeRailLazy = lazyNamed(import("../companions/CompanionLifeRail"), "CompanionLifeRail");
export const CompanionPersonRailLazy = lazyNamed(import("../companions/CompanionPersonRail"), "CompanionPersonRail");
export const CompanionSceneWorkspaceLazy = lazyNamed(import("../companions/CompanionSceneWorkspace"), "CompanionSceneWorkspace");

export const FinancialResearchLiveProjectionLazy = lazyNamed(
  import("../finance/FinancialResearchLiveProjection"),
  "FinancialResearchLiveProjection",
);
