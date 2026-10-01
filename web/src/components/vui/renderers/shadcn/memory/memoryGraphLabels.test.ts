/** @vitest-environment happy-dom */
import {
  PerspectiveCamera,
  QuadraticBezierCurve3,
  Vector3,
} from "three";
import { afterEach, expect, it, vi } from "vitest";
import type {
  MemoryKnowledgeGraphEdge,
  MemoryKnowledgeGraphNode,
} from "../../../../../api/types";
import type {
  MemoryGraphCluster,
  PositionedMemoryKnowledgeGraphNode,
} from "../../../product/memory/memoryGraphModel";
import {
  buildMemoryGraphAdjacency,
  createMemoryGraphLabelElements,
  positionMemoryGraphLabels,
  type MemoryGraphEdgePath,
} from "./memoryGraphLabels";

type Dimensions = { width: number | ((element: HTMLElement) => number); height: (element: HTMLElement) => number };

function mockDimensions(dimensions: Dimensions) {
  const counts = { width: 0, height: 0 };
  const oldWidth = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "offsetWidth");
  const oldHeight = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "offsetHeight");
  Object.defineProperty(HTMLElement.prototype, "offsetWidth", {
    configurable: true,
    get() {
      counts.width += 1;
      return typeof dimensions.width === "function" ? dimensions.width(this as HTMLElement) : dimensions.width;
    },
  });
  Object.defineProperty(HTMLElement.prototype, "offsetHeight", {
    configurable: true,
    get() {
      counts.height += 1;
      return dimensions.height(this as HTMLElement);
    },
  });
  return {
    counts,
    restore() {
      if (oldWidth) Object.defineProperty(HTMLElement.prototype, "offsetWidth", oldWidth);
      else Reflect.deleteProperty(HTMLElement.prototype, "offsetWidth");
      if (oldHeight) Object.defineProperty(HTMLElement.prototype, "offsetHeight", oldHeight);
      else Reflect.deleteProperty(HTMLElement.prototype, "offsetHeight");
    },
  };
}

function sourceNode(id: string): MemoryKnowledgeGraphNode {
  return {
    id,
    type: "concept",
    label: `节点 ${id}`,
    summary: `节点 ${id} 的摘要内容`,
    status: "active",
    createdAt: "",
    updatedAt: "",
    metadata: {},
    responsibilityQuestion: "",
    visual: {},
    childNodeIds: [],
    contentItems: [],
  };
}

function makeNodes(
  ids: readonly string[],
  positions: ReadonlyMap<string, { x: number; y: number; z: number }>,
): PositionedMemoryKnowledgeGraphNode[] {
  return ids.map((id) => ({
    id,
    source: sourceNode(id),
    clusterKey: "knowledge",
    clusterLabel: "知识与概念",
    ...(positions.get(id) ?? { x: 0, y: 0, z: 0 }),
  }));
}

function makeCluster(nodes: readonly PositionedMemoryKnowledgeGraphNode[]): MemoryGraphCluster[] {
  return nodes.length
    ? [{
        key: "knowledge",
        label: "知识与概念",
        center: { x: 0, y: 0, z: 0 },
        nodeIds: nodes.map((node) => node.id),
      }]
    : [];
}

function makeEdge(id: string, source: string, target: string, weight = 1): MemoryKnowledgeGraphEdge {
  return { id, source, target, type: "related_to", label: `关系 ${id}`, weight, metadata: {} };
}

function makeEdgePath(
  edge: MemoryKnowledgeGraphEdge,
  start: Vector3,
  end: Vector3,
): MemoryGraphEdgePath {
  const control = start.clone().add(end).multiplyScalar(0.5).add(new Vector3(0, 0.35, 0));
  return { edge, curve: new QuadraticBezierCurve3(start, control, end) };
}

