/**
 * Final layout composer: combines phase-A internal layouts with the outer ELK
 * result into the public `WorkflowLayoutResult`.
 *
 *  - task absolute = outer stage position + internal local position;
 *  - serpentine auto-layout edges use a facing-side orthogonal connector
 *    after ELK places the cards; rerun keeps a local bottom rail;
 *  - stage-columns cross-stage edges keep outer ELK sections plus gateway stubs;
 *  - port sides / handles follow the chosen orthogonal sides and snap
 *    fractions along that side.
 *
 * React Flow consumes ONLY this final projection — no geometry is invented
 * here beyond the offset composition and the serpentine orthogonal connector.
 */
import type {
  WorkflowLayoutInput,
  WorkflowLayoutNode,
  WorkflowLayoutPoint,
  WorkflowLayoutResult,
  WorkflowPortSide,
} from "../../../product/workflow/workflowCanvasTypes";
import { DECISION_OUTCOME_IDS } from "./workflowElkPorts";
import { resolveEdgeLabelSpec } from "./workflowEdgeLabelGeometry";
import type { StageLocalLayout } from "./workflowStageLayout";
import type { OuterLayoutResult } from "./workflowOuterElkLayout";
import type { Rect } from "./workflowLayoutGeometry";
import type { WorkflowCanvasLayoutMode } from "./workflowElkOptions";
import { workflowEdgeKeepsNarrativeLabel } from "./workflowElkOptions";
import {
  assignSnapFractions,
  elkSideFromOrthogonal,
  longestStrokeIsVertical,
  longestStrokeLabelAnchor,
  projectedSnapFraction,
  routeOrthogonalConnector,
  snapSlotsForSide,
  type OrthogonalRect,
  type OrthogonalSide,
} from "./workflowOrthogonalRoute";

export type ComposerInput = {
  input: WorkflowLayoutInput;
  localLayouts: Map<string, StageLocalLayout>;
  outer: OuterLayoutResult;
  stageBoxes: Map<string, Rect>;
  portSidesByNode: Map<string, WorkflowLayoutNode["portSides"]>;
  sourceHandleByEdge?: Map<string, string>;
  targetHandleByEdge: Map<string, string>;
  layoutMode?: WorkflowCanvasLayoutMode;
};

