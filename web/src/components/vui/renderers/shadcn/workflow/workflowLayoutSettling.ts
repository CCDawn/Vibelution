/**
 * Layout settling protocol (design -> calibration -> settled).
 *
 * Phase state machine for the two-level layout:
 *  - DESIGN: first layout using design-contract sizes; the canvas then
 *    measures real task content sizes;
 *  - CALIBRATION: measured sizes differ from the committed sizes beyond a
 *    threshold -> one relayout with real sizes;
 *  - SETTLED: sizes converged (or the calibration budget is spent) -> this
 *    revision is the one allowed to trigger the initial fit.
 *
 * Pure functions; the hook owns the revision/token plumbing.
 */
import type { WorkflowLayoutNode } from "../../../product/workflow/workflowCanvasTypes";
import type { WorkflowNodeSize } from "./workflowLayoutHash";

export type SettlingPhase = "design" | "calibration" | "settled";

export const SIZE_CHANGE_THRESHOLD = 2; // px; 1px jitter must not relayout
export const MAX_CALIBRATION_ROUNDS = 1;

/** True when measured content size differs meaningfully from the committed size. */
export function requiresCalibration(
  measured: { width: number; height: number },
  committed: { width: number; height: number },
): boolean {
  return (
    Math.abs(measured.width - committed.width) > SIZE_CHANGE_THRESHOLD ||
    Math.abs(measured.height - committed.height) > SIZE_CHANGE_THRESHOLD
  );
}

/**
 * True when the committed layout matches the measured content sizes for every
 * task (within threshold). A settled layout stays settled across runtime-only
 * updates, because they never change sizes.
 */
export function isLayoutSettled(
  nodes: WorkflowLayoutNode[],
  sizes: ReadonlyMap<string, WorkflowNodeSize>,
  currentPhase: SettlingPhase,
): boolean {
  if (currentPhase === "settled") {
    return true;
  }
  for (const node of nodes) {
    if (node.kind !== "task") continue;
    const measured = sizes.get(node.id);
    if (!measured) continue;
    if (requiresCalibration(measured, { width: node.width, height: node.height })) {
      return false;
    }
  }
  return true;
}

export function nextPhase(
  current: SettlingPhase,
  calibrationRounds: number,
  needsCalibration: boolean,
): SettlingPhase {
  if (current === "design") {
    return needsCalibration && calibrationRounds < MAX_CALIBRATION_ROUNDS
      ? "calibration"
      : "settled";
  }
  if (current === "calibration") {
    return needsCalibration && calibrationRounds < MAX_CALIBRATION_ROUNDS
      ? "calibration"
      : "settled";
  }
  return "settled";
}

/** True when the given revision may trigger the initial fit. */
export function mayFit(phase: SettlingPhase): boolean {
  return phase === "settled";
}
