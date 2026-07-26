/**
 * Soft-prefetch for Agents structured workbench copy (dictionary charter C1.1).
 * Not a flat TranslationKey domain — nested tables stay typed via AgentsRouteCopy.
 */
export function prefetchAgentsWorkbenchCopy(): void {
  void import("./domains/agentsWorkbenchCopy").catch(() => {
    // Soft prefetch must not surface.
  });
}

export async function loadAgentsWorkbenchCopy() {
  return import("./domains/agentsWorkbenchCopy");
}