export function composeFinalLayout(ctx: ComposerInput): WorkflowLayoutResult {
  const { input, localLayouts, outer, stageBoxes, portSidesByNode, targetHandleByEdge } = ctx;
  const nodes: WorkflowLayoutNode[] = [];
  const stageById = new Map(input.stages.map((s) => [s.stageId, s] as const));
  const nodeById = new Map(input.nodes.map((n) => [n.nodeId, n] as const));
  const taskBoxes = collectTaskBoxes(ctx);
  const orthogonalRoutes = ctx.layoutMode === "serpentine"
    ? applySerpentineOrthogonalRoutes(ctx, taskBoxes)
    : new Map<string, OrthogonalEdgeRoute>();

  for (const stage of input.stages) {
    const pos = outer.stagePositions.get(stage.stageId);
    if (!pos) {
      throw new Error(`workflowLayoutComposer: no outer position for stage "${stage.stageId}"`);
    }
    const box = stageBoxes.get(stage.stageId)!;
    const local = localLayouts.get(stage.stageId);
    const meta = stageById.get(stage.stageId);

    nodes.push({
      id: `stage:${stage.stageId}`,
      stageId: stage.stageId,
      label: meta?.label ?? stage.stageId,
      actorKind: "system",
      visualKind: "stage_region",
      kind: "stage",
      x: pos.x,
      y: pos.y,
      width: box.width,
      height: box.height,
      stageTone: meta?.stageTone,
    });

    for (const task of local?.tasks ?? []) {
      const metaNode = nodeById.get(task.id);
      if (!metaNode) continue;
      const uniqueHandles: string[] = [];
      for (const edge of input.edges) {
        if (edge.fromNodeId === task.id && edge.sourceHandle && !uniqueHandles.includes(edge.sourceHandle)) {
          uniqueHandles.push(edge.sourceHandle);
        }
      }
      nodes.push({
        id: task.id,
        stageId: stage.stageId,
        label: metaNode.label,
        actorKind: metaNode.actorKind,
        visualKind: metaNode.visualKind,
        x: pos.x + task.x,
        y: pos.y + task.y,
        width: task.width,
        height: task.height,
        kind: "task",
        parentStageId: `stage:${stage.stageId}`,
        relativeX: task.x,
        relativeY: task.y,
        status: metaNode.status,
        attempt: metaNode.attempt,
        primaryAgentId: metaNode.primaryAgentId,
        isRuntimeCurrent: metaNode.isRuntimeCurrent,
        hasPendingHumanTask: metaNode.hasPendingHumanTask,
        blockedReason: metaNode.blockedReason,
        description: metaNode.description,
        primaryRoleKey: metaNode.primaryRoleKey,
        sourceHandleIds: uniqueHandles.length > 0 ? uniqueHandles : undefined,
        decisionOutcomeIds: metaNode.visualKind === "decision" ? [...DECISION_OUTCOME_IDS] : undefined,
        portSides: portSidesByNode.get(task.id),
      });
    }
  }

  const edges: WorkflowLayoutResult["edges"] = input.edges.map((edge) => {
    const orthogonal = orthogonalRoutes.get(edge.edgeId);
    const internal = collectInternalSections(input, localLayouts, edge.edgeId, outer);
    const narrative = orthogonal ? null : serpentineNarrativeRoute(edge, ctx);
    let sections = orthogonal?.sections
      ?? narrative?.sections
      ?? internal
      ?? outer.edgeSections.get(edge.edgeId)
      ?? [];
    if (!internal && !narrative && !orthogonal) {
      // Cross-stage edges: the outer ELK sections start/end at the stage
      // gateway ports; append the internal legs from the source task's right
      // edge to the source gateway and from the target gateway to the target
      // task's left edge, so the final polyline is continuous node-to-node.
      sections = withGatewayStubs(edge, sections, ctx);
    }
    const labelBounds = orthogonal?.labelBounds ?? narrative?.labelBounds ?? (internal
      ? internalLabelBounds(localLayouts, input, edge.edgeId, outer)
      : outer.labelPositions.get(edge.edgeId));
    const visibleLabel = ctx.layoutMode === "serpentine" && !workflowEdgeKeepsNarrativeLabel(edge)
      ? ""
      : edge.label;
    return {
      id: edge.edgeId,
      source: edge.fromNodeId,
      target: edge.toNodeId,
      label: visibleLabel,
      semanticKind: edge.semanticKind,
      pathState: edge.pathState,
      labelAlwaysVisible: edge.labelAlwaysVisible,
      sourceHandle: ctx.sourceHandleByEdge?.get(edge.edgeId) ?? edge.sourceHandle,
      targetHandle: targetHandleByEdge.get(edge.edgeId),
      gateKind: edge.gateKind,
      requiresHumanAccept: edge.requiresHumanAccept,
      sections,
      labelBounds,
    };
  });

  return { nodes, edges, width: outer.size.width, height: outer.size.height };
}

type OrthogonalEdgeRoute = {
  sections: WorkflowLayoutResult["edges"][number]["sections"];
  labelBounds?: WorkflowLayoutResult["edges"][number]["labelBounds"];
};

function collectTaskBoxes(ctx: ComposerInput): Map<string, OrthogonalRect> {
  const boxes = new Map<string, OrthogonalRect>();
  for (const stage of ctx.input.stages) {
    const pos = ctx.outer.stagePositions.get(stage.stageId);
    const local = ctx.localLayouts.get(stage.stageId);
    if (!pos || !local) continue;
    for (const task of local.tasks) {
      boxes.set(task.id, {
        x: pos.x + task.x,
        y: pos.y + task.y,
        width: task.width,
        height: task.height,
      });
    }
  }
  return boxes;
}

