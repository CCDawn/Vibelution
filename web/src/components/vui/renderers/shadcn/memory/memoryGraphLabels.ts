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

  for (const cluster of clusters) {
    const heading = document.createElement("div");
    heading.className = styles.clusterLabel;
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
    }

    button.addEventListener("click", () => onSelectNode(node.id));
    layer.append(button);
    nodeButtons.set(node.id, button);
  }

  return { nodeButtons, edgeButtons, clusterHeadings };
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

function rectangle(x: number, y: number, width: number, height: number) {
  return {
    left: x - width / 2 - 5,
    right: x + width / 2 + 5,
    top: y - height / 2 - 4,
    bottom: y + height / 2 + 4,
  };
}

type LabelRect = ReturnType<typeof rectangle>;

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

function placeCard(
  element: HTMLElement,
  x: number,
  y: number,
  radius: number,
  width: number,
  height: number,
  occupied: LabelRect[],
  nodeCircles: Map<string, { x: number; y: number; radius: number }>,
  exceptNodeId?: string,
): boolean {
  element.style.display = "block";
  element.style.visibility = "hidden";
  const cardWidth = element.offsetWidth || 148;
  const cardHeight = element.offsetHeight || 26;
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
      if (id === exceptNodeId) continue;
      const nearestX = Math.max(rect.left, Math.min(circle.x, rect.right));
      const nearestY = Math.max(rect.top, Math.min(circle.y, rect.bottom));
      if (Math.hypot(circle.x - nearestX, circle.y - nearestY) < circle.radius + 3) {
        overlapsNode = true;
        break;
      }
    }
    if (overlapsNode) continue;

    occupied.push(rect);
    element.style.left = centerX + "px";
    element.style.top = centerY + "px";
    element.style.visibility = "visible";
    return true;
  }

  element.style.display = "none";
  element.style.visibility = "";
  return false;
}

