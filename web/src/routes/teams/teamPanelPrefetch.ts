import type { ResearchWorkspaceView } from "./researchWorkspaceModel";

/** Path-scoped Teams UI packs created in Wave 8N. */
export type TeamsPanelPackId = "shared" | "research" | "source_collection";

export type TeamsPanelPrefetchInput = {
  researchWorkflowTeamSelected: boolean;
  aiSearchScopeTeamSelected: boolean;
  /** True when the knowledge/source-collection workspace is the active surface. */
  sourceCollectionWorkspaceSelected: boolean;
};

/**
 * Decide which secondary packs to warm after a team/view switch.
 * Does not prefetch on empty shell: callers only invoke when a matching surface is active.
 */
export function resolveTeamsPanelPrefetchPacks(input: TeamsPanelPrefetchInput): TeamsPanelPackId[] {
  const packs = new Set<TeamsPanelPackId>();

  if (input.sourceCollectionWorkspaceSelected) {
    packs.add("source_collection");
    packs.add("shared");
  }

  if (input.aiSearchScopeTeamSelected) {
    packs.add("research");
    packs.add("shared");
  }

  // Research workflow on non-SC surfaces (overview / experiment / iteration / canvas / …).
  if (input.researchWorkflowTeamSelected && !input.sourceCollectionWorkspaceSelected) {
    packs.add("research");
    packs.add("shared");
  }

  return [...packs];
}

/** Convenience: detect SC surface from view + standalone flag. */
export function isSourceCollectionWorkspaceSelected(input: {
  researchWorkflowTeamSelected: boolean;
  sourceCollectionStandalone: boolean;
  researchWorkspaceView: ResearchWorkspaceView;
}): boolean {
  if (!input.researchWorkflowTeamSelected) {
    return false;
  }
  return (
    input.sourceCollectionStandalone
    || input.researchWorkspaceView === "knowledge_collection"
    || input.researchWorkspaceView === "source_collection"
  );
}

export type TeamsPanelPackLoaders = {
  shared: () => Promise<unknown>;
  research: () => Promise<unknown>;
  source_collection: () => Promise<unknown>;
};

/**
 * Fire-and-forget pack imports. Safe to call repeatedly; browser module cache dedupes.
 */
export function prefetchTeamsPanelPacks(
  packs: TeamsPanelPackId[],
  loaders: TeamsPanelPackLoaders,
): void {
  for (const pack of packs) {
    void loaders[pack]();
  }
}
