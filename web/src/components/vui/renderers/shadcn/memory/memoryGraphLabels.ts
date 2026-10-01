import type {
  Camera,
  QuadraticBezierCurve3,
  Vector3,
} from "three";
import type {
  MemoryKnowledgeGraphEdge,
  MemoryKnowledgeGraphNode,
} from "../../../../../api/types";
import type {
  MemoryGraphCluster,
  PositionedMemoryKnowledgeGraphNode,
} from "../../../product/memory/memoryGraphModel";
import { memoryGraphRendererStyles as styles } from "./memoryGraphRenderer.styles";

export type MemoryGraphZoomLevel = "overview" | "topic" | "detail";

export type MemoryGraphLabelElements = {
  nodeButtons: Map<string, HTMLButtonElement>;
  edgeButtons: Map<string, HTMLButtonElement>;
  clusterHeadings: Map<string, HTMLDivElement>;
};

export type MemoryGraphEdgePath = {
  edge: MemoryKnowledgeGraphEdge;
  curve: QuadraticBezierCurve3;
};

const LABEL_BUDGETS: Record<MemoryGraphZoomLevel, number> = {
  overview: 5,
  topic: 13,
  detail: 28,
};

function oneLine(value: string, limit: number): string {
  const text = String(value ?? "").replace(/\s+/g, " ").trim();
  return text.length > limit ? text.slice(0, Math.max(0, limit - 1)).trimEnd() + "…" : text;
}

function kindLabel(node: MemoryKnowledgeGraphNode): string {
  const labels: Record<string, string> = {
    project: "项目",
    team: "团队",
    agent: "Agent",
    agent_private_memory: "Agent 私有记忆",
    knowledge_base: "知识库",
    knowledge_item: "知识条目",
    source_artifact: "来源材料",
    refinement_proposal: "修订建议",
    knowledge_batch: "知识批次",
    rating_suggestion: "评价建议",
    runtime_scene: "运行场景",
    evolution: "进化记录",
    supervision: "监督记录",
    tag: "标签",
    concept: "概念",
  };
  return labels[node.type] ?? node.type;
}

export function createMemoryGraphLabelElements(
  layer: HTMLDivElement,
  nodes: readonly PositionedMemoryKnowledgeGraphNode[],
  edges: readonly MemoryKnowledgeGraphEdge[],
  clusters: readonly MemoryGraphCluster[],
  onSelectNode: (id: string) => void,
  onSelectEdge: (id: string) => void,
  canSelectEdge: () => boolean,
): MemoryGraphLabelElements {
  const nodeButtons = new Map<string, HTMLButtonElement>();
  const edgeButtons = new Map<string, HTMLButtonElement>();
  const clusterHeadings = new Map<string, HTMLDivElement>();
  const summaryElements = new Map<string, HTMLElement>();

  for (const cluster of clusters) {
    const heading = document.createElement("div");
    heading.className = styles.clusterLabel;
    heading.style.display = "none";
    heading.dataset.clusterKey = cluster.key;
    heading.setAttribute("role", "heading");
    heading.setAttribute("aria-level", "2");
    heading.textContent = cluster.label;
    layer.append(heading);
    clusterHeadings.set(cluster.key, heading);
  }

  for (const edge of edges) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = styles.edgeLabel;
    button.style.display = "none";
    button.dataset.edgeId = edge.id;
    button.dataset.edgeType = edge.type;
    button.setAttribute("aria-label", "选择关系：" + (edge.label || edge.type) + "（" + edge.type + "）");
    button.textContent = oneLine(edge.label || edge.type, 28);
    button.disabled = !canSelectEdge();
    button.addEventListener("click", () => onSelectEdge(edge.id));
    layer.append(button);
    edgeButtons.set(edge.id, button);
  }

  for (const viewNode of nodes) {
    const node = viewNode.source;
    const button = document.createElement("button");
    button.type = "button";
    button.className = styles.nodeLabel;
    button.style.display = "none";
    button.dataset.nodeId = node.id;
    button.dataset.nodeType = node.type;
    button.dataset.clusterKey = viewNode.clusterKey;
    button.dataset.worldPosition = [viewNode.x, viewNode.y, viewNode.z].join(",");
    button.setAttribute(
      "aria-label",
      [node.label, kindLabel(node), viewNode.clusterLabel, node.summary].filter(Boolean).join("，"),
    );
    button.setAttribute("aria-pressed", "false");

    const title = document.createElement("span");
    title.className = styles.nodeLabelTitle;
    title.textContent = oneLine(node.label, 64);
    button.append(title);

    if (node.summary) {
      const summary = document.createElement("span");
      summary.className = styles.nodeLabelSummary;
      summary.textContent = oneLine(node.summary, 82);
      button.append(summary);
      summaryElements.set(node.id, summary);
    }

    button.addEventListener("click", () => onSelectNode(node.id));
    layer.append(button);
    nodeButtons.set(node.id, button);
  }

  const elements = { nodeButtons, edgeButtons, clusterHeadings };
  labelLayoutStates.set(elements, createLabelLayoutState(summaryElements));
  return elements;
}