function applySerpentineOrthogonalRoutes(
  ctx: ComposerInput,
  boxes: Map<string, OrthogonalRect>,
): Map<string, OrthogonalEdgeRoute> {
  const routes = new Map<string, OrthogonalEdgeRoute>();
  const planned: Array<{
    edgeId: string;
    fromNodeId: string;
    toNodeId: string;
    label: string;
    sourceHandle: string;
    targetHandle: string;
    source: OrthogonalRect;
    target: OrthogonalRect;
  }> = [];

  for (const edge of ctx.input.edges) {
    if (edge.semanticKind === "rerun") continue;
    const source = boxes.get(edge.fromNodeId);
    const target = boxes.get(edge.toNodeId);
    if (!source || !target) continue;
    const sourceHandle = ctx.sourceHandleByEdge?.get(edge.edgeId) ?? edge.sourceHandle;
    const targetHandle = ctx.targetHandleByEdge.get(edge.edgeId);
    if (!sourceHandle || !targetHandle) continue;
    planned.push({
      edgeId: edge.edgeId,
      fromNodeId: edge.fromNodeId,
      toNodeId: edge.toNodeId,
      label: edge.label,
      sourceHandle,
      targetHandle,
      source,
      target,
    });
  }

  const obstacles = [...boxes.values()];
  const firstPass = planned.map((item) => ({
    item,
    routed: routeOrthogonalConnector({ source: item.source, target: item.target, obstacles }),
  }));
  const sourceFractionByEdge = sameSideFractions(
    firstPass.map(({ item, routed }) => ({
      edgeId: item.edgeId,
      nodeId: item.fromNodeId,
      side: routed.sourceSide,
      rect: item.source,
      far: item.target,
    })),
  );
  const targetFractionByEdge = sameSideFractions(
    firstPass.map(({ item, routed }) => ({
      edgeId: item.edgeId,
      nodeId: item.toNodeId,
      side: routed.targetSide,
      rect: item.target,
      far: item.source,
    })),
  );

  for (const { item, routed: first } of firstPass) {
    const sourceFraction = sourceFractionByEdge.get(item.edgeId) ?? 0.5;
    const targetFraction = targetFractionByEdge.get(item.edgeId) ?? 0.5;
    const routed = routeOrthogonalConnector({
      source: item.source,
      target: item.target,
      sourceSide: first.sourceSide,
      targetSide: first.targetSide,
      sourceFraction,
      targetFraction,
      obstacles,
    });
    assignPortSide(
      ctx.portSidesByNode,
      item.fromNodeId,
      "source",
      item.sourceHandle,
      elkSideFromOrthogonal(routed.sourceSide),
      sourceFraction,
    );
    assignPortSide(
      ctx.portSidesByNode,
      item.toNodeId,
      "target",
      item.targetHandle,
      elkSideFromOrthogonal(routed.targetSide),
      targetFraction,
    );
    routes.set(item.edgeId, {
      sections: sectionsFromPoints(item.edgeId, routed.points),
      labelBounds: orthogonalLabelBounds(item.label, routed.points),
    });
  }
  return routes;
}

function sameSideFractions(
  items: Array<{
    edgeId: string;
    nodeId: string;
    side: OrthogonalSide;
    rect: OrthogonalRect;
    far: OrthogonalRect;
  }>,
): Map<string, number> {
  const fractions = new Map<string, number>();
  const groups = new Map<string, typeof items>();
  for (const item of items) {
    const key = `${item.nodeId}:${item.side}`;
    const list = groups.get(key) ?? [];
    list.push(item);
    groups.set(key, list);
  }
  for (const list of groups.values()) {
    const assigned = assignSnapFractions(
      list.map((item) => ({
        id: item.edgeId,
        preferred: projectedSnapFraction(item.rect, item.side, item.far),
      })),
      snapSlotsForSide(list[0]!.side),
    );
    for (const [edgeId, fraction] of assigned) {
      fractions.set(edgeId, fraction);
    }
  }
  return fractions;
}

