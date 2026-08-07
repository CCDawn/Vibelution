/**
 * Stage meta-graph construction and layout (phase B of the two-level layout).
 *
 * Collapses the stages into meta-nodes sized by their phase-A boxes and lays
 * them out along RIGHT. The stage sequence is the definition order; positions
 * are computed DETERMINISTICALLY as a single row with a fixed channel gap:
 * ELK cannot order unconnected compounds (probe fact, design §4.2), so a
 * hand-computed row is the geometry authority here — no ordering edges, no
 * engine dependency for the meta placement.
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