export function buildMemoryGraphAdjacency(
  nodes: readonly PositionedMemoryKnowledgeGraphNode[],
  edges: readonly MemoryKnowledgeGraphEdge[],
): { adjacent: Map<string, Set<string>>; degree: Map<string, number> } {
  const nodeIds = new Set(nodes.map((node) => node.id));
  const adjacent = new Map<string, Set<string>>();
  const degree = new Map<string, number>();
  for (const id of nodeIds) {
    adjacent.set(id, new Set());
    degree.set(id, 0);
  }
  for (const edge of edges) {
    if (!nodeIds.has(edge.source) || !nodeIds.has(edge.target)) continue;
    adjacent.get(edge.source)?.add(edge.target);
    adjacent.get(edge.target)?.add(edge.source);
    degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1);
    degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1);
  }
  return { adjacent, degree };
}

type LabelRect = {
  left: number;
  right: number;
  top: number;
  bottom: number;
};

type NodeCircle = { x: number; y: number; radius: number };
type LabelSize = { width: number; height: number };
type CachedLabelSize = LabelSize & { version: number; variant: string };
type CardKind = "node" | "edge" | "cluster";
type CardPosition = { x: number; y: number };

type CardRequest = {
  kind: CardKind;
  id: string;
  element: HTMLElement;
  x: number;
  y: number;
  radius: number;
  exceptNodeId?: string;
  variant: string;
  size?: LabelSize;
  position?: CardPosition;
};

type CandidateCache = {
  nodes: readonly PositionedMemoryKnowledgeGraphNode[];
  adjacent: Map<string, Set<string>>;
  degree: Map<string, number>;
  clusters: readonly MemoryGraphCluster[];
  selectedNodeId: string;
  highlightIds: ReadonlySet<string>;
  zoom: MemoryGraphZoomLevel;
  areaScale: number;
  ids: string[];
  budget: number;
};

type LayoutEnvironment = {
  width: number;
  height: number;
  viewportWidth: number;
  viewportHeight: number;
  devicePixelRatio: number;
  fontStatus: string;
  fontReady: Promise<FontFaceSet> | undefined;
  themeFingerprint: string;
  styleSignature: string;
};

type MemoryGraphLabelLayoutState = {
  sizes: WeakMap<HTMLElement, CachedLabelSize>;
  summaryElements: Map<string, HTMLElement>;
  visibleNodes: Set<string>;
  visibleEdges: Set<string>;
  visibleClusters: Set<string>;
  nodeVisualStates: Map<string, string>;
  edgeVisualStates: Map<string, string>;
  lastNodeVisualNodes: readonly PositionedMemoryKnowledgeGraphNode[] | null;
  lastNodeVisualSelected: string | null;
  lastNodeVisualHighlights: ReadonlySet<string> | null;
  lastEdgeVisualPaths: readonly MemoryGraphEdgePath[] | null;
  lastEdgeVisualSelected: string | null;
  lastEdgeSelectable: boolean | null;
  nodesRef: readonly PositionedMemoryKnowledgeGraphNode[] | null;
  clustersRef: readonly MemoryGraphCluster[] | null;
  nodesById: Map<string, PositionedMemoryKnowledgeGraphNode>;
  clusterAnchors: Map<string, { center: { x: number; y: number; z: number }; topMemberY: number }>;
  candidateCache: CandidateCache | null;
  edgePathsRef: readonly MemoryGraphEdgePath[] | null;
  relatedEdgesByNode: Map<string, MemoryGraphEdgePath[]>;
  layoutVersion: number;
  layoutEnvironment: LayoutEnvironment | null;
  zoom: MemoryGraphZoomLevel | null;
};

const labelLayoutStates = new WeakMap<MemoryGraphLabelElements, MemoryGraphLabelLayoutState>();
const EMPTY_NODE_IDS: ReadonlySet<string> = new Set();
const MAX_VISIBLE_NODE_LABELS = 32;

function createLabelLayoutState(
  summaryElements: Map<string, HTMLElement>,
): MemoryGraphLabelLayoutState {
  return {
    sizes: new WeakMap(),
    summaryElements,
    visibleNodes: new Set(),
    visibleEdges: new Set(),
    visibleClusters: new Set(),
    nodeVisualStates: new Map(),
    edgeVisualStates: new Map(),
    lastNodeVisualNodes: null,
    lastNodeVisualSelected: null,
    lastNodeVisualHighlights: null,
    lastEdgeVisualPaths: null,
    lastEdgeVisualSelected: null,
    lastEdgeSelectable: null,
    nodesRef: null,
    clustersRef: null,
    nodesById: new Map(),
    clusterAnchors: new Map(),
    candidateCache: null,
    edgePathsRef: null,
    relatedEdgesByNode: new Map(),
    layoutVersion: 0,
    layoutEnvironment: null,
    zoom: null,
  };
}