function createFixture(
  nodes: readonly PositionedMemoryKnowledgeGraphNode[],
  edges: readonly MemoryKnowledgeGraphEdge[],
  width = 1200,
  height = 900,
  cameraDistance = 20,
  suppliedClusters?: MemoryGraphCluster[],
) {
  let hostWidth = width;
  let hostHeight = height;
  const host = document.createElement("div");
  Object.defineProperties(host, {
    clientWidth: { configurable: true, get: () => hostWidth },
    clientHeight: { configurable: true, get: () => hostHeight },
  });
  const layer = document.createElement("div");
  host.append(layer);
  document.body.append(host);
  const clusters = suppliedClusters ?? makeCluster(nodes);
  const camera = new PerspectiveCamera(44, width / height, 0.1, 220);
  camera.position.set(0, 0, cameraDistance);
  camera.lookAt(0, 0, 0);
  camera.updateProjectionMatrix();
  camera.updateMatrixWorld(true);
  const cameraTarget = new Vector3();
  const edgePaths = edges.map((edge) => {
    const start = nodes.find((node) => node.id === edge.source);
    const end = nodes.find((node) => node.id === edge.target);
    return makeEdgePath(
      edge,
      new Vector3(start?.x ?? 0, start?.y ?? 0, start?.z ?? 0),
      new Vector3(end?.x ?? 0, end?.y ?? 0, end?.z ?? 0),
    );
  });
  const elements = createMemoryGraphLabelElements(
    layer,
    nodes,
    edges,
    clusters,
    vi.fn(),
    vi.fn(),
    () => true,
  );
  const adjacency = buildMemoryGraphAdjacency(nodes, edges);
  const place = (values: {
    selectedNodeId?: string;
    highlightIds?: ReadonlySet<string>;
    labelsVisible?: boolean;
    selectable?: boolean;
  } = {}) => positionMemoryGraphLabels({
    host,
    labelLayer: layer,
    camera,
    fieldOfView: 44,
    nodes,
    clusters,
    edgePaths,
    elements,
    adjacent: adjacency.adjacent,
    degree: adjacency.degree,
    selectedNodeId: values.selectedNodeId ?? "",
    highlightIds: values.highlightIds ?? new Set(),
    labelsVisible: values.labelsVisible ?? true,
    overviewDistance: 20,
    cameraTarget,
    canSelectEdge: () => values.selectable ?? true,
    scratch: new Vector3(),
  });
  return {
    host,
    layer,
    nodes,
    edges,
    edgePaths,
    elements,
    camera,
    place,
    setSize(nextWidth: number, nextHeight: number) {
      hostWidth = nextWidth;
      hostHeight = nextHeight;
      camera.aspect = nextWidth / nextHeight;
      camera.updateProjectionMatrix();
      camera.updateMatrixWorld(true);
    },
    cleanup() {
      host.remove();
    },
  };
}

afterEach(() => vi.restoreAllMocks());

it("measures visible candidates within input size and reuses sizes in steady state", () => {
  const nodes = makeNodes(
    Array.from({ length: 200 }, (_, index) => `n${String(index).padStart(3, "0")}`),
    new Map(),
  );
  const fixture = createFixture(nodes, [], 1200, 900, 5.5);
  const dimensions = mockDimensions({ width: 2400, height: () => 80 });
  try {
    expect(fixture.place()).toBe("detail");
    expect(dimensions.counts.width).toBeLessThanOrEqual(nodes.length);
    expect(dimensions.counts.height).toBeLessThanOrEqual(nodes.length);
    expect([...fixture.elements.nodeButtons.values()].every((button) => button.style.display === "none")).toBe(true);

    const measured = { ...dimensions.counts };
    fixture.place();
    expect(dimensions.counts).toEqual(measured);

    const beforeResize = { ...dimensions.counts };
    fixture.setSize(1100, 900);
    fixture.place();
    expect(dimensions.counts.width - beforeResize.width).toBeLessThanOrEqual(nodes.length);
    expect(dimensions.counts.height - beforeResize.height).toBeLessThanOrEqual(nodes.length);
    const afterResize = { ...dimensions.counts };
    fixture.place();
    expect(dimensions.counts).toEqual(afterResize);

    fixture.place({ selectedNodeId: "n000" });
    const selected = fixture.elements.nodeButtons.get("n000")!;
    expect(selected.getAttribute("aria-pressed")).toBe("true");
    expect(selected.style.display).toBe("grid");
    expect(selected.style.left).not.toBe("");
    expect(selected.style.top).not.toBe("");
  } finally {
    dimensions.restore();
    fixture.cleanup();
  }
});

