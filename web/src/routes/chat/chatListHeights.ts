/**
 * Shared height pane specs for Chat list strips (Wave 6G).
 * Stored under WORKBENCH_LAYOUT_IDS.chat in vibelution.pane-heights.v1.
 */
import type { PaneHeightSpec } from "../../components/layout/paneHeightPersistence";
import { WORKBENCH_LAYOUT_IDS } from "../../components/layout/workbenchLayoutIds";

export const CHAT_LIST_HEIGHT_LAYOUT_ID = WORKBENCH_LAYOUT_IDS.chat;

/** Group room member picker in status rail (~former max-h min(40dvh,360px)). */
export const CHAT_GROUP_MEMBER_PICKER_HEIGHT_PANE: PaneHeightSpec = {
  id: "group-member-picker",
  defaultHeight: 280,
  minHeight: 160,
  maxHeight: 360,
};

/**
 * Companion / mental-model compact details body in status rail
 * (~former max-h 220px on the whole <details>).
 * Height applies to the open body only; closed summary stays content-sized.
 */
export const CHAT_COMPACT_DETAILS_HEIGHT_PANE: PaneHeightSpec = {
  id: "compact-details",
  defaultHeight: 220,
  minHeight: 120,
  maxHeight: 360,
};
