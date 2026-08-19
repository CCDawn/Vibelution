/**
 * Stage-internal layout execution (phase A of the two-level layout).
 *
 * Runs one ELK DOWN layout per stage subgraph and produces:
 *  - per-task LOCAL coordinates relative to the stage origin;
 *  - per-stage size = children bounds + title band + vertical/horizontal
 *    padding (design budgets from the two-level contract).
 *
 * The local coordinate space keeps phase A independent from phase B: phase B
 * only needs the stage box, and the final absolute task position is
 * `stage meta position + local position`.
 */
import type { ElkNode } from "elkjs/lib/elk-api";

import { WORKFLOW_STAGE_TITLE_HEIGHT } from "./workflowElkOptions";
import { boundsOf, type Rect } from "./workflowLayoutGeometry";
/** Design budgets (two-level layout contract §四). */
export const STAGE_HORIZONTAL_PADDING = 20;
export const STAGE_VERTICAL_PADDING_BOTTOM = 34;
export const STAGE_MIN_WIDTH = 300;
export const STAGE_MIN_HEIGHT = 190;

export type StageLocalTask = {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  /** Internal sections are resolved in stage-local space (offset applied). */
  stageId: string;
};

export type StageLocalLayout = {
  stageId: string;
  /** Stage box in LOCAL (phase A) space — origin at (0,0). */
  box: Rect;
  tasks: StageLocalTask[];
  /** Internal edge sections in LOCAL space (to be offset by the meta x/y). */
  internalEdges: Array<{
    id: string;
    source: string;
    target: string;
    sections: Array<{
      id: string;
      startPoint: { x: number; y: number };
      endPoint: { x: number; y: number };
      bendPoints?: Array<{ x: number; y: number }>;
      incomingSections?: string[];
      outgoingSections?: string[];
    }>;
    /** Engine label coordinate (x/y/width/height in local space). */
    label?: { x: number; y: number; width: number; height: number };
  }>;
};

export type StageLayoutInput = {
  stageId: string;
  root: ElkNode;
  nodeIds: string[];
};

export async function layoutStages(
  layouts: StageLayoutInput[],
  engine: { layout: (graph: ElkNode) => Promise<ElkNode> },
): Promise<StageLocalLayout[]> {
  // Serial execution: elkjs instances are not safe for concurrent layout()
  // calls, and the outer ELK layout follows immediately — interleaving would
  // corrupt sections. Three stages are cheap enough to serialize.
  const results: StageLocalLayout[] = [];
  for (const input of layouts) {
    const laidOut = await engine.layout(input.root);
    results.push(consumeStageLayout(input, laidOut));
  }
  return results;
}

export function consumeStageLayout(
  input: StageLayoutInput,
  laidOut: ElkNode,
): StageLocalLayout {
  const tasks: StageLocalTask[] = [];
  const bounds: Rect[] = [];
  for (const child of laidOut.children ?? []) {
    const x = child.x ?? 0;
    // Reserve the title band on top of the internal content.
    const y = (child.y ?? 0) + WORKFLOW_STAGE_TITLE_HEIGHT;
    const width = child.width ?? 0;
    const height = child.height ?? 0;
    tasks.push({ id: child.id, x, y, width, height, stageId: input.stageId });
    bounds.push({ x, y, width, height });
  }

  const content = boundsOf(bounds) ?? { x: 0, y: 0, width: 0, height: 0 };
  const box: Rect = {
    x: 0,
    y: 0,
    width: Math.max(STAGE_MIN_WIDTH, content.width + STAGE_HORIZONTAL_PADDING * 2),
    // Height must reach the lowest card bottom (content.y + content.height),
    // not just the content span: when ELK pushes the first row below the title
    // band (e.g. LEFT-direction stages with a feedback rail), the span alone
    // under-heights the box and bottom-row cards poke out of the stage region.
    height: Math.max(
      STAGE_MIN_HEIGHT,
      content.y + content.height + STAGE_VERTICAL_PADDING_BOTTOM,
    ),
  };

  const internalEdges: StageLocalLayout["internalEdges"] = [];
  for (const edge of laidOut.edges ?? []) {
    const labelElk = edge.labels?.[0];
    const offsetY = WORKFLOW_STAGE_TITLE_HEIGHT;
    const sections = (edge.sections ?? []).map((s) => ({
      id: s.id,
      startPoint: { x: s.startPoint.x, y: s.startPoint.y + offsetY },
      endPoint: { x: s.endPoint.x, y: s.endPoint.y + offsetY },
      bendPoints: (s.bendPoints ?? []).map((p) => ({ x: p.x, y: p.y + offsetY })),
      incomingSections: s.incomingSections ? [...s.incomingSections] : undefined,
      outgoingSections: s.outgoingSections ? [...s.outgoingSections] : undefined,
    }));
    internalEdges.push({
      id: edge.id,
      source: (edge.sources ?? [])[0] ?? "",
      target: (edge.targets ?? [])[0] ?? "",
      sections,
      label: labelElk
        ? {
            x: labelElk.x ?? 0,
            y: (labelElk.y ?? 0) + offsetY,
            width: labelElk.width ?? 0,
            height: labelElk.height ?? 0,
          }
        : undefined,
    });
  }

  return { stageId: input.stageId, box, tasks, internalEdges };
}