function stateFor(elements: MemoryGraphLabelElements): MemoryGraphLabelLayoutState {
  let state = labelLayoutStates.get(elements);
  if (!state) {
    state = createLabelLayoutState(new Map());
    labelLayoutStates.set(elements, state);
  }
  return state;
}

function refreshStaticLabelInputs(
  state: MemoryGraphLabelLayoutState,
  nodes: readonly PositionedMemoryKnowledgeGraphNode[],
  clusters: readonly MemoryGraphCluster[],
): void {
  if (state.nodesRef === nodes && state.clustersRef === clusters) return;
  state.nodesRef = nodes;
  state.clustersRef = clusters;
  state.nodesById = new Map(nodes.map((node) => [node.id, node]));
  state.clusterAnchors = new Map();
  for (const cluster of clusters) {
    let topMember: PositionedMemoryKnowledgeGraphNode | undefined;
    for (const id of cluster.nodeIds) {
      const node = state.nodesById.get(id);
      if (node && (!topMember || node.y > topMember.y)) topMember = node;
    }
    if (topMember) {
      state.clusterAnchors.set(cluster.key, {
        center: cluster.center,
        topMemberY: topMember.y,
      });
    }
  }
  state.candidateCache = null;
  state.nodeVisualStates.clear();
  state.lastNodeVisualNodes = null;
  state.lastNodeVisualSelected = null;
  state.lastNodeVisualHighlights = null;
}

function refreshRelatedEdges(
  state: MemoryGraphLabelLayoutState,
  edgePaths: readonly MemoryGraphEdgePath[],
): void {
  if (state.edgePathsRef === edgePaths) return;
  state.edgePathsRef = edgePaths;
  const related = new Map<string, MemoryGraphEdgePath[]>();
  for (const path of edgePaths) {
    const { source, target } = path.edge;
    const sourcePaths = related.get(source) ?? [];
    sourcePaths.push(path);
    related.set(source, sourcePaths);
    if (target !== source) {
      const targetPaths = related.get(target) ?? [];
      targetPaths.push(path);
      related.set(target, targetPaths);
    }
  }
  state.relatedEdgesByNode = new Map();
  for (const [id, paths] of related) {
    paths.sort((left, right) => {
      const weightDelta = (right.edge.weight ?? 0) - (left.edge.weight ?? 0);
      return weightDelta || (left.edge.id < right.edge.id ? -1 : left.edge.id > right.edge.id ? 1 : 0);
    });
    state.relatedEdgesByNode.set(id, paths.slice(0, 4));
  }
  state.edgeVisualStates.clear();
  state.lastEdgeVisualPaths = null;
  state.lastEdgeVisualSelected = null;
  state.lastEdgeSelectable = null;
}

function rectangle(x: number, y: number, width: number, height: number): LabelRect {
  return {
    left: x - width / 2 - 5,
    right: x + width / 2 + 5,
    top: y - height / 2 - 4,
    bottom: y + height / 2 + 4,
  };
}

function projectWorldPosition(
  camera: Camera,
  worldPosition: Vector3,
  scratch: Vector3,
  width: number,
  height: number,
): { x: number; y: number; z: number } {
  scratch.copy(worldPosition).project(camera);
  return {
    x: (scratch.x * 0.5 + 0.5) * width,
    y: (-scratch.y * 0.5 + 0.5) * height,
    z: scratch.z,
  };
}

function computedLabelStyleSignature(element: HTMLElement | undefined): string {
  if (!element || typeof window === "undefined" || typeof window.getComputedStyle !== "function") return "";
  const style = window.getComputedStyle(element);
  return [
    style.font,
    style.fontFamily,
    style.fontSize,
    style.fontStyle,
    style.fontWeight,
    style.lineHeight,
    style.letterSpacing,
    style.paddingTop,
    style.paddingRight,
    style.paddingBottom,
    style.paddingLeft,
    style.borderTopWidth,
    style.borderRightWidth,
    style.borderBottomWidth,
    style.borderLeftWidth,
    style.maxWidth,
    style.minWidth,
    style.boxSizing,
    style.whiteSpace,
  ].join("\u001f");
}

