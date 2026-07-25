/**
 * Shared height pane specs for Launcher scroll strips (Wave 6F).
 * Stored under WORKBENCH_LAYOUT_IDS.launcher in vibelution.pane-heights.v1.
 */
import type { PaneHeightSpec } from "../components/layout/paneHeightPersistence";
import { WORKBENCH_LAYOUT_IDS } from "../components/layout/workbenchLayoutIds";

export const LAUNCHER_LIST_HEIGHT_LAYOUT_ID = WORKBENCH_LAYOUT_IDS.launcher;

/** Advanced diagnostics guardian responsibility table (~former max-h 220px). */
export const LAUNCHER_GUARDIAN_TABLE_HEIGHT_PANE: PaneHeightSpec = {
  id: "guardian-table",
  defaultHeight: 220,
  minHeight: 120,
  maxHeight: 420,
};

/** Developer / project-maintenance cleanup console (~former max-h 220px). */
export const LAUNCHER_CLEANUP_CONSOLE_HEIGHT_PANE: PaneHeightSpec = {
  id: "cleanup-console",
  defaultHeight: 220,
  minHeight: 120,
  maxHeight: 420,
};