function assignPortSide(
  portSidesByNode: Map<string, WorkflowLayoutNode["portSides"]>,
  nodeId: string,
  role: "source" | "target",
  handleId: string,
  side: WorkflowPortSide,
  fraction: number,
): void {
  const current = portSidesByNode.get(nodeId) ?? { source: {}, target: {} };
  if (role === "source") {
    portSidesByNode.set(nodeId, {
      source: { ...current.source, [handleId]: side },
      target: { ...current.target },
      sourceAnchor: { ...current.sourceAnchor, [handleId]: fraction },
      targetAnchor: current.targetAnchor,
    });
    return;
  }
  portSidesByNode.set(nodeId, {
    source: { ...current.source },
    target: { ...current.target, [handleId]: side },
    sourceAnchor: current.sourceAnchor,
    targetAnchor: { ...current.targetAnchor, [handleId]: fraction },
  });
}

function orthogonalLabelBounds(
  label: string,
  points: WorkflowLayoutPoint[],
): WorkflowLayoutResult["edges"][number]["labelBounds"] {
  if (!label) return undefined;
  const spec = resolveEdgeLabelSpec(label);
  const anchor = longestStrokeLabelAnchor(points);
  if (!anchor) return undefined;
  if (longestStrokeIsVertical(points)) {
    return {
      x: anchor.x + 10,
      y: anchor.y - spec.height / 2,
      width: spec.width,
      height: spec.height,
    };
  }
  return {
    x: anchor.x - spec.width / 2,
    y: anchor.y - spec.height - 4,
    width: spec.width,
    height: spec.height,
  };
}

/**
 * Serpentine presentation uses two deterministic narrative routes instead of
 * exposing ELK gateway drift to users:
 *  - ordinary edges use the facing-side orthogonal connector after ELK places
 *    the cards;
 *  - rerun feedback hugs the bottom of its stage rather than encircling the
 *    whole stage graph.
 * ELK still owns task order, stage positions and the space budget.
 */
function serpentineNarrativeRoute(
  edge: WorkflowLayoutInput["edges"][number],
  ctx: ComposerInput,
): {
  sections: WorkflowLayoutResult["edges"][number]["sections"];
  labelBounds?: WorkflowLayoutResult["edges"][number]["labelBounds"];
} | null {
  if (ctx.layoutMode !== "serpentine") return null;
  if (edge.semanticKind !== "rerun") return null;
  const sourceMeta = ctx.input.nodes.find((node) => node.nodeId === edge.fromNodeId);
  const targetMeta = ctx.input.nodes.find((node) => node.nodeId === edge.toNodeId);
  if (!sourceMeta || !targetMeta) return null;
  const sourceLocal = ctx.localLayouts.get(sourceMeta.stageId);
  const targetLocal = ctx.localLayouts.get(targetMeta.stageId);
  const sourceStagePosition = ctx.outer.stagePositions.get(sourceMeta.stageId);
  const targetStagePosition = ctx.outer.stagePositions.get(targetMeta.stageId);
  const sourceTask = sourceLocal?.tasks.find((task) => task.id === edge.fromNodeId);
  const targetTask = targetLocal?.tasks.find((task) => task.id === edge.toNodeId);
  if (!sourceLocal || !targetLocal || !sourceStagePosition || !targetStagePosition || !sourceTask || !targetTask) {
    return null;
  }

  const stageBox = ctx.stageBoxes.get(sourceMeta.stageId);
  if (!stageBox) return null;
  const source = offset(
    { x: sourceTask.x, y: sourceTask.y + sourceTask.height / 2 },
    sourceStagePosition,
  );
  const target = offset(
    { x: targetTask.x + targetTask.width, y: targetTask.y + targetTask.height / 2 },
    targetStagePosition,
  );
  const railY = sourceStagePosition.y + stageBox.height - 18;
  const points = compactPoints([
    source,
    { x: source.x - 16, y: source.y },
    { x: source.x - 16, y: railY },
    { x: target.x + 16, y: railY },
    { x: target.x + 16, y: target.y },
    target,
  ]);
  return {
    sections: sectionsFromPoints(edge.edgeId, points),
    labelBounds: aboveHorizontalStrokeLabelBounds(edge.label, (source.x + target.x) / 2, railY),
  };
}

function compactPoints(points: WorkflowLayoutPoint[]): WorkflowLayoutPoint[] {
  return points.filter((point, index) => {
    const previous = points[index - 1];
    return !previous || Math.abs(previous.x - point.x) > 1e-3 || Math.abs(previous.y - point.y) > 1e-3;
  });
}