function themeFingerprint(labelLayer: HTMLElement): string {
  const parts: string[] = [];
  let element: HTMLElement | null = labelLayer;
  while (element) {
    parts.push(
      element.tagName,
      element.getAttribute("class") ?? "",
      element.getAttribute("style") ?? "",
      element.getAttribute("data-theme") ?? "",
      element.getAttribute("data-vui-theme") ?? "",
      element.getAttribute("data-color-scheme") ?? "",
      element.getAttribute("data-mode") ?? "",
    );
    if (typeof document !== "undefined" && element === document.documentElement) break;
    element = element.parentElement;
  }
  if (typeof window !== "undefined") {
    parts.push(String(Boolean(window.matchMedia?.("(prefers-color-scheme: dark)")?.matches)));
  }
  return parts.join("\u001f");
}

function labelLayoutVersion(
  state: MemoryGraphLabelLayoutState,
  elements: MemoryGraphLabelElements,
  labelLayer: HTMLDivElement,
  width: number,
  height: number,
): number {
  const fontSet = typeof document === "undefined" ? undefined : document.fonts;
  const fontReady = fontSet?.ready;
  const previous = state.layoutEnvironment;
  const theme = themeFingerprint(labelLayer);
  const baseChanged =
    !previous ||
    previous.width !== width ||
    previous.height !== height ||
    previous.viewportWidth !== (typeof window === "undefined" ? width : window.innerWidth) ||
    previous.viewportHeight !== (typeof window === "undefined" ? height : window.innerHeight) ||
    previous.devicePixelRatio !== (typeof window === "undefined" ? 1 : window.devicePixelRatio || 1) ||
    previous.fontStatus !== (fontSet?.status ?? "unsupported") ||
    previous.fontReady !== fontReady ||
    previous.themeFingerprint !== theme;
  const styleSignature = baseChanged
    ? [
        computedLabelStyleSignature(elements.nodeButtons.values().next().value),
        computedLabelStyleSignature(elements.edgeButtons.values().next().value),
        computedLabelStyleSignature(elements.clusterHeadings.values().next().value),
        labelLayer.className,
      ].join("\u001e")
    : previous.styleSignature;
  const environment: LayoutEnvironment = {
    width,
    height,
    viewportWidth: typeof window === "undefined" ? width : window.innerWidth,
    viewportHeight: typeof window === "undefined" ? height : window.innerHeight,
    devicePixelRatio: typeof window === "undefined" ? 1 : window.devicePixelRatio || 1,
    fontStatus: fontSet?.status ?? "unsupported",
    fontReady,
    themeFingerprint: theme,
    styleSignature,
  };
  if (
    baseChanged ||
    previous?.styleSignature !== environment.styleSignature
  ) {
    state.layoutVersion += 1;
    state.layoutEnvironment = environment;
  }
  return state.layoutVersion;
}

function updateNodeVisualState(
  state: MemoryGraphLabelLayoutState,
  elements: MemoryGraphLabelElements,
  nodes: readonly PositionedMemoryKnowledgeGraphNode[],
  adjacent: Map<string, Set<string>>,
  selectedNodeId: string,
  highlightIds: ReadonlySet<string>,
): void {
  if (
    state.lastNodeVisualNodes === nodes &&
    state.lastNodeVisualSelected === selectedNodeId &&
    state.lastNodeVisualHighlights === highlightIds
  ) return;
  const selectedNeighbors = adjacent.get(selectedNodeId) ?? EMPTY_NODE_IDS;
  const hasContext = Boolean(selectedNodeId) || highlightIds.size > 0;
  for (const node of nodes) {
    const button = elements.nodeButtons.get(node.id);
    if (!button) continue;
    const selected = node.id === selectedNodeId;
    const neighbor = selectedNeighbors.has(node.id);
    const highlighted = highlightIds.has(node.id);
    const muted = hasContext && !selected && !neighbor && !highlighted;
    const signature = `${Number(selected)}${Number(neighbor)}${Number(highlighted)}${Number(muted)}`;
    if (state.nodeVisualStates.get(node.id) === signature) continue;
    state.nodeVisualStates.set(node.id, signature);
    button.setAttribute("aria-pressed", String(selected));
    button.dataset.selected = String(selected);
    button.dataset.highlighted = String(highlighted);
    button.classList.toggle("is-selected", selected);
    button.classList.toggle("is-neighbor", neighbor);
    button.classList.toggle("is-highlighted", highlighted);
    button.classList.toggle("is-muted", muted);
  }
  state.lastNodeVisualNodes = nodes;
  state.lastNodeVisualSelected = selectedNodeId;
  state.lastNodeVisualHighlights = highlightIds;
}

