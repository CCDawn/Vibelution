/**
 * Shared height pane specs for Teams source-collection list shells (Wave 6E).
 * Stored under WORKBENCH_LAYOUT_IDS.teams in vibelution.pane-heights.v1.
 */
import type { PaneHeightSpec } from "../components/layout/paneHeightPersistence";
import { WORKBENCH_LAYOUT_IDS } from "../components/layout/workbenchLayoutIds";

export const TEAM_SOURCE_COLLECTION_LAYOUT_ID = WORKBENCH_LAYOUT_IDS.teams;

/** Extracted candidates / screening / memory review lists (~former max-h 44vh). */
export const TEAM_SOURCE_COLLECTION_LIST_HEIGHT_PANE: PaneHeightSpec = {
  id: "source-collection-list",
  defaultHeight: 320,
  minHeight: 220,
  maxHeight: 560,
};

/** Ingestion graph node list (~former max-h 28vh). */
export const TEAM_SOURCE_COLLECTION_GRAPH_NODES_HEIGHT_PANE: PaneHeightSpec = {
  id: "source-collection-graph-nodes",
  defaultHeight: 200,
  minHeight: 96,
  maxHeight: 420,
};

/**
 * Stage-specific pane ids so heights do not thrash when switching source-collection
 * modules (candidates vs screening vs memory). Defaults match the shared list pane.
 */
export const TEAM_SOURCE_COLLECTION_CANDIDATES_HEIGHT_PANE: PaneHeightSpec = {
  ...TEAM_SOURCE_COLLECTION_LIST_HEIGHT_PANE,
  id: "source-collection-candidates",
};

export const TEAM_SOURCE_COLLECTION_SCREENING_HEIGHT_PANE: PaneHeightSpec = {
  ...TEAM_SOURCE_COLLECTION_LIST_HEIGHT_PANE,
  id: "source-collection-screening",
};

export const TEAM_SOURCE_COLLECTION_MEMORY_HEIGHT_PANE: PaneHeightSpec = {
  ...TEAM_SOURCE_COLLECTION_LIST_HEIGHT_PANE,
  id: "source-collection-memory",
};