function candidateNodeIds(
  nodes: readonly PositionedMemoryKnowledgeGraphNode[],
  adjacency: Map<string, Set<string>>,
  degree: Map<string, number>,
  clusters: readonly MemoryGraphCluster[],
  selectedNodeId: string,
  highlightIds: ReadonlySet<string>,
  zoom: MemoryGraphZoomLevel,
  areaScale: number,
): { ids: string[]; budget: number } {
  const selectedNeighbors = adjacency.get(selectedNodeId) ?? new Set<string>();
  const priorities = new Map<string, number>();
  const sourceById = new Map(nodes.map((node) => [node.id, node]));

  for (const node of nodes) {
    priorities.set(node.id, (degree.get(node.id) ?? 0) * 10);
  }

  if (zoom === "overview") {
    for (const cluster of clusters) {
      const anchor = cluster.nodeIds
        .map((id) => sourceById.get(id))
        .filter((node): node is PositionedMemoryKnowledgeGraphNode => Boolean(node))
        .sort((left, right) => {
          const degreeDelta = (degree.get(right.id) ?? 0) - (degree.get(left.id) ?? 0);
          return degreeDelta || (left.id < right.id ? -1 : left.id > right.id ? 1 : 0);
        })[0];
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
  const budget = Math.min(nodes.length, 32, Math.max(baseBudget, importantCount));
  const ids = [...priorities.entries()]
    .sort((left, right) => {
      const priorityDelta = right[1] - left[1];
      return priorityDelta || (left[0] < right[0] ? -1 : left[0] > right[0] ? 1 : 0);
    })
    .map(([id]) => id);
  return { ids, budget };
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

  const areaScale = Math.max(0.58, Math.min(1.18, Math.sqrt((width * height) / 600_000)));
  const zoomScale = (overviewDistance / Math.max(1, camera.position.distanceTo(cameraTarget))) * areaScale;
  const zoom: MemoryGraphZoomLevel = zoomScale < 1.38 ? "overview" : zoomScale < 2.35 ? "topic" : "detail";
  labelLayer.parentElement?.setAttribute("data-zoom-level", zoom);

  const nodeCircles = new Map<string, { x: number; y: number; radius: number }>();
  const tangent = Math.tan((fieldOfView * Math.PI) / 360);
  for (const node of nodes) {
    const projected = projectWorldPosition(
      camera,
      scratch.set(node.x, node.y, node.z),
      scratch,
      width,
      height,
    );
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

  const selectedNeighbors = adjacent.get(selectedNodeId) ?? new Set<string>();
  const occupied: LabelRect[] = [];

  for (const [id, button] of elements.nodeButtons) {
    const selected = id === selectedNodeId;
    const neighbor = selectedNeighbors.has(id);
    const highlighted = highlightIds.has(id);
    button.setAttribute("aria-pressed", String(selected));
    button.dataset.selected = String(selected);
    button.dataset.highlighted = String(highlighted);
    button.classList.toggle("is-selected", selected);
    button.classList.toggle("is-neighbor", neighbor);
    button.classList.toggle("is-highlighted", highlighted);
    button.classList.toggle("is-muted", Boolean(selectedNodeId || highlightIds.size) && !selected && !neighbor && !highlighted);
    button.style.display = "none";
  }

  for (const heading of elements.clusterHeadings.values()) heading.style.display = "none";
  for (const edgePath of edgePaths) {
    const button = elements.edgeButtons.get(edgePath.edge.id);
    if (!button) continue;
    const connected =
      Boolean(selectedNodeId) &&
      (edgePath.edge.source === selectedNodeId || edgePath.edge.target === selectedNodeId);
    button.classList.toggle("is-selected", connected);
    button.disabled = !canSelectEdge();
    button.style.display = "none";
  }

  if (!labelsVisible) return zoom;

  if (zoom !== "detail") {
    const clusterCenters = new Map(clusters.map((cluster) => [cluster.key, cluster.center]));
    for (const cluster of clusters) {
      const heading = elements.clusterHeadings.get(cluster.key);
      const center = clusterCenters.get(cluster.key);
      if (!heading || !center) continue;
      const topMember = cluster.nodeIds
        .map((id) => nodes.find((node) => node.id === id))
        .filter((node): node is PositionedMemoryKnowledgeGraphNode => Boolean(node))
        .sort((left, right) => right.y - left.y)[0];
      if (!topMember) continue;
      const headingWorld = scratch.set(center.x, topMember.y + 1.15, center.z + 0.18);
      const projected = projectWorldPosition(camera, headingWorld, scratch, width, height);
      if (projected.z < -1 || projected.z > 1) continue;
      if (projected.x < -24 || projected.x > width + 24 || projected.y < -24 || projected.y > height + 24) continue;
      placeCard(heading, projected.x, projected.y, 0, width, height, occupied, nodeCircles);
    }
  }

  const candidates = candidateNodeIds(
    nodes,
    adjacent,
    degree,
    clusters,
    selectedNodeId,
    highlightIds,
    zoom,
    areaScale,
  );
  let placed = 0;
  for (const id of candidates.ids) {
    if (placed >= candidates.budget) break;
    const button = elements.nodeButtons.get(id);
    const circle = nodeCircles.get(id);
    if (!button || !circle) continue;
    if (placeCard(button, circle.x, circle.y, circle.radius, width, height, occupied, nodeCircles, id)) placed += 1;
  }

  if (!selectedNodeId) return zoom;
  const related = edgePaths
    .filter(
      ({ edge }) =>
        edge.source === selectedNodeId || edge.target === selectedNodeId,
    )
    .sort((left, right) => {
      const weightDelta = (right.edge.weight ?? 0) - (left.edge.weight ?? 0);
      return weightDelta || (left.edge.id < right.edge.id ? -1 : left.edge.id > right.edge.id ? 1 : 0);
    })
    .slice(0, 4);
  for (const path of related) {
    const button = elements.edgeButtons.get(path.edge.id);
    if (!button) continue;
    const point = path.curve.getPoint(0.54);
    const projected = projectWorldPosition(camera, point, scratch, width, height);
    if (projected.z < -1 || projected.z > 1) continue;
    placeCard(button, projected.x, projected.y, 0, width, height, occupied, nodeCircles);
  }
  return zoom;
}