it("gives every dense graph cluster an attempt under heavy neighbor and highlight context", () => {
  const clusterSpecs: Array<{ key: MemoryGraphCluster["key"]; label: string }> = [
    { key: "knowledge", label: "知识与概念" },
    { key: "workspace", label: "项目与团队" },
    { key: "agents", label: "Agent 与私有记忆" },
    { key: "sources", label: "知识来源" },
    { key: "operations", label: "运行与扩展" },
  ];
  const ids = [
    ...Array.from({ length: 56 }, (_, index) => `k${String(index).padStart(2, "0")}`),
    "w0",
    "a0",
    "s0",
    "o0",
  ];
  const clusterById = new Map<string, MemoryGraphCluster["key"]>([
    ["w0", "workspace"],
    ["a0", "agents"],
    ["s0", "sources"],
    ["o0", "operations"],
  ]);
  const nodes = makeNodes(ids, new Map()).map((node) => {
    const clusterKey = clusterById.get(node.id) ?? "knowledge";
    const clusterLabel = clusterSpecs.find((cluster) => cluster.key === clusterKey)!.label;
    return { ...node, clusterKey, clusterLabel };
  });
  const clusters = clusterSpecs
    .map(({ key, label }) => ({
      key,
      label,
      center: { x: 0, y: 0, z: 0 },
      nodeIds: nodes.filter((node) => node.clusterKey === key).map((node) => node.id),
    }))
    .filter((cluster) => cluster.nodeIds.length > 0);
  const edges = [
    ...Array.from({ length: 54 }, (_, index) => makeEdge(`e${index}`, "a0", `k${String(index).padStart(2, "0")}`)),
    makeEdge("workspace-neighbor", "a0", "w0"),
  ];
  const fixture = createFixture(nodes, edges, 1200, 900, 5.5, clusters);
  const measuredNodeIds: string[] = [];
  const dimensions = mockDimensions({
    width: (element) => {
      if (element.dataset.nodeId) measuredNodeIds.push(element.dataset.nodeId);
      return 2400;
    },
    height: () => 80,
  });
  const highlighted = new Set(Array.from({ length: 52 }, (_, index) => `k${String(index).padStart(2, "0")}`));
  try {
    expect(fixture.place({ selectedNodeId: "a0", highlightIds: highlighted })).toBe("detail");
    expect(measuredNodeIds).toHaveLength(nodes.length);
    expect(measuredNodeIds[0]).toBe("a0");
    expect(["k00", "w0", "a0", "s0", "o0"].every((id) => measuredNodeIds.includes(id))).toBe(true);
    expect(dimensions.counts.width).toBeLessThanOrEqual(nodes.length + fixture.edgePaths.length);
    expect(dimensions.counts.height).toBeLessThanOrEqual(nodes.length + fixture.edgePaths.length);
    expect(fixture.elements.nodeButtons.get("a0")!.style.display).toBe("grid");
  } finally {
    dimensions.restore();
    fixture.cleanup();
  }
});

