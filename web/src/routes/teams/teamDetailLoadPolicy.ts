/**
 * First-paint load policy for TeamsRoute.
 * Prefer light team detail + view-gated heavy queries over always-full hydration.
 */

export type TeamDetailLoadMode = "light" | "full";

export type ResearchWorkspaceViewLike =
  | "overview"
  | "source_collection"
  | "knowledge_collection"
  | "canvas"
  | "candidates"
  | "graph"
  | "ingestion"
  | "coordination"
  | "experiment"
  | "iteration"
  | string;

/**
 * Team detail always starts light. Full detail is reserved for rare repair-heavy
 * surfaces; canvas lives on its own endpoint.
 */
export function resolveTeamDetailLoadMode(_options?: {
  sourceCollectionStandalone?: boolean;
  researchWorkspaceView?: ResearchWorkspaceViewLike;
}): TeamDetailLoadMode {
  return "light";
}

/** Organization canvas API is expensive; only fetch when the canvas surface is active. */
export function resolveTeamCanvasQueryEnabled(options: {
  effectiveTeamId: string;
  researchWorkflowTeamSelected: boolean;
  researchWorkspaceView: ResearchWorkspaceViewLike;
  sourceCollectionStandalone: boolean;
}): boolean {
  if (!options.effectiveTeamId || options.sourceCollectionStandalone) {
    return false;
  }
  if (options.researchWorkflowTeamSelected) {
    return options.researchWorkspaceView === "canvas";
  }
  // Custom / demo teams: main workbench surface is the organization canvas.
  return true;
}

/** SC run list is only needed inside source-collection / knowledge-collection workspaces. */
export function resolveSourceCollectionRunsQueryEnabled(options: {
  effectiveTeamId: string;
  researchWorkflowTeamSelected: boolean;
  sourceCollectionWorkspaceSelected: boolean;
}): boolean {
  return Boolean(
    options.effectiveTeamId
    && options.researchWorkflowTeamSelected
    && options.sourceCollectionWorkspaceSelected,
  );
}

/**
 * Experiment planning / research-loop status are unused on SC-only surfaces and
 * should not fire for every research team overview refresh.
 */
export function resolveResearchSecondaryStatusQueryEnabled(options: {
  effectiveTeamId: string;
  researchWorkflowTeamSelected: boolean;
  researchWorkspaceView: ResearchWorkspaceViewLike;
  sourceCollectionStandalone: boolean;
}): boolean {
  if (!options.effectiveTeamId || !options.researchWorkflowTeamSelected || options.sourceCollectionStandalone) {
    return false;
  }
  return options.researchWorkspaceView !== "source_collection"
    && options.researchWorkspaceView !== "knowledge_collection"
    && options.researchWorkspaceView !== "canvas";
}

export function isForeignTeamDetailQueryKey(
  queryKey: readonly unknown[],
  activeTeamId: string,
): boolean {
  if (queryKey[0] !== "teams" || queryKey[2] !== "detail") {
    return false;
  }
  const teamId = String(queryKey[1] ?? "").trim();
  if (!teamId || teamId === "none") {
    return false;
  }
  return teamId !== activeTeamId;
}
