import { createMemoryGraphLabelElements as createOriginalLabels, positionMemoryGraphLabels as positionOriginalLabels } from "./memoryGraphLabels";
import { memoryGraphRendererStyles as styles } from "./memoryGraphRenderer.styles";
export { buildMemoryGraphAdjacency } from "./memoryGraphLabels";
export type { MemoryGraphLabelElements, MemoryGraphEdgePath } from "./memoryGraphLabels";

type Placement = { offsetY: number; width: number; height: number };
type Labels = Parameters<typeof positionOriginalLabels>[0]["elements"];
type LabelRect = { x: number; y: number; w: number; h: number };
const layouts = new WeakMap<Labels, {
  key: string;
  mode: "overview" | "detail";
  placements: Map<string, Placement>;
  edgePlacements: Map<string, Placement>;
}>();

export const createMemoryGraphCosmosLabelElements: typeof createOriginalLabels = (...args) => {
  const elements = createOriginalLabels(...args);
  for (const node of args[1]) {
    const button = elements.nodeButtons.get(node.id)!;
    // Keep summaries in the inspector; hover must not resize projected labels.
    if (button.children.length > 1) button.children[1].remove();
    button.title = node.source.label;
    const title = button.querySelector("span")!;
    title.className = styles.cosmosLabelTitle;
    title.textContent = node.source.type === "topic" ? node.clusterLabel : node.source.label;
    if (node.source.type === "topic") {
      button.className = styles.cosmosTopicLabel;
      const count = document.createElement("span");
      count.className = styles.cosmosCount;
      count.textContent = String(node.source.metadata.memberCount ?? 0) + " 条知识";
      button.append(count);
    } else {
      button.className = styles.cosmosRecordLabel;
    }
  }
  for (const edge of args[2]) {
    const button = elements.edgeButtons.get(edge.id)!;
    button.className = styles.cosmosEdgeLabel;
    const title = document.createElement("span");
    title.className = styles.cosmosLabelTitle;
    title.textContent = (edge.metadata.status === "candidate" ? "待确认 · " : "") + (edge.label || edge.type);
    button.replaceChildren(title);
    button.dataset.relationLayer = String(edge.metadata.layer);
    button.title = edge.label || edge.type;
  }
  return elements;
};

