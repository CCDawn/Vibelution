/**
 * Browser-local visual attachment for serpentine edges.
 *
 * These overrides move an arrow onto another magnet of the already connected
 * cards. They never rewrite source/target node ids, ELK topology, or runtime.
 */
import type { Connection, Edge } from "@xyflow/react";

import type {
  WorkflowLayoutEdge,
  WorkflowPortSide,
  WorkflowPortSides,
} from "../../../product/workflow/workflowCanvasTypes";
import {
  WORKFLOW_SNAP_SLOTS_LONG,
  WORKFLOW_SNAP_SLOTS_SHORT,
} from "./workflowOrthogonalRoute";

export const WORKFLOW_PORT_SIDES: readonly WorkflowPortSide[] = ["NORTH", "EAST", "SOUTH", "WEST"];
const SNAP_HANDLE_PREFIX = "workflow-snap:";

export type WorkflowEdgeAnchor = {
  sourceSide?: WorkflowPortSide;
  targetSide?: WorkflowPortSide;
  sourceFraction?: number;
  targetFraction?: number;
};

export type WorkflowEdgeAnchors = Record<string, WorkflowEdgeAnchor>;

export type WorkflowReconnectMagnets = { type: "source" | "target" };

export function workflowSnapSlotsForPortSide(side: WorkflowPortSide): readonly number[] {
  return side === "WEST" || side === "EAST" ? WORKFLOW_SNAP_SLOTS_SHORT : WORKFLOW_SNAP_SLOTS_LONG;
}

export function workflowSnapHandleId(side: WorkflowPortSide, fraction: number): string {
  return `${SNAP_HANDLE_PREFIX}${side}:${fraction.toFixed(4)}`;
}

export function parseWorkflowSnapHandle(
  handleId: string | null | undefined,
): { side: WorkflowPortSide; fraction: number } | null {
  if (!handleId?.startsWith(SNAP_HANDLE_PREFIX)) return null;
  const match = /^workflow-snap:(NORTH|EAST|SOUTH|WEST):(\d+(?:\.\d+)?)$/.exec(handleId);
  if (!match) return null;
  const fraction = Number(match[2]);
  if (!Number.isFinite(fraction) || fraction < 0 || fraction > 1) return null;
  return { side: match[1] as WorkflowPortSide, fraction };
}

export function workflowReconnectKeepsEndpoints(
  edge: Pick<Edge, "source" | "target">,
  connection: Pick<Connection, "source" | "target">,
): boolean {
  return connection.source === edge.source && connection.target === edge.target;
}

export function resolveWorkflowEdgeAnchorPatch(args: {
  handleType: "source" | "target";
  connection: Connection;
  portSides?: WorkflowPortSides;
}): WorkflowEdgeAnchor | null {
  const handleId = args.handleType === "source" ? args.connection.sourceHandle : args.connection.targetHandle;
  const snap = parseWorkflowSnapHandle(handleId);
  if (snap) {
    return args.handleType === "source"
      ? { sourceSide: snap.side, sourceFraction: snap.fraction }
      : { targetSide: snap.side, targetFraction: snap.fraction };
  }
  if (!handleId || !args.portSides) return null;
  if (args.handleType === "source") {
    const side = args.portSides.source[handleId];
    if (!side) return null;
    const fraction = args.portSides.sourceAnchor?.[handleId];
    return { sourceSide: side, sourceFraction: typeof fraction === "number" ? fraction : 0.5 };
  }
  const side = args.portSides.target[handleId];
  if (!side) return null;
  const fraction = args.portSides.targetAnchor?.[handleId];
  return { targetSide: side, targetFraction: typeof fraction === "number" ? fraction : 0.5 };
}

export function applyWorkflowEdgeAnchorsToPortSides(
  nodeId: string,
  portSides: WorkflowPortSides | undefined,
  edges: ReadonlyArray<Pick<WorkflowLayoutEdge, "id" | "source" | "target" | "sourceHandle" | "targetHandle">>,
  anchors: WorkflowEdgeAnchors,
): WorkflowPortSides | undefined {
  if (!portSides) return portSides;
  let next: WorkflowPortSides | undefined;
  const draft = (): WorkflowPortSides => {
    next ??= {
      source: { ...portSides.source },
      target: { ...portSides.target },
      sourceAnchor: { ...portSides.sourceAnchor },
      targetAnchor: { ...portSides.targetAnchor },
    };
    return next;
  };
  for (const edge of edges) {
    const anchor = anchors[edge.id];
    if (!anchor) continue;
    if (edge.source === nodeId && edge.sourceHandle) {
      const portSidesDraft = draft();
      if (anchor.sourceSide) portSidesDraft.source[edge.sourceHandle] = anchor.sourceSide;
      if (typeof anchor.sourceFraction === "number") {
        portSidesDraft.sourceAnchor = { ...portSidesDraft.sourceAnchor, [edge.sourceHandle]: anchor.sourceFraction };
      }
    }
    if (edge.target === nodeId && edge.targetHandle) {
      const portSidesDraft = draft();
      if (anchor.targetSide) portSidesDraft.target[edge.targetHandle] = anchor.targetSide;
      if (typeof anchor.targetFraction === "number") {
        portSidesDraft.targetAnchor = { ...portSidesDraft.targetAnchor, [edge.targetHandle]: anchor.targetFraction };
      }
    }
  }
  return next ?? portSides;
}

export function cloneWorkflowEdgeAnchors(anchors: WorkflowEdgeAnchors): WorkflowEdgeAnchors {
  return Object.fromEntries(
    Object.entries(anchors).map(([id, anchor]) => [id, { ...anchor }]),
  );
}

export function parseWorkflowEdgeAnchors(value: unknown): WorkflowEdgeAnchors {
  if (!isRecord(value)) return {};
  const anchors: WorkflowEdgeAnchors = {};
  for (const [id, candidate] of Object.entries(value)) {
    const parsed = parseEdgeAnchor(candidate);
    if (parsed) anchors[id] = parsed;
  }
  return anchors;
}

export function readWorkflowReconnectMagnets(data: unknown): WorkflowReconnectMagnets | undefined {
  if (!isRecord(data) || !isRecord(data.reconnectMagnets)) return undefined;
  const type = data.reconnectMagnets.type;
  return type === "source" || type === "target" ? { type } : undefined;
}

function parseEdgeAnchor(value: unknown): WorkflowEdgeAnchor | null {
  if (!isRecord(value)) return null;
  const anchor: WorkflowEdgeAnchor = {};
  if (value.sourceSide !== undefined) {
    if (!isPortSide(value.sourceSide)) return null;
    anchor.sourceSide = value.sourceSide;
  }
  if (value.targetSide !== undefined) {
    if (!isPortSide(value.targetSide)) return null;
    anchor.targetSide = value.targetSide;
  }
  if (value.sourceFraction !== undefined) {
    if (!isFraction(value.sourceFraction)) return null;
    anchor.sourceFraction = value.sourceFraction;
  }
  if (value.targetFraction !== undefined) {
    if (!isFraction(value.targetFraction)) return null;
    anchor.targetFraction = value.targetFraction;
  }
  return Object.keys(anchor).length > 0 ? anchor : null;
}

function isPortSide(value: unknown): value is WorkflowPortSide {
  return value === "NORTH" || value === "EAST" || value === "SOUTH" || value === "WEST";
}

function isFraction(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