function sectionsFromPoints(
  edgeId: string,
  points: WorkflowLayoutPoint[],
): WorkflowLayoutResult["edges"][number]["sections"] {
  const sections = points.slice(0, -1).map((point, index) =>
    section(`${edgeId}_narrative_${index}`, point, points[index + 1]!),
  );
  return linkSections(sections);
}

/** Sit the pill above a horizontal feedback rail so the stroke does not bisect the text. */
function aboveHorizontalStrokeLabelBounds(
  label: string,
  centerX: number,
  strokeY: number,
): WorkflowLayoutResult["edges"][number]["labelBounds"] {
  if (!label) return undefined;
  const spec = resolveEdgeLabelSpec(label);
  return {
    x: centerX - spec.width / 2,
    y: strokeY - spec.height - 4,
    width: spec.width,
    height: spec.height,
  };
}

/**
 * Prepends/appends the internal node-to-gateway legs for a cross-stage edge.
 *
 * The outer ELK graph routes between stage gateway ports, so its sections
 * begin at the source stage's EAST edge (at the Y the engine chose for the
 * port) and end at the target stage's WEST edge. ELK's layered algorithm does
 * NOT honor fixed port coordinates (probed: FIXED_POS/FIXED_RATIO/anchors are
 * ignored; ports float), so the composer bridges from the actual task port to
 * the engine's chosen channel entry:
 *
 *   src task right edge --horizontal--> stage EAST edge
 *   stage EAST edge ----vertical (if Y differs)--> engine channel Y
 *   ...engine sections...
 *   engine channel Y ----vertical (if Y differs)--> target stage WEST edge
 *   target stage WEST edge --horizontal--> tgt task left edge
 *
 * The polyline is fully orthogonal, node-to-node continuous, and the section
 * chain stays well-formed (symmetric declaration, geometric joins).
 */