export const positionMemoryGraphCosmosLabels = (options: Parameters<typeof positionOriginalLabels>[0] & { moving: boolean }) => {
  // Read host geometry once before writing styles. Never hide a caption just
  // to measure it, including during drag, inertia and automatic orbit.
  const width = options.host.clientWidth;
  const height = options.host.clientHeight;
  const roots = options.nodes.filter(node => node.source.type === "topic");
  const selected = options.nodes.find(node => node.id === options.selectedNodeId);
  const distance = options.camera.position.distanceTo(options.cameraTarget);
  const proposedMode = selected || options.highlightIds.size || distance < 25 ? "detail" : "overview";
  const key = [options.selectedNodeId, [...options.highlightIds].sort().join(","), width, height, options.labelsVisible].join(":");
  const previousState = layouts.get(options.elements);
  const mode = options.moving && previousState?.key === key ? previousState.mode : proposedMode;
  options.labelLayer.parentElement!.dataset.zoomLevel = mode;

  const projections = new Map<string, { x: number; y: number; visible: boolean }>();
  const project = (node: typeof options.nodes[number]) => {
    const existing = projections.get(node.id);
    if (existing) return existing;
    const point = options.scratch.set(node.x, node.y, node.z).project(options.camera);
    const projected = {
      x: (point.x * 0.5 + 0.5) * width,
      y: (-point.y * 0.5 + 0.5) * height,
      visible: point.z >= -1 && point.z <= 1,
    };
    projections.set(node.id, projected);
    return projected;
  };

  const previous = previousState?.key === key ? previousState.placements : new Map<string, Placement>();
  const focusCluster = selected?.source.type === "topic" ? selected.clusterKey : undefined;
  const matchingNodes = options.highlightIds.size
    ? options.nodes.filter(node => options.highlightIds.has(node.id))
    : roots.length && !selected && (mode === "overview" || roots.length === options.nodes.length)
      ? roots
      : options.nodes.filter(node => focusCluster
        ? node.clusterKey === focusCluster
        : selected ? options.adjacent.get(selected.id)?.has(node.id) : node.source.type !== "topic");
  // Selection wins even when it is outside the current search highlights.
  const candidates = selected ? [selected, ...matchingNodes.filter(node => node.id !== selected.id)] : matchingNodes;
  const placements = new Map<string, Placement>();
  const occupied: LabelRect[] = [];
  const budget = selected ? 12 : roots.length && mode === "overview" ? 10 : 14;
  const clusterTops = new Map<string, number>();
  if (candidates.some(node => node.source.type === "topic")) {
    for (const node of options.nodes) {
      const point = project(node);
      if (point.visible) clusterTops.set(node.clusterKey, Math.min(clusterTops.get(node.clusterKey) ?? Infinity, point.y));
    }
  }

  const findY = (candidatesY: number[], x: number, w: number, h: number) => candidatesY.find(y =>
    y - h / 2 >= 12 && y + h / 2 <= height - 12 &&
    !occupied.some(rect => Math.abs(rect.x - x) < (rect.w + w) / 2 + 5 && Math.abs(rect.y - y) < (rect.h + h) / 2 + 3));

  // Re-evaluate projected rectangles every frame. Try the previous anchor
  // offset first so motion only displaces labels whose current slot collides.
  for (const node of candidates) {
    if (placements.size >= budget || !options.labelsVisible) break;
    const anchor = project(node);
    if (!anchor.visible || anchor.x < 12 || anchor.x > width - 12 || anchor.y < 12 || anchor.y > height - 16) continue;
    const topic = node.source.type === "topic";
    const text = topic ? node.clusterLabel : node.source.label;
    const w = Math.min(320, width - 28, Math.max(104, text.length * (topic ? 15 : 7) + 24));
    const h = topic ? 46 : 32;
    const x = Math.max(w / 2 + 12, Math.min(width - w / 2 - 12, anchor.x));
    const top = (clusterTops.get(node.clusterKey) ?? anchor.y) - 22;
    const old = previous.get(node.id);
    const offsets = topic ? [top, anchor.y + 38, anchor.y - 38, anchor.y + 65]
      : [anchor.y - 25, anchor.y + 25, anchor.y - 62, anchor.y + 62, anchor.y - 99, anchor.y + 99];
    const y = findY([...(old ? [anchor.y + old.offsetY] : []), ...offsets], x, w, h);
    if (y === undefined) continue;
    placements.set(node.id, { offsetY: y - anchor.y, width: w, height: h });
    occupied.push({ x, y, w, h });
  }

  const edgePlacements = new Map<string, Placement>();
  const canSelectEdge = options.canSelectEdge();
  if (options.labelsVisible && canSelectEdge) {
    for (const path of options.edgePaths) {
      if (edgePlacements.size >= 5) break;
      const connected = selected && selected.source.type !== "topic" && (path.edge.source === selected.id || path.edge.target === selected.id);
      const highlighted = options.highlightIds.has(path.edge.source) && options.highlightIds.has(path.edge.target);
      if (!connected && !highlighted) continue;
      const point = path.curve.getPoint(0.5).project(options.camera);
      const anchor = { x: (point.x * 0.5 + 0.5) * width, y: (-point.y * 0.5 + 0.5) * height };
      if (point.z < -1 || point.z > 1 || anchor.x < 16 || anchor.x > width - 16 || anchor.y < 24 || anchor.y > height - 24) continue;
      const text = path.edge.label || path.edge.type;
      const w = Math.min(320, width - 28, Math.max(64, text.length * 14 + 28));
      const h = 32;
      const x = Math.max(w / 2 + 12, Math.min(width - w / 2 - 12, anchor.x));
      const old = previousState?.key === key ? previousState.edgePlacements.get(path.edge.id) : undefined;
      const y = findY([...(old ? [anchor.y + old.offsetY] : []), anchor.y, anchor.y - 37, anchor.y + 37, anchor.y + 74], x, w, h);
      if (y === undefined) continue;
      edgePlacements.set(path.edge.id, { offsetY: y - anchor.y, width: w, height: h });
      occupied.push({ x, y, w, h });
    }
  }

  layouts.set(options.elements, { key, mode, placements, edgePlacements });
  for (const node of options.nodes) {
    const button = options.elements.nodeButtons.get(node.id)!;
    const placement = placements.get(node.id);
    if (!placement) {
      if (button.style.display !== "none") button.style.display = "none";
      continue;
    }
    const anchor = project(node);
    const x = Math.max(placement.width / 2 + 12, Math.min(width - placement.width / 2 - 12, anchor.x));
    button.style.left = x + "px";
    button.style.top = anchor.y + placement.offsetY + "px";
    button.style.width = placement.width + "px";
    button.style.visibility = "visible";
    if (button.style.display !== "grid") button.style.display = "grid";
    const pressed = String(node.id === options.selectedNodeId);
    if (button.getAttribute("aria-pressed") !== pressed) button.setAttribute("aria-pressed", pressed);
  }
  for (const path of options.edgePaths) {
    const button = options.elements.edgeButtons.get(path.edge.id)!;
    button.disabled = !canSelectEdge;
    const placement = edgePlacements.get(path.edge.id);
    if (!placement) {
      if (button.style.display !== "none") button.style.display = "none";
      continue;
    }
    const point = path.curve.getPoint(0.5).project(options.camera);
    const x = Math.max(placement.width / 2 + 12, Math.min(width - placement.width / 2 - 12, (point.x * 0.5 + 0.5) * width));
    button.style.left = x + "px";
    button.style.top = (-point.y * 0.5 + 0.5) * height + placement.offsetY + "px";
    button.style.width = placement.width + "px";
    button.style.visibility = "visible";
    if (button.style.display !== "grid") button.style.display = "grid";
  }
  return mode;
};
