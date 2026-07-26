import type { ResearchWorkspaceView } from "./researchWorkspaceModel";

/** Path-scoped Teams UI packs (Wave 8N + U4 research split). */
export type TeamsPanelPackId =
  | "shared"
  | "research"
  | "research_experiment"
  | "research_search"
  | "source_collection";

export type TeamsPanelPrefetchInput = {
  researchWorkflowTeamSelected: boolean;
  aiSearchScopeTeamSelected: boolean;
  /** True when the knowledge/source-collection workspace is the active surface. */
  sourceCollectionWorkspaceSelected: boolean;
  /** Optional view for finer research secondary packs. */
  researchWorkspaceView?: ResearchWorkspaceView | null;
};

const RESEARCH_EXPERIMENT_VIEWS = new Set<ResearchWorkspaceView>([
  "overview",
  "experiment",
  "iteration",
  "candidates",
  "graph",
  "coordination",
  "ingestion",
]);

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
    packs.add("research_search");
    packs.add("shared");
  }

  // Research workflow on non-SC surfaces (overview / experiment / iteration / canvas / …).
  if (input.researchWorkflowTeamSelected && !input.sourceCollectionWorkspaceSelected) {
    packs.add("research");
    packs.add("shared");
    const view = input.researchWorkspaceView;
    if (!view || RESEARCH_EXPERIMENT_VIEWS.has(view)) {
      packs.add("research_experiment");
    }
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
  research_experiment: () => Promise<unknown>;
  research_search: () => Promise<unknown>;
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