it("retains selected, neighbor, edge, hover, focus, font, and layout-size behavior", () => {
  const nodes = makeNodes(
    ["n0", "n1", "n2"],
    new Map([
      ["n0", { x: -2.4, y: 0, z: 0 }],
      ["n1", { x: 0, y: 0.5, z: 0 }],
      ["n2", { x: 2.4, y: -0.25, z: 0 }],
    ]),
  );
  const edges = [makeEdge("e0", "n0", "n1", 2), makeEdge("e1", "n1", "n2", 1)];
  const fixture = createFixture(nodes, edges, 1200, 900, 14);
  const expandedReads: string[] = [];
  const dimensions = mockDimensions({
    width: 92,
    height: (element) => {
      const id = element.dataset.nodeId;
      if (!id) return 24;
      const expanded =
        element.getAttribute("aria-pressed") === "true" ||
        element.dataset.highlighted === "true" ||
        element.matches(":hover") ||
        element.matches(":focus-visible");
      expandedReads.push(`${id}:${expanded}`);
      return expanded ? 46 : 26;
    },
  });
  const hoverIds = new Set<string>();
  const focusIds = new Set<string>();
  for (const [id, button] of fixture.elements.nodeButtons) {
    const matches = button.matches.bind(button);
    vi.spyOn(button, "matches").mockImplementation((selector) => {
      if (selector === ":hover") return hoverIds.has(id);
      if (selector === ":focus-visible") return focusIds.has(id);
      return matches(selector);
    });
  }
  const savedFonts = Object.getOwnPropertyDescriptor(document, "fonts");
  const fontSet = (ready: Promise<FontFaceSet>) => ({ status: "loaded", ready }) as unknown as FontFaceSet;
  Object.defineProperty(document, "fonts", {
    configurable: true,
    value: fontSet(Promise.resolve(document as unknown as FontFaceSet)),
  });

  try {
    fixture.place();
    const initialReads = { ...dimensions.counts };
    fixture.place();
    expect(dimensions.counts).toEqual(initialReads);

    fixture.place({ selectedNodeId: "n0" });
    const n0 = fixture.elements.nodeButtons.get("n0")!;
    const n1 = fixture.elements.nodeButtons.get("n1")!;
    const n2 = fixture.elements.nodeButtons.get("n2")!;
    const connectedEdge = fixture.elements.edgeButtons.get("e0")!;
    expect(n0.getAttribute("aria-pressed")).toBe("true");
    expect(n0.dataset.selected).toBe("true");
    expect(n0.classList.contains("is-selected")).toBe(true);
    expect(n1.classList.contains("is-neighbor")).toBe(true);
    expect(expandedReads).toContain("n0:true");
    expect(connectedEdge.classList.contains("is-selected")).toBe(true);
    expect(connectedEdge.style.display).toBe("block");
    expect(n0.style.left).not.toBe("");
    const selectedReads = { ...dimensions.counts };
    fixture.place({ selectedNodeId: "n0" });
    expect(dimensions.counts).toEqual(selectedReads);

    fixture.place({ selectedNodeId: "n0", highlightIds: new Set(["n2"]) });
    expect(n2.dataset.highlighted).toBe("true");
    expect(n2.classList.contains("is-highlighted")).toBe(true);
    expect(expandedReads).toContain("n2:true");

    hoverIds.add("n2");
    fixture.place({ selectedNodeId: "n0" });
    expect(expandedReads.filter((read) => read === "n2:true").length).toBeGreaterThan(1);
    hoverIds.clear();
    focusIds.add("n2");
    fixture.place({ selectedNodeId: "n0" });
    expect(expandedReads.filter((read) => read === "n2:true").length).toBeGreaterThan(2);

    const beforeFontReload = { ...dimensions.counts };
    Object.defineProperty(document, "fonts", {
      configurable: true,
      value: fontSet(Promise.resolve(document as unknown as FontFaceSet)),
    });
    fixture.place({ selectedNodeId: "n0" });
    expect(dimensions.counts.width).toBeGreaterThan(beforeFontReload.width);

    const beforeThemeChange = { ...dimensions.counts };
    fixture.host.classList.add("theme-updated");
    fixture.place({ selectedNodeId: "n0" });
    expect(dimensions.counts.width).toBeGreaterThan(beforeThemeChange.width);

    const beforeResize = { ...dimensions.counts };
    fixture.setSize(1050, 900);
    fixture.place({ selectedNodeId: "n0" });
    expect(dimensions.counts.width).toBeGreaterThan(beforeResize.width);
  } finally {
    dimensions.restore();
    if (savedFonts) Object.defineProperty(document, "fonts", savedFonts);
    else Reflect.deleteProperty(document, "fonts");
    fixture.cleanup();
  }
});
