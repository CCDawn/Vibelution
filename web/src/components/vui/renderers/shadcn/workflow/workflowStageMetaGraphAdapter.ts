/**
 * Stage meta-graph construction (LEGACY, retired from the production path).
 *
 * Superseded by the outer ELK architecture (workflowOuterElkGraphAdapter):
 * stage positions, gaps and cross-stage routing are now computed by a REAL
 * outer ELK graph with label spacer nodes — no fixed STAGE_CHANNEL_GAP.
 *
 * Retained only for reference and legacy tests. Deletion condition: all
 * remaining tests migrated to the outer-ELK contracts and no production
 * import remains (workflowTwoLevelLayout no longer imports this module).
 */
import type { WorkflowLayoutInput } from "../../../product/workflow/workflowCanvasTypes";
import { WORKFLOW_STAGE_TITLE_HEIGHT } from "./workflowElkOptions";
import type { Rect } from "./workflowLayoutGeometry";

export type StageMetaBox = {
  stageId: string;
  label: string;
  box: Rect;
};

/** Cross-stage channel gap (design budget: 32–48px). */
export const STAGE_CHANNEL_GAP = 40;

export function buildStageMetaGraph(
  input: WorkflowLayoutInput,
  stageBoxes: Map<string, Rect>,
): { stageElkIds: Map<string, string>; positions: StageMetaPositions } {
  const stageElkIds = new Map<string, string>();
  const positions = new Map<string, { x: number; y: number }>();
  let cursorX = 12;
  let maxBottom = 0;
  for (const stage of input.stages) {
    const box = stageBoxes.get(stage.stageId);
    if (!box) {
      throw new Error(`workflowStageMetaGraphAdapter: no phase-A box for stage "${stage.stageId}"`);
    }
    const stageElkId = `stage:${stage.stageId}`;
    stageElkIds.set(stage.stageId, stageElkId);
    positions.set(stage.stageId, { x: cursorX, y: 12 });
    maxBottom = Math.max(maxBottom, 12 + box.height);
    cursorX += box.width + STAGE_CHANNEL_GAP;
  }
  const width = Math.max(0, cursorX - STAGE_CHANNEL_GAP + 12);
  const size = { width, height: maxBottom + 12 };
  return { stageElkIds, positions: { positions, size } };
}

export type StageMetaPositions = {
  /** stageId -> absolute meta position (x, y). */
  positions: Map<string, { x: number; y: number }>;
  /** Total canvas size produced by the meta layout. */
  size: { width: number; height: number };
};

export type { WorkflowLayoutInput };