function updateEdgeVisualState(
  state: MemoryGraphLabelLayoutState,
  elements: MemoryGraphLabelElements,
  edgePaths: readonly MemoryGraphEdgePath[],
  selectedNodeId: string,
  edgeSelectable: boolean,
): void {
  if (
    state.lastEdgeVisualPaths === edgePaths &&
    state.lastEdgeVisualSelected === selectedNodeId &&
    state.lastEdgeSelectable === edgeSelectable
  ) return;
  for (const { edge } of edgePaths) {
    const button = elements.edgeButtons.get(edge.id);
    if (!button) continue;
    const connected = Boolean(selectedNodeId) && (edge.source === selectedNodeId || edge.target === selectedNodeId);
    const signature = `${Number(connected)}${Number(edgeSelectable)}`;
    if (state.edgeVisualStates.get(edge.id) === signature) continue;
    state.edgeVisualStates.set(edge.id, signature);
    button.classList.toggle("is-selected", connected);
    button.disabled = !edgeSelectable;
  }
  state.lastEdgeVisualPaths = edgePaths;
  state.lastEdgeVisualSelected = selectedNodeId;
  state.lastEdgeSelectable = edgeSelectable;
}

function candidatesForFrame(
  state: MemoryGraphLabelLayoutState,
  nodes: readonly PositionedMemoryKnowledgeGraphNode[],
  adjacent: Map<string, Set<string>>,
  degree: Map<string, number>,
  clusters: readonly MemoryGraphCluster[],
  selectedNodeId: string,
  highlightIds: ReadonlySet<string>,
  zoom: MemoryGraphZoomLevel,
  areaScale: number,
): CandidateCache {
  const cached = state.candidateCache;
  if (
    cached &&
    cached.nodes === nodes &&
    cached.adjacent === adjacent &&
    cached.degree === degree &&
    cached.clusters === clusters &&
    cached.selectedNodeId === selectedNodeId &&
    cached.highlightIds === highlightIds &&
    cached.zoom === zoom &&
    cached.areaScale === areaScale
  ) return cached;

  const selectedNeighbors = adjacent.get(selectedNodeId) ?? EMPTY_NODE_IDS;
  const priorities = new Map<string, number>();
  for (const node of nodes) priorities.set(node.id, (degree.get(node.id) ?? 0) * 10);

  if (zoom === "overview") {
    for (const cluster of clusters) {
      let anchor: PositionedMemoryKnowledgeGraphNode | undefined;
      for (const id of cluster.nodeIds) {
        const candidate = state.nodesById.get(id);
        if (!candidate) continue;
        if (
          !anchor ||
          (degree.get(candidate.id) ?? 0) > (degree.get(anchor.id) ?? 0) ||
          ((degree.get(candidate.id) ?? 0) === (degree.get(anchor.id) ?? 0) && candidate.id < anchor.id)
        ) anchor = candidate;
      }
      if (anchor) priorities.set(anchor.id, Math.max(priorities.get(anchor.id) ?? 0, 1200));
    }
  }

  if (selectedNodeId) {
    priorities.set(selectedNodeId, 10_000);
    for (const id of selectedNeighbors) priorities.set(id, Math.max(priorities.get(id) ?? 0, 8_000));
  }
  for (const id of highlightIds) priorities.set(id, Math.max(priorities.get(id) ?? 0, 9_500));

  const importantCount = Math.min(24, Number(Boolean(selectedNodeId)) + selectedNeighbors.size + highlightIds.size);
  const baseBudget = Math.max(3, Math.round(LABEL_BUDGETS[zoom] * areaScale));
  const budget = Math.min(nodes.length, MAX_VISIBLE_NODE_LABELS, Math.max(baseBudget, importantCount));
  const comparePriority = (left: string, right: string) => {
    const priorityDelta = (priorities.get(right) ?? 0) - (priorities.get(left) ?? 0);
    return priorityDelta || (left < right ? -1 : left > right ? 1 : 0);
  };
  const clusterOrder = [...new Set([...clusters.map((cluster) => cluster.key), ...nodes.map((node) => node.clusterKey)])];
  const byCluster = new Map<string, string[]>(clusterOrder.map((key) => [key, []]));
  for (const node of nodes) byCluster.get(node.clusterKey)?.push(node.id);
  for (const idsInCluster of byCluster.values()) idsInCluster.sort(comparePriority);

  const ids: string[] = [];
  const included = new Set<string>();
  const include = (id: string) => {
    if (included.has(id) || !state.nodesById.has(id)) return;
    included.add(id);
    ids.push(id);
  };
  // Keep the selected node first, then reserve each cluster's best candidate.
  // A cluster's best uses the same score as the old global order, so a selected
  // neighbor or search highlight stays ahead of an ordinary cluster anchor.
  include(selectedNodeId);
  const clusterLeaders = clusterOrder
    .map((key) => byCluster.get(key)?.[0])
    .filter((id): id is string => Boolean(id))
    .sort(comparePriority);
  for (const id of clusterLeaders) include(id);

  // Complete the selected-neighbor/highlight tier before round-robin fallback.
  // This preserves context priority after giving each cluster its first choice.
  for (const id of [...priorities.keys()].sort(comparePriority)) {
    if ((priorities.get(id) ?? 0) >= 8_000) include(id);
  }

  const clusterOffsets = new Map(clusterOrder.map((key) => [key, 0]));
  let added = true;
  while (added) {
    added = false;
    for (const key of clusterOrder) {
      const idsInCluster = byCluster.get(key) ?? [];
      let offset = clusterOffsets.get(key) ?? 0;
      while (offset < idsInCluster.length && included.has(idsInCluster[offset])) offset += 1;
      clusterOffsets.set(key, offset + 1);
      if (offset >= idsInCluster.length) continue;
      include(idsInCluster[offset]);
      added = true;
    }
  }
  const next: CandidateCache = {
    nodes,
    adjacent,
    degree,
    clusters,
    selectedNodeId,
    highlightIds,
    zoom,
    areaScale,
    ids,
    budget,
  };
  state.candidateCache = next;
  return next;
}