function withGatewayStubs(
  edge: WorkflowLayoutInput["edges"][number],
  sections: WorkflowLayoutResult["edges"][number]["sections"],
  ctx: ComposerInput,
): WorkflowLayoutResult["edges"][number]["sections"] {
  if (sections.length === 0) {
    return sections;
  }
  const { input, localLayouts, outer, stageBoxes } = ctx;
  const sourceNode = input.nodes.find((n) => n.nodeId === edge.fromNodeId);
  const targetNode = input.nodes.find((n) => n.nodeId === edge.toNodeId);
  if (!sourceNode || !targetNode || sourceNode.stageId === targetNode.stageId) {
    return sections;
  }
  const srcLocal = localLayouts.get(sourceNode.stageId);
  const tgtLocal = localLayouts.get(targetNode.stageId);
  const srcPos = outer.stagePositions.get(sourceNode.stageId);
  const tgtPos = outer.stagePositions.get(targetNode.stageId);
  const srcBox = stageBoxes.get(sourceNode.stageId);
  if (!srcLocal || !tgtLocal || !srcPos || !tgtPos || !srcBox) {
    return sections;
  }
  const srcTask = srcLocal.tasks.find((t) => t.id === edge.fromNodeId);
  const tgtTask = tgtLocal.tasks.find((t) => t.id === edge.toNodeId);
  if (!srcTask || !tgtTask) {
    return sections;
  }

  if (ctx.layoutMode === "serpentine") {
    return withVerticalGatewayStubs(edge, sections, {
      sourceTask: srcTask,
      targetTask: tgtTask,
      sourceStagePosition: srcPos,
      targetStagePosition: tgtPos,
      sourceStageBox: srcBox,
    });
  }

  const first = sections[0];
  const last = sections[sections.length - 1];
  const srcAnchorY = srcTask.y + srcTask.height / 2;
  const tgtAnchorY = tgtTask.y + tgtTask.height / 2;
  const engineSrcY = first.start.y;
  const engineTgtY = last.end.y;

  const srcPort: { x: number; y: number } = offset({ x: srcTask.x + srcTask.width, y: srcAnchorY }, srcPos);
  const srcBorder: { x: number; y: number } = offset({ x: srcBox.width, y: srcAnchorY }, srcPos);
  const tgtBorder: { x: number; y: number } = offset({ x: 0, y: tgtAnchorY }, tgtPos);
  const tgtPort: { x: number; y: number } = offset({ x: tgtTask.x, y: tgtAnchorY }, tgtPos);

  const srcStubs: WorkflowLayoutResult["edges"][number]["sections"] = [];
  srcStubs.push({
    id: `${edge.edgeId}_src_exit`,
    start: srcPort,
    end: srcBorder,
    bendPoints: [],
    incomingSectionIds: [],
    outgoingSectionIds: [],
  });
  if (Math.abs(srcBorder.y - engineSrcY) > 1e-3) {
    srcStubs.push({
      id: `${edge.edgeId}_src_drop`,
      start: srcBorder,
      end: { x: srcBorder.x, y: engineSrcY },
      bendPoints: [],
      incomingSectionIds: [],
      outgoingSectionIds: [],
    });
  }
  const tgtStubs: WorkflowLayoutResult["edges"][number]["sections"] = [];
  if (Math.abs(tgtBorder.y - engineTgtY) > 1e-3) {
    tgtStubs.push({
      id: `${edge.edgeId}_tgt_drop`,
      start: { x: tgtBorder.x, y: engineTgtY },
      end: tgtBorder,
      bendPoints: [],
      incomingSectionIds: [],
      outgoingSectionIds: [],
    });
  }
  tgtStubs.push({
    id: `${edge.edgeId}_tgt_enter`,
    start: tgtBorder,
    end: tgtPort,
    bendPoints: [],
    incomingSectionIds: [],
    outgoingSectionIds: [],
  });

  for (let i = 0; i < srcStubs.length; i += 1) {
    srcStubs[i]!.outgoingSectionIds = [i + 1 < srcStubs.length ? srcStubs[i + 1]!.id : first.id];
    if (i > 0) {
      srcStubs[i]!.incomingSectionIds = [srcStubs[i - 1]!.id];
    }
  }
  for (let i = 0; i < tgtStubs.length; i += 1) {
    tgtStubs[i]!.incomingSectionIds = [i > 0 ? tgtStubs[i - 1]!.id : last.id];
    if (i + 1 < tgtStubs.length) {
      tgtStubs[i]!.outgoingSectionIds = [tgtStubs[i + 1]!.id];
    }
  }

  const updatedSections = sections.map((s) => {
    let next = s;
    if (s.id === first.id) {
      next = { ...next, incomingSectionIds: [srcStubs[srcStubs.length - 1]!.id] };
    }
    if (s.id === last.id) {
      next = { ...next, outgoingSectionIds: [tgtStubs[0]!.id] };
    }
    return next;
  });
  return [...srcStubs, ...updatedSections, ...tgtStubs];
}

function withVerticalGatewayStubs(
  edge: WorkflowLayoutInput["edges"][number],
  sections: WorkflowLayoutResult["edges"][number]["sections"],
  geometry: {
    sourceTask: StageLocalLayout["tasks"][number];
    targetTask: StageLocalLayout["tasks"][number];
    sourceStagePosition: { x: number; y: number };
    targetStagePosition: { x: number; y: number };
    sourceStageBox: Rect;
  },
): WorkflowLayoutResult["edges"][number]["sections"] {
  const first = sections[0];
  const last = sections[sections.length - 1];
  if (!first || !last) return sections;

  const srcAnchorX = geometry.sourceTask.x + geometry.sourceTask.width / 2;
  const tgtAnchorX = geometry.targetTask.x + geometry.targetTask.width / 2;
  const srcPort = offset(
    { x: srcAnchorX, y: geometry.sourceTask.y + geometry.sourceTask.height },
    geometry.sourceStagePosition,
  );
  const srcBorder = offset(
    { x: srcAnchorX, y: geometry.sourceStageBox.height },
    geometry.sourceStagePosition,
  );
  const tgtBorder = offset({ x: tgtAnchorX, y: 0 }, geometry.targetStagePosition);
  const tgtPort = offset({ x: tgtAnchorX, y: geometry.targetTask.y }, geometry.targetStagePosition);

  const srcStubs: WorkflowLayoutResult["edges"][number]["sections"] = [
    section(`${edge.edgeId}_src_exit`, srcPort, srcBorder),
  ];
  if (Math.abs(srcBorder.x - first.start.x) > 1e-3) {
    srcStubs.push(section(`${edge.edgeId}_src_shift`, srcBorder, { x: first.start.x, y: srcBorder.y }));
  }

  const tgtStubs: WorkflowLayoutResult["edges"][number]["sections"] = [];
  if (Math.abs(tgtBorder.x - last.end.x) > 1e-3) {
    tgtStubs.push(section(`${edge.edgeId}_tgt_shift`, { x: last.end.x, y: tgtBorder.y }, tgtBorder));
  }
  tgtStubs.push(section(`${edge.edgeId}_tgt_enter`, tgtBorder, tgtPort));

  return linkSections([...srcStubs, ...sections, ...tgtStubs]);
}

