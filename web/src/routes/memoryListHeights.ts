/**
 * Shared height pane specs for Memory compact lists (Wave 6F).
 * Stored under WORKBENCH_LAYOUT_IDS.memory in vibelution.pane-heights.v1.
 */
import type { PaneHeightSpec } from "../components/layout/paneHeightPersistence";
import { WORKBENCH_LAYOUT_IDS } from "../components/layout/workbenchLayoutIds";

export const MEMORY_LIST_HEIGHT_LAYOUT_ID = WORKBENCH_LAYOUT_IDS.memory;

/** Overview compact memory item lists (~former max-h 148px). */
export const MEMORY_COMPACT_LIST_HEIGHT_PANE: PaneHeightSpec = {
  id: "compact-memory-list",
  defaultHeight: 148,
  minHeight: 96,
  maxHeight: 320,
};