function requestNodeVariant(
  button: HTMLButtonElement,
  selected: boolean,
  neighbor: boolean,
  highlighted: boolean,
  muted: boolean,
): string {
  return [
    selected,
    neighbor,
    highlighted,
    muted,
    button.matches(":hover"),
    button.matches(":focus-visible"),
  ].map(Number).join("");
}

function nodeSummaryExpanded(
  state: MemoryGraphLabelLayoutState,
  id: string,
  button: HTMLButtonElement,
  selected: boolean,
  highlighted: boolean,
): boolean {
  if (!state.summaryElements.has(id)) return false;
  return selected || highlighted || button.matches(":hover") || button.matches(":focus-visible");
}

function prepareCardMeasurements(
  state: MemoryGraphLabelLayoutState,
  requests: readonly CardRequest[],
  version: number,
): { node: Set<string>; edge: Set<string>; cluster: Set<string> } {
  const staged = { node: new Set<string>(), edge: new Set<string>(), cluster: new Set<string>() };
  const misses: CardRequest[] = [];
  for (const request of requests) {
    const cached = state.sizes.get(request.element);
    if (cached && cached.version === version && cached.variant === request.variant) {
      request.size = { width: cached.width, height: cached.height };
      continue;
    }
    // Match the class-declared node grid and block card modes before measuring.
    // All misses are staged before any offset read forces layout.
    request.element.style.display = request.kind === "node" ? "grid" : "block";
    staged[request.kind].add(request.id);
    misses.push(request);
  }
  for (const request of misses) {
    const size = {
      width: request.element.offsetWidth || 148,
      height: request.element.offsetHeight || 26,
    };
    request.size = size;
    state.sizes.set(request.element, { ...size, version, variant: request.variant });
  }
  return staged;
}

function findCardPosition(
  request: CardRequest,
  width: number,
  height: number,
  occupied: LabelRect[],
  nodeCircles: Map<string, NodeCircle>,
): CardPosition | null {
  const cardWidth = request.size?.width ?? 148;
  const cardHeight = request.size?.height ?? 26;
  const { x, y, radius } = request;
  const options = [
    { x: x + cardWidth / 2 + radius + 8, y },
    { x: x - cardWidth / 2 - radius - 8, y },
    { x, y: y - cardHeight / 2 - radius - 8 },
    { x, y: y + cardHeight / 2 + radius + 8 },
  ];

  for (const option of options) {
    const left = cardWidth / 2 + 8;
    const right = width - cardWidth / 2 - 8;
    const top = cardHeight / 2 + 8;
    const bottom = height - cardHeight / 2 - 8;
    if (right < left || bottom < top) continue;
    const centerX = Math.max(left, Math.min(right, option.x));
    const centerY = Math.max(top, Math.min(bottom, option.y));
    const rect = rectangle(centerX, centerY, cardWidth, cardHeight);
    const overlapsLabel = occupied.some(
      (other) =>
        rect.left < other.right &&
        rect.right > other.left &&
        rect.top < other.bottom &&
        rect.bottom > other.top,
    );
    if (overlapsLabel) continue;

    let overlapsNode = false;
    for (const [id, circle] of nodeCircles) {
      if (id === request.exceptNodeId) continue;
      const nearestX = Math.max(rect.left, Math.min(circle.x, rect.right));
      const nearestY = Math.max(rect.top, Math.min(circle.y, rect.bottom));
      if (Math.hypot(circle.x - nearestX, circle.y - nearestY) < circle.radius + 3) {
        overlapsNode = true;
        break;
      }
    }
    if (overlapsNode) continue;

    occupied.push(rect);
    return { x: centerX, y: centerY };
  }
  return null;
}

function firstClampedCardPosition(request: CardRequest, width: number, height: number): CardPosition {
  const cardWidth = request.size?.width ?? 148;
  const cardHeight = request.size?.height ?? 26;
  const left = cardWidth / 2 + 8;
  const right = width - cardWidth / 2 - 8;
  const top = cardHeight / 2 + 8;
  const bottom = height - cardHeight / 2 - 8;
  const desiredX = request.x + cardWidth / 2 + request.radius + 8;
  return {
    x: right < left ? width / 2 : Math.max(left, Math.min(right, desiredX)),
    y: bottom < top ? height / 2 : Math.max(top, Math.min(bottom, request.y)),
  };
}