function section(
  id: string,
  start: { x: number; y: number },
  end: { x: number; y: number },
): WorkflowLayoutResult["edges"][number]["sections"][number] {
  return {
    id,
    start,
    end,
    bendPoints: [],
    incomingSectionIds: [],
    outgoingSectionIds: [],
  };
}

function linkSections(
  sections: WorkflowLayoutResult["edges"][number]["sections"],
): WorkflowLayoutResult["edges"][number]["sections"] {
  return sections.map((item, index) => ({
    ...item,
    incomingSectionIds: index > 0 ? [sections[index - 1]!.id] : [],
    outgoingSectionIds: index + 1 < sections.length ? [sections[index + 1]!.id] : [],
  }));
}

/** Internal edge sections: local sections offset by the outer stage position. */
function collectInternalSections(
  input: WorkflowLayoutInput,
  localLayouts: Map<string, StageLocalLayout>,
  edgeId: string,
  outer: OuterLayoutResult,
): WorkflowLayoutResult["edges"][number]["sections"] | undefined {
  const edge = input.edges.find((e) => e.edgeId === edgeId);
  if (!edge) return undefined;
  const stageId = input.nodes.find((n) => n.nodeId === edge.fromNodeId)?.stageId;
  const local = localLayouts.get(stageId ?? "");
  const pos = outer.stagePositions.get(stageId ?? "");
  if (!local || !pos) return undefined;
  const internalEdge = local.internalEdges.find((ie) => ie.id === edgeId);
  if (!internalEdge) return undefined;
  return (internalEdge.sections ?? []).map((s, i) => ({
    id: `${edgeId}_s${i}`,
    start: offset(s.startPoint, pos),
    end: offset(s.endPoint, pos),
    bendPoints: (s.bendPoints ?? []).map((p) => offset(p, pos)),
    incomingSectionIds: s.incomingSections ? [...s.incomingSections] : [],
    outgoingSectionIds: s.outgoingSections ? [...s.outgoingSections] : [],
  }));
}

function internalLabelBounds(
  localLayouts: Map<string, StageLocalLayout>,
  input: WorkflowLayoutInput,
  edgeId: string,
  outer: OuterLayoutResult,
): WorkflowLayoutResult["edges"][number]["labelBounds"] {
  const edge = input.edges.find((e) => e.edgeId === edgeId);
  if (!edge) return undefined;
  const stageId = input.nodes.find((n) => n.nodeId === edge.fromNodeId)?.stageId;
  const local = localLayouts.get(stageId ?? "");
  const pos = outer.stagePositions.get(stageId ?? "");
  if (!local || !pos) return undefined;
  const internalEdge = local.internalEdges.find((ie) => ie.id === edgeId);
  const label = internalEdge?.label;
  if (!label) return undefined;
  return {
    x: label.x + pos.x,
    y: label.y + pos.y,
    width: label.width,
    height: label.height,
  };
}

function offset(p: WorkflowLayoutPoint, by: { x: number; y: number }): WorkflowLayoutPoint {
  return { x: p.x + by.x, y: p.y + by.y };
}