function hideCard(element: HTMLElement | undefined): void {
  if (!element) return;
  if (element.style.display !== "none") element.style.display = "none";
  if (element.style.visibility !== "") element.style.visibility = "";
}

function showPlacedCards<T extends HTMLElement>(
  previous: Set<string>,
  staged: Set<string>,
  placements: Map<string, CardRequest>,
  elements: Map<string, T>,
): Set<string> {
  for (const id of previous) {
    if (!placements.has(id)) hideCard(elements.get(id));
  }
  for (const id of staged) {
    if (!placements.has(id)) hideCard(elements.get(id));
  }
  const visible = new Set<string>();
  for (const [id, request] of placements) {
    const position = request.position;
    if (!position) continue;
    const display = request.kind === "node" ? "grid" : "block";
    if (request.element.style.display !== display) request.element.style.display = display;
    if (request.element.style.visibility !== "visible") request.element.style.visibility = "visible";
    const left = position.x + "px";
    const top = position.y + "px";
    if (request.element.style.left !== left) request.element.style.left = left;
    if (request.element.style.top !== top) request.element.style.top = top;
    visible.add(id);
  }
  return visible;
}

export function positionMemoryGraphLabels(options: {
  host: HTMLDivElement;
  labelLayer: HTMLDivElement;
  camera: Camera;
  fieldOfView: number;
  nodes: readonly PositionedMemoryKnowledgeGraphNode[];
  clusters: readonly MemoryGraphCluster[];
  edgePaths: readonly MemoryGraphEdgePath[];
  elements: MemoryGraphLabelElements;
  adjacent: Map<string, Set<string>>;
  degree: Map<string, number>;
  selectedNodeId: string;
  highlightIds: ReadonlySet<string>;
  labelsVisible: boolean;
  overviewDistance: number;
  cameraTarget: Vector3;
  canSelectEdge: () => boolean;
  scratch: Vector3;
}): MemoryGraphZoomLevel {
  const {
    host,
    labelLayer,
    camera,
    fieldOfView,
    nodes,
    clusters,
    edgePaths,
    elements,
    adjacent,
    degree,
    selectedNodeId,
    highlightIds,
    labelsVisible,
    overviewDistance,
    cameraTarget,
    canSelectEdge,
    scratch,
  } = options;
  const width = host.clientWidth;
  const height = host.clientHeight;
  if (!width || !height) return "overview";

  const state = stateFor(elements);
  refreshStaticLabelInputs(state, nodes, clusters);
  refreshRelatedEdges(state, edgePaths);
  const areaScale = Math.max(0.58, Math.min(1.18, Math.sqrt((width * height) / 600_000)));
  const zoomScale = (overviewDistance / Math.max(1, camera.position.distanceTo(cameraTarget))) * areaScale;
  const zoom: MemoryGraphZoomLevel = zoomScale < 1.38 ? "overview" : zoomScale < 2.35 ? "topic" : "detail";
  if (state.zoom !== zoom) {
    labelLayer.parentElement?.setAttribute("data-zoom-level", zoom);
    state.zoom = zoom;
  }

  updateNodeVisualState(state, elements, nodes, adjacent, selectedNodeId, highlightIds);
  const edgeSelectable = canSelectEdge();
  updateEdgeVisualState(state, elements, edgePaths, selectedNodeId, edgeSelectable);

  const placedNodes = new Map<string, CardRequest>();
  const placedEdges = new Map<string, CardRequest>();
  const placedClusters = new Map<string, CardRequest>();
  if (!labelsVisible) {
    state.visibleNodes = showPlacedCards(state.visibleNodes, new Set(), placedNodes, elements.nodeButtons);
    state.visibleEdges = showPlacedCards(state.visibleEdges, new Set(), placedEdges, elements.edgeButtons);
    state.visibleClusters = showPlacedCards(state.visibleClusters, new Set(), placedClusters, elements.clusterHeadings);
    return zoom;
  }

  const layoutVersion = labelLayoutVersion(state, elements, labelLayer, width, height);
  const nodeCircles = new Map<string, NodeCircle>();
  const tangent = Math.tan((fieldOfView * Math.PI) / 360);
  for (const node of nodes) {
    const projected = projectWorldPosition(camera, scratch.set(node.x, node.y, node.z), scratch, width, height);
    if (projected.z < -1 || projected.z > 1) continue;
    if (projected.x < -50 || projected.x > width + 50 || projected.y < -50 || projected.y > height + 50) continue;
    const depth = Math.max(
      1,
      Math.hypot(
        camera.position.x - node.x,
        camera.position.y - node.y,
        camera.position.z - node.z,
      ),
    );
    const radius = Math.min(44, Math.max(7, (0.42 * height) / (2 * tangent * depth)));
    nodeCircles.set(node.id, { x: projected.x, y: projected.y, radius });
  }

  const clusterRequests: CardRequest[] = [];
  if (zoom !== "detail") {
    for (const cluster of clusters) {
      const heading = elements.clusterHeadings.get(cluster.key);
      const anchor = state.clusterAnchors.get(cluster.key);
      if (!heading || !anchor) continue;
      const projected = projectWorldPosition(
        camera,
        scratch.set(anchor.center.x, anchor.topMemberY + 1.15, anchor.center.z + 0.18),
        scratch,
        width,
        height,
      );
      if (projected.z < -1 || projected.z > 1) continue;
      if (projected.x < -24 || projected.x > width + 24 || projected.y < -24 || projected.y > height + 24) continue;
      clusterRequests.push({
        kind: "cluster",
        id: cluster.key,
        element: heading,
        x: projected.x,
        y: projected.y,
        radius: 0,
        variant: "",
      });
    }
  }

  const candidates = candidatesForFrame(
    state,
    nodes,
    adjacent,
    degree,
    clusters,
    selectedNodeId,
    highlightIds,
    zoom,
    areaScale,
  );
  const visibleCandidateIds = candidates.ids
    .filter((id) => nodeCircles.has(id));
  const selectedNeighbors = adjacent.get(selectedNodeId) ?? EMPTY_NODE_IDS;
  const nodeRequests: CardRequest[] = [];
  for (const id of visibleCandidateIds) {
    const button = elements.nodeButtons.get(id);
    const circle = nodeCircles.get(id);
    if (!button || !circle) continue;
    const selected = id === selectedNodeId;
    const neighbor = selectedNeighbors.has(id);
    const highlighted = highlightIds.has(id);
    const muted = Boolean(selectedNodeId || highlightIds.size) && !selected && !neighbor && !highlighted;
    const variant = requestNodeVariant(button, selected, neighbor, highlighted, muted);
    nodeRequests.push({
      kind: "node",
      id,
      element: button,
      x: circle.x,
      y: circle.y,
      radius: circle.radius,
      exceptNodeId: id,
      variant,
    });
    const last = nodeRequests[nodeRequests.length - 1];
    last.variant += nodeSummaryExpanded(state, id, button, selected, highlighted) ? "e" : "c";
  }

  const edgeRequests: CardRequest[] = [];
  if (selectedNodeId) {
    for (const path of state.relatedEdgesByNode.get(selectedNodeId) ?? []) {
      const button = elements.edgeButtons.get(path.edge.id);
      if (!button) continue;
      const point = path.curve.getPoint(0.54);
      const projected = projectWorldPosition(camera, point, scratch, width, height);
      if (projected.z < -1 || projected.z > 1) continue;
      edgeRequests.push({
        kind: "edge",
        id: path.edge.id,
        element: button,
        x: projected.x,
        y: projected.y,
        radius: 0,
        variant: `${Number(edgeSelectable)}${Number(path.edge.source === selectedNodeId || path.edge.target === selectedNodeId)}`,
      });
    }
  }

  const requests = [...clusterRequests, ...nodeRequests, ...edgeRequests];
  const staged = prepareCardMeasurements(state, requests, layoutVersion);
  const occupied: LabelRect[] = [];
  for (const request of clusterRequests) {
    const position = findCardPosition(request, width, height, occupied, nodeCircles);
    if (!position) continue;
    request.position = position;
    placedClusters.set(request.id, request);
  }
  let placedNodeCount = 0;
  for (const request of nodeRequests) {
    if (placedNodeCount >= candidates.budget) break;
    let position = findCardPosition(request, width, height, occupied, nodeCircles);
    if (!position && request.id === selectedNodeId) {
      position = firstClampedCardPosition(request, width, height);
      occupied.push(rectangle(position.x, position.y, request.size?.width ?? 148, request.size?.height ?? 26));
    }
    if (!position) continue;
    request.position = position;
    placedNodeCount += 1;
    placedNodes.set(request.id, request);
  }
  for (const request of edgeRequests) {
    const position = findCardPosition(request, width, height, occupied, nodeCircles);
    if (!position) continue;
    request.position = position;
    placedEdges.set(request.id, request);
  }

  state.visibleClusters = showPlacedCards(state.visibleClusters, staged.cluster, placedClusters, elements.clusterHeadings);
  state.visibleNodes = showPlacedCards(state.visibleNodes, staged.node, placedNodes, elements.nodeButtons);
  state.visibleEdges = showPlacedCards(state.visibleEdges, staged.edge, placedEdges, elements.edgeButtons);
  return zoom;
}
