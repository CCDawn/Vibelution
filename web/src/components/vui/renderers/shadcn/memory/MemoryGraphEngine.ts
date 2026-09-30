import type {
  MemoryKnowledgeGraphEdge,
  MemoryKnowledgeGraphNode,
} from "../../../../../api/types";
import type {
  MemoryGraphCluster,
  MemoryGraphClusterKey,
  PositionedMemoryKnowledgeGraphNode,
} from "../../../product/memory/memoryGraphModel";
import {
  buildMemoryGraphAdjacency,
  createMemoryGraphLabelElements,
  positionMemoryGraphLabels,
  type MemoryGraphEdgePath,
  type MemoryGraphLabelElements,
} from "./memoryGraphLabels";
import { memoryGraphRendererStyles as styles } from "./memoryGraphRenderer.styles";

type ThreeApi = typeof import("three");
type OrbitControlsApi = typeof import("three/addons/controls/OrbitControls.js").OrbitControls;
type Vector3 = import("three").Vector3;

type MemoryGraphTheme = {
  clusterColors: Map<MemoryGraphClusterKey, number>;
  edgeColor: number;
  selectedColor: number;
};

export type MemoryGraphEngine = {
  updateSelection: (id: string) => void;
  updateHighlights: (ids: string[]) => void;
  updateFlat: (flat: boolean) => void;
  refreshTheme: () => void;
  updateLabels: (visible: boolean) => void;
  focus: (id: string) => void;
  dispose: () => void;
};

export type CreateMemoryGraphEngineOptions = {
  THREE: ThreeApi;
  OrbitControls: OrbitControlsApi;
  host: HTMLDivElement;
  labelLayer: HTMLDivElement;
  nodes: readonly PositionedMemoryKnowledgeGraphNode[];
  clusters: readonly MemoryGraphCluster[];
  edges: readonly MemoryKnowledgeGraphEdge[];
  selectedNodeId: string;
  flat: boolean;
  highlightIds: string[];
  showLabels: boolean;
  onSelectNode: (id: string) => void;
  onSelectEdge: (id: string) => void;
  canSelectEdge: () => boolean;
  onFailure: (reason?: unknown) => void;
};

type MemoryGraphRuntimeScope = {
  readonly disposed: boolean;
  addCleanup: (cleanup: () => void) => void;
  dispose: () => void;
  fail: (reason: unknown) => void;
};

function createMemoryGraphRuntimeScope(onFailure: (reason?: unknown) => void): MemoryGraphRuntimeScope {
  let disposed = false;
  let failed = false;
  const cleanups: Array<() => void> = [];

  const dispose = () => {
    if (disposed) return;
    disposed = true;
    for (const cleanup of cleanups.splice(0).reverse()) {
      try {
        cleanup();
      } catch (error) {
        console.warn("[VMemoryGraphCanvas] renderer cleanup failed", error);
      }
    }
  };

  return {
    get disposed() {
      return disposed;
    },
    addCleanup(cleanup) {
      if (disposed) {
        cleanup();
        return;
      }
      cleanups.push(cleanup);
    },
    dispose,
    fail(reason) {
      if (disposed || failed) return;
      failed = true;
      dispose();
      try {
        onFailure(reason);
      } catch (error) {
        console.warn("[VMemoryGraphCanvas] renderer failure callback failed", error);
      }
    },
  };
}

const MUTED_CLUSTER_COLORS: Record<MemoryGraphClusterKey, number> = {
  workspace: 0xa8bda9,
  agents: 0x88b8b0,
  knowledge: 0x94aeca,
  sources: 0xacafc6,
  operations: 0xc1aa92,
};

function opaqueCssColor(value: string): string {
  const color = value.trim();
  const hexWithAlpha = color.match(/^#([\da-f]{4}|[\da-f]{8})$/i);
  if (hexWithAlpha) {
    return "#" + hexWithAlpha[1].slice(0, hexWithAlpha[1].length === 4 ? 3 : 6);
  }

  const rgba = color.match(/^rgba\(\s*(.*?)\s*\)$/i);
  if (!rgba) return color;
  const channels = rgba[1];
  const commaChannels = channels.split(",");
  if (commaChannels.length >= 4) {
    return "rgb(" + commaChannels.slice(0, 3).map((channel) => channel.trim()).join(", ") + ")";
  }
  const alphaSeparator = channels.indexOf("/");
  return "rgb(" + (alphaSeparator >= 0 ? channels.slice(0, alphaSeparator) : channels).trim() + ")";
}

function cssColor(
  THREE: ThreeApi,
  host: HTMLElement,
  property: string,
  fallback: string,
): number {
  const value = window.getComputedStyle(host).getPropertyValue(property).trim() || fallback;
  try {
    return new THREE.Color(opaqueCssColor(value)).getHex();
  } catch {
    return new THREE.Color(opaqueCssColor(fallback)).getHex();
  }
}

function readTheme(
  THREE: ThreeApi,
  host: HTMLElement,
  clusters: readonly MemoryGraphCluster[],
): MemoryGraphTheme {
  const computed = window.getComputedStyle(host);
  const surface = opaqueCssColor(
    computed.getPropertyValue("--vui-surface-workspace").trim() || "#0c0e13",
  );
  let lightSurface = false;
  try {
    const color = new THREE.Color(surface);
    const luminance = color.r * 0.2126 + color.g * 0.7152 + color.b * 0.0722;
    lightSurface = luminance > 0.52;
  } catch {
    lightSurface = false;
  }

  // The graph uses the subdued palette from the approved preview. The live VUI
  // surface token selects the light/dark treatment; these are chart colors, not
  // a second application theme or a replacement for semantic UI tokens.
  const clusterColors = new Map<MemoryGraphClusterKey, number>();
  for (const cluster of clusters) {
    const color = new THREE.Color(MUTED_CLUSTER_COLORS[cluster.key]);
    if (lightSurface) color.multiplyScalar(0.58);
    clusterColors.set(cluster.key, color.getHex());
  }
  return {
    clusterColors,
    edgeColor: cssColor(THREE, host, "--vui-border-strong", "rgb(135, 151, 170)"),
    selectedColor: cssColor(THREE, host, "--accent-cool", "#0a84ff"),
  };
}
function getNodeScale(node: MemoryKnowledgeGraphNode): number {
  switch (node.visual?.size) {
    case "root":
      return 1.35;
    case "group":
      return 1.18;
    case "container":
      return 1.06;
    case "leaf":
      return 0.9;
    case "support":
      return 0.8;
    default:
      return 1;
  }
}

function createNodeGeometry(THREE: ThreeApi, node: MemoryKnowledgeGraphNode): import("three").BufferGeometry {
  const size = getNodeScale(node);
  if (node.type === "knowledge_item") {
    return new THREE.TorusGeometry(0.21 * size, 0.046 * size, 8, 24);
  }
  if (node.type === "source_artifact" || node.type === "knowledge_batch") {
    return new THREE.OctahedronGeometry(0.19 * size, 0);
  }
  if (node.type === "agent" || node.type === "team") {
    return new THREE.IcosahedronGeometry(0.19 * size, 0);
  }
  if (node.type === "project") {
    return new THREE.DodecahedronGeometry(0.22 * size, 0);
  }
  return new THREE.SphereGeometry(0.155 * size, 12, 10);
}

function createClusterIsland(
  THREE: ThreeApi,
  nodes: readonly PositionedMemoryKnowledgeGraphNode[],
  cluster: MemoryGraphCluster,
  clusterIndex: number,
): { geometry: import("three").BufferGeometry; radiusX: number; radiusY: number; landZ: number } {
  const members = nodes.filter((node) => node.clusterKey === cluster.key);
  const radiusX = Math.max(2.2, ...members.map((node) => Math.abs(node.x - cluster.center.x) + 1.15));
  const radiusY = Math.max(1.8, ...members.map((node) => Math.abs(node.y - cluster.center.y) + 0.95));
  const points = 48;
  const shape = new THREE.Shape();
  for (let index = 0; index <= points; index += 1) {
    const angle = (index / points) * Math.PI * 2;
    const wobble =
      1 +
      0.055 * Math.sin(angle * 3 + clusterIndex) +
      0.032 * Math.cos(angle * 5 - clusterIndex * 0.6);
    const x = Math.cos(angle) * radiusX * wobble;
    const y = Math.sin(angle) * radiusY * wobble;
    if (index === 0) shape.moveTo(x, y);
    else shape.lineTo(x, y);
  }
  shape.closePath();
  const geometry = new THREE.ShapeGeometry(shape, points);
  const landZ = cluster.center.z - 0.68;
  geometry.translate(cluster.center.x, cluster.center.y, landZ);
  return { geometry, radiusX, radiusY, landZ };
}

function isReducedMotion(): boolean {
  return Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)").matches);
}

export function createMemoryGraphEngine(options: CreateMemoryGraphEngineOptions): MemoryGraphEngine | null {
  const runtime = createMemoryGraphRuntimeScope(options.onFailure);
  try {
    return initializeMemoryGraphEngine(options, runtime);
  } catch (error) {
    runtime.fail(error);
    return null;
  }
}

function initializeMemoryGraphEngine(
  options: CreateMemoryGraphEngineOptions,
  runtime: MemoryGraphRuntimeScope,
): MemoryGraphEngine {
  const {
    THREE,
    OrbitControls,
    host,
    labelLayer,
    nodes,
    clusters,
    edges,
    onSelectNode,
    onSelectEdge,
    canSelectEdge,
  } = options;

  const renderer = new THREE.WebGLRenderer({
    antialias: true,
    alpha: true,
    powerPreference: "low-power",
  });
  runtime.addCleanup(() => renderer.dispose());

  const scene = new THREE.Scene();
  runtime.addCleanup(() => scene.clear());
  const camera = new THREE.PerspectiveCamera(44, 1, 0.1, 220);
  const positions = new Map<string, Vector3>();
  for (const node of nodes) positions.set(node.id, new THREE.Vector3(node.x, node.y, node.z));

  const bounds = {
    minX: Infinity,
    maxX: -Infinity,
    minY: Infinity,
    maxY: -Infinity,
    minZ: Infinity,
    maxZ: -Infinity,
  };
  for (const node of nodes) {
    bounds.minX = Math.min(bounds.minX, node.x);
    bounds.maxX = Math.max(bounds.maxX, node.x);
    bounds.minY = Math.min(bounds.minY, node.y);
    bounds.maxY = Math.max(bounds.maxY, node.y);
    bounds.minZ = Math.min(bounds.minZ, node.z);
    bounds.maxZ = Math.max(bounds.maxZ, node.z);
  }

  const initialTarget = nodes.length
    ? new THREE.Vector3(
        (bounds.minX + bounds.maxX) / 2,
        (bounds.minY + bounds.maxY) / 2,
        (bounds.minZ + bounds.maxZ) / 2,
      )
    : new THREE.Vector3();
  const graphRadius = nodes.reduce(
    (radius, node) =>
      Math.max(
        radius,
        Math.hypot(
          node.x - initialTarget.x,
          node.y - initialTarget.y,
          node.z - initialTarget.z,
        ),
      ),
    0,
  ) + 4;
  const fieldOfView = camera.fov;
  const tangent = Math.tan(THREE.MathUtils.degToRad(fieldOfView / 2));
  const contentWidth = nodes.length ? bounds.maxX - bounds.minX + 5 : 12;
  const contentHeight = nodes.length ? bounds.maxY - bounds.minY + 5 : 12;
  const initialAspect = Math.max(0.65, host.clientWidth / Math.max(1, host.clientHeight));
  const initialDistance = Math.max(
    18,
    Math.max(contentHeight / (2 * tangent), contentWidth / (2 * tangent * initialAspect)) * 1.1,
  );
  let overviewDistance = initialDistance;
  const perspectiveDirection = new THREE.Vector3(0, Math.sin(THREE.MathUtils.degToRad(15)), Math.cos(THREE.MathUtils.degToRad(15))).normalize();
  const initialCameraPosition = initialTarget.clone().add(perspectiveDirection.clone().multiplyScalar(overviewDistance));
  const flatOverviewPosition = initialTarget.clone().add(new THREE.Vector3(0, 0, overviewDistance));
  camera.position.copy(options.flat ? flatOverviewPosition : initialCameraPosition);
  camera.up.set(0, 1, 0);
  camera.lookAt(initialTarget);

  const canvas = renderer.domElement;
  canvas.className = styles.canvas;
  canvas.setAttribute("aria-hidden", "true");
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75));
  renderer.setClearColor(0x000000, 0);
  host.replaceChildren(canvas);
  runtime.addCleanup(() => {
    if (canvas.parentElement === host) canvas.remove();
  });

  const controls = new OrbitControls(camera, canvas);
  runtime.addCleanup(() => controls.dispose());
  controls.target.copy(initialTarget);
  controls.enableDamping = !isReducedMotion();
  controls.dampingFactor = 0.075;
  controls.screenSpacePanning = true;
  controls.enablePan = true;
  controls.enableZoom = true;
  controls.rotateSpeed = 0.58;
  controls.panSpeed = 0.82;
  controls.zoomSpeed = 0.78;
  controls.minDistance = 5;
  controls.maxDistance = Math.max(42, overviewDistance * 2.35);
  camera.far = Math.max(220, controls.maxDistance + graphRadius * 1.5 + 10);
  camera.updateProjectionMatrix();
  controls.minPolarAngle = Math.PI / 2 - THREE.MathUtils.degToRad(26);
  controls.maxPolarAngle = Math.PI / 2 + THREE.MathUtils.degToRad(26);

  const configureInputMode = (flat: boolean) => {
    controls.enableRotate = !flat;
    controls.mouseButtons.LEFT = flat ? THREE.MOUSE.PAN : THREE.MOUSE.ROTATE;
    controls.mouseButtons.MIDDLE = THREE.MOUSE.DOLLY;
    controls.mouseButtons.RIGHT = THREE.MOUSE.PAN;
    controls.touches.ONE = flat ? THREE.TOUCH.PAN : THREE.TOUCH.ROTATE;
    controls.touches.TWO = THREE.TOUCH.DOLLY_PAN;
  };
  configureInputMode(options.flat);
  controls.update();

  const geometries: import("three").BufferGeometry[] = [];
  const materials: import("three").Material[] = [];
  runtime.addCleanup(() => {
    for (const geometry of geometries) {
      try {
        geometry.dispose();
      } catch (error) {
        console.warn("[VMemoryGraphCanvas] geometry cleanup failed", error);
      }
    }
    for (const material of materials) {
      try {
        material.dispose();
      } catch (error) {
        console.warn("[VMemoryGraphCanvas] material cleanup failed", error);
      }
    }
    geometries.length = 0;
    materials.length = 0;
  });
  const disposeGeometry = <T extends import("three").BufferGeometry>(geometry: T): T => {
    geometries.push(geometry);
    return geometry;
  };
  const disposeMaterial = <T extends import("three").Material>(material: T): T => {
    materials.push(material);
    return material;
  };

  const theme = readTheme(THREE, host, clusters);
  const nodeGroups = new Map<string, import("three").Group>();
  const nodeMaterials = new Map<string, {
    body: import("three").MeshBasicMaterial;
    ring: import("three").MeshBasicMaterial;
    clusterKey: MemoryGraphClusterKey;
  }>();
  const islandMaterials = new Map<MemoryGraphClusterKey, {
    land: import("three").MeshBasicMaterial;
    contour: import("three").LineBasicMaterial;
  }>();
  const hitObjects = new Map<string, import("three").Mesh>();
  const edgePaths: MemoryGraphEdgePath[] = [];
  const edgeVisuals: Array<{
    edge: MemoryKnowledgeGraphEdge;
    material: import("three").LineBasicMaterial;
    arrow: import("three").Mesh;
    arrowMaterial: import("three").MeshBasicMaterial;
  }> = [];
  const adjacency = buildMemoryGraphAdjacency(nodes, edges);
  runtime.addCleanup(() => {
    positions.clear();
    nodeGroups.clear();
    nodeMaterials.clear();
    islandMaterials.clear();
    hitObjects.clear();
    edgePaths.length = 0;
    edgeVisuals.length = 0;
    adjacency.adjacent.clear();
    adjacency.degree.clear();
  });
  runtime.addCleanup(() => labelLayer.replaceChildren());
  const labelElements: MemoryGraphLabelElements = createMemoryGraphLabelElements(
    labelLayer,
    nodes,
    edges,
    clusters,
    onSelectNode,
    onSelectEdge,
    canSelectEdge,
  );
  runtime.addCleanup(() => {
    labelElements.nodeButtons.clear();
    labelElements.edgeButtons.clear();
    labelElements.clusterHeadings.clear();
  });

  let selectedNodeId = options.selectedNodeId;
  let highlightedIds = new Set(options.highlightIds);
  let labelsVisible = options.showLabels;
  let flatMode = options.flat;
  let frameId = 0;
  let contextLost = false;
  runtime.addCleanup(() => {
    if (frameId) window.cancelAnimationFrame(frameId);
    frameId = 0;
  });
  let focusAnimation: {
    fromPosition: Vector3;
    toPosition: Vector3;
    fromTarget: Vector3;
    toTarget: Vector3;
    startedAt: number;
    duration: number;
  } | null = null;
  let savedPerspective: { position: Vector3; target: Vector3 } | null = null;
  let pointerStart: { x: number; y: number } | null = null;
  let reducedMotion = isReducedMotion();

  for (const [index, cluster] of clusters.entries()) {
    const clusterColor = theme.clusterColors.get(cluster.key) ?? theme.selectedColor;
    const island = createClusterIsland(THREE, nodes, cluster, index);
    const landMaterial = disposeMaterial(
      new THREE.MeshBasicMaterial({
        color: clusterColor,
        transparent: true,
        opacity: 0.045,
        depthWrite: false,
        side: THREE.DoubleSide,
      }),
    );
    const land = new THREE.Mesh(disposeGeometry(island.geometry), landMaterial);
    land.renderOrder = -2;
    scene.add(land);

    const contourPoints: Vector3[] = [];
    for (let point = 0; point <= 64; point += 1) {
      const angle = (point / 64) * Math.PI * 2;
      const wobble =
        1 +
        0.055 * Math.sin(angle * 3 + index) +
        0.032 * Math.cos(angle * 5 - index * 0.6);
      contourPoints.push(
        new THREE.Vector3(
          cluster.center.x + Math.cos(angle) * island.radiusX * wobble,
          cluster.center.y + Math.sin(angle) * island.radiusY * wobble,
          island.landZ + 0.018,
        ),
      );
    }
    const contourMaterial = disposeMaterial(
      new THREE.LineBasicMaterial({
        color: clusterColor,
        transparent: true,
        opacity: 0.17,
        depthWrite: false,
      }),
    );
    const contour = new THREE.Line(
      disposeGeometry(new THREE.BufferGeometry().setFromPoints(contourPoints)),
      contourMaterial,
    );
    contour.renderOrder = -1;
    scene.add(contour);
    islandMaterials.set(cluster.key, { land: landMaterial, contour: contourMaterial });
  }

  for (const edge of edges) {
    const start = positions.get(edge.source);
    const end = positions.get(edge.target);
    if (!start || !end) continue;

    const middle = start.clone().add(end).multiplyScalar(0.5);
    middle.z += 0.22 + Math.min(0.32, start.distanceTo(end) * 0.02);
    const curve = new THREE.QuadraticBezierCurve3(start, middle, end);
    const lineMaterial = disposeMaterial(
      new THREE.LineBasicMaterial({
        color: theme.edgeColor,
        transparent: true,
        opacity: 0.15,
        depthWrite: false,
      }),
    );
    const line = new THREE.Line(
      disposeGeometry(new THREE.BufferGeometry().setFromPoints(curve.getPoints(20))),
      lineMaterial,
    );
    line.frustumCulled = false;
    scene.add(line);

    const arrowMaterial = disposeMaterial(
      new THREE.MeshBasicMaterial({
        color: theme.selectedColor,
        transparent: true,
        opacity: 0.9,
        depthWrite: false,
      }),
    );
    const arrow = new THREE.Mesh(
      disposeGeometry(new THREE.ConeGeometry(0.075, 0.22, 8)),
      arrowMaterial,
    );
    const arrowPosition = 0.78;
    arrow.position.copy(curve.getPoint(arrowPosition));
    arrow.quaternion.setFromUnitVectors(
      new THREE.Vector3(0, 1, 0),
      curve.getTangent(arrowPosition).normalize(),
    );
    arrow.visible = false;
    arrow.renderOrder = 1;
    scene.add(arrow);

    edgePaths.push({ edge, curve });
    edgeVisuals.push({ edge, material: lineMaterial, arrow, arrowMaterial });
  }

  for (const node of nodes) {
    const colorHex = theme.clusterColors.get(node.clusterKey) ?? theme.selectedColor;
    const group = new THREE.Group();
    group.position.set(node.x, node.y, node.z);
    const bodyMaterial = disposeMaterial(
      new THREE.MeshBasicMaterial({ color: colorHex, transparent: true, opacity: 0.88 }),
    );
    const ringMaterial = disposeMaterial(
      new THREE.MeshBasicMaterial({
        color: colorHex,
        side: THREE.DoubleSide,
        transparent: true,
        opacity: 0.1,
        depthWrite: false,
      }),
    );
    const body = new THREE.Mesh(disposeGeometry(createNodeGeometry(THREE, node.source)), bodyMaterial);
    const scale = getNodeScale(node.source);
    const ring = new THREE.Mesh(
      disposeGeometry(new THREE.TorusGeometry(0.3 * scale, 0.012, 6, 32)),
      ringMaterial,
    );
    const hitArea = new THREE.Mesh(
      disposeGeometry(new THREE.SphereGeometry(0.44 * scale, 8, 8)),
      disposeMaterial(
        new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false }),
      ),
    );
    hitArea.userData.nodeId = node.id;
    group.add(ring, body, hitArea);
    scene.add(group);
    nodeGroups.set(node.id, group);
    nodeMaterials.set(node.id, { body: bodyMaterial, ring: ringMaterial, clusterKey: node.clusterKey });
    hitObjects.set(node.id, hitArea);
  }

  const raycaster = new THREE.Raycaster();
  const pointer = new THREE.Vector2();
  const scratch = new THREE.Vector3();
  const reducedMotionQuery = window.matchMedia?.("(prefers-reduced-motion: reduce)");

  const invalidate = () => {
    if (runtime.disposed || contextLost || frameId) return;
    try {
      frameId = window.requestAnimationFrame(drawFrame);
    } catch (error) {
      runtime.fail(error);
    }
  };

  function updateSelection(id: string) {
    if (runtime.disposed) return;
    selectedNodeId = id;
    const neighbors = adjacency.adjacent.get(id) ?? new Set<string>();
    const hasContext = Boolean(id) || highlightedIds.size > 0;
    for (const node of nodes) {
      const selected = node.id === id;
      const neighbor = neighbors.has(node.id);
      const highlighted = highlightedIds.has(node.id);
      const group = nodeGroups.get(node.id);
      const appearance = nodeMaterials.get(node.id);
      if (group) group.scale.setScalar(selected ? 1.14 : neighbor || highlighted ? 1.05 : hasContext ? 0.9 : 1);
      if (appearance) {
        appearance.body.opacity = selected ? 1 : neighbor || highlighted ? 0.98 : hasContext ? 0.28 : 0.86;
        appearance.ring.opacity = selected ? 0.76 : neighbor || highlighted ? 0.4 : hasContext ? 0.035 : 0.08;
      }
    }
    for (const visual of edgeVisuals) {
      const connected = Boolean(id && (visual.edge.source === id || visual.edge.target === id));
      const highlighted =
        highlightedIds.has(visual.edge.source) || highlightedIds.has(visual.edge.target);
      visual.material.opacity = connected ? 0.56 : highlighted ? 0.36 : hasContext ? 0.035 : 0.15;
      visual.arrow.visible = connected;
      visual.arrowMaterial.opacity = connected ? 0.94 : 0;
    }
    invalidate();
  }

  function updateHighlights(ids: string[]) {
    if (runtime.disposed) return;
    highlightedIds = new Set(ids);
    updateSelection(selectedNodeId);
  }

  function refreshTheme() {
    if (runtime.disposed) return;
    const next = readTheme(THREE, host, clusters);
    theme.clusterColors.clear();
    for (const [key, color] of next.clusterColors) theme.clusterColors.set(key, color);
    theme.edgeColor = next.edgeColor;
    theme.selectedColor = next.selectedColor;

    for (const appearance of nodeMaterials.values()) {
      const color = theme.clusterColors.get(appearance.clusterKey) ?? theme.selectedColor;
      appearance.body.color.setHex(color);
      appearance.ring.color.setHex(color);
    }
    for (const [key, appearance] of islandMaterials) {
      const color = theme.clusterColors.get(key) ?? theme.selectedColor;
      appearance.land.color.setHex(color);
      appearance.contour.color.setHex(color);
    }
    for (const visual of edgeVisuals) {
      visual.material.color.setHex(theme.edgeColor);
      visual.arrowMaterial.color.setHex(theme.selectedColor);
    }
    invalidate();
  }

  function drawFrame(now: number) {
    frameId = 0;
    if (runtime.disposed || contextLost) return;
    try {
      if (focusAnimation) {
        const progress = Math.min(1, (now - focusAnimation.startedAt) / focusAnimation.duration);
        const eased = 1 - Math.pow(1 - progress, 3);
        camera.position.lerpVectors(focusAnimation.fromPosition, focusAnimation.toPosition, eased);
        controls.target.lerpVectors(focusAnimation.fromTarget, focusAnimation.toTarget, eased);
        if (progress >= 1) focusAnimation = null;
      }
      controls.update();
      renderer.render(scene, camera);
      positionMemoryGraphLabels({
        host,
        labelLayer,
        camera,
        fieldOfView,
        nodes,
        clusters,
        edgePaths,
        elements: labelElements,
        adjacent: adjacency.adjacent,
        degree: adjacency.degree,
        selectedNodeId,
        highlightIds: highlightedIds,
        labelsVisible,
        overviewDistance,
        cameraTarget: controls.target,
        canSelectEdge,
        scratch,
      });
      if (focusAnimation) invalidate();
    } catch (error) {
      contextLost = true;
      runtime.fail(error);
    }
  }

  function animateCamera(targetPosition: Vector3, distance?: number) {
    if (runtime.disposed) return;
    const fromPosition = camera.position.clone();
    const fromTarget = controls.target.clone();
    const direction = camera.position.clone().sub(controls.target).normalize();
    const preferredDistance = distance ?? Math.min(18, Math.max(10, camera.position.distanceTo(controls.target)));
    const toTarget = targetPosition.clone();
    const toPosition = toTarget.clone().add(direction.multiplyScalar(preferredDistance));
    if (reducedMotion) {
      focusAnimation = null;
      camera.position.copy(toPosition);
      controls.target.copy(toTarget);
      controls.update();
      invalidate();
      return;
    }
    focusAnimation = {
      fromPosition,
      toPosition,
      fromTarget,
      toTarget,
      startedAt: performance.now(),
      duration: 420,
    };
    invalidate();
  }

  function focus(id: string) {
    if (!id) {
      animateCamera(initialTarget, overviewDistance);
      return;
    }
    const position = positions.get(id);
    if (position) animateCamera(position);
  }

  function updateFlat(next: boolean) {
    if (runtime.disposed) return;
    if (flatMode === next) return;
    const fromPosition = camera.position.clone();
    const fromTarget = controls.target.clone();
    let toPosition: Vector3;
    let toTarget: Vector3;
    if (next) {
      savedPerspective = { position: fromPosition.clone(), target: fromTarget.clone() };
      configureInputMode(true);
      toTarget = initialTarget.clone();
      toPosition = flatOverviewPosition.clone();
    } else {
      configureInputMode(false);
      toTarget = savedPerspective?.target.clone() ?? initialTarget.clone();
      toPosition = savedPerspective?.position.clone() ?? initialCameraPosition.clone();
    }
    flatMode = next;
    if (reducedMotion) {
      camera.position.copy(toPosition);
      controls.target.copy(toTarget);
      controls.update();
      focusAnimation = null;
    } else {
      focusAnimation = {
        fromPosition,
        toPosition,
        fromTarget,
        toTarget,
        startedAt: performance.now(),
        duration: 360,
      };
    }
    invalidate();
  }

  function updateLabels(visible: boolean) {
    if (runtime.disposed) return;
    labelsVisible = visible;
    invalidate();
  }

  function resize() {
    if (runtime.disposed) return;
    const width = Math.max(1, host.clientWidth);
    const height = Math.max(1, host.clientHeight);
    const oldOverview = flatMode ? flatOverviewPosition : initialCameraPosition;
    const wasOverview =
      camera.position.distanceTo(oldOverview) < 0.5 &&
      controls.target.distanceTo(initialTarget) < 0.5;
    camera.aspect = width / height;
    const nextDistance = Math.max(
      18,
      Math.max(contentHeight / (2 * tangent), contentWidth / (2 * tangent * camera.aspect)) * 1.1,
    );
    overviewDistance = nextDistance;
    initialCameraPosition.copy(initialTarget).add(perspectiveDirection.clone().multiplyScalar(nextDistance));
    flatOverviewPosition.copy(initialTarget).add(new THREE.Vector3(0, 0, nextDistance));
    controls.maxDistance = Math.max(42, nextDistance * 2.35);
    camera.far = Math.max(220, controls.maxDistance + graphRadius * 1.5 + 10);
    if (wasOverview && !focusAnimation) {
      camera.position.copy(flatMode ? flatOverviewPosition : initialCameraPosition);
      controls.target.copy(initialTarget);
      controls.update();
    }
    camera.updateProjectionMatrix();
    renderer.setSize(width, height, false);
    invalidate();
  }

  function onCanvasClick(event: MouseEvent) {
    if (!pointerStart) return;
    const moved = Math.hypot(event.clientX - pointerStart.x, event.clientY - pointerStart.y);
    pointerStart = null;
    if (moved > 5) return;
    const rect = canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    pointer.set(
      ((event.clientX - rect.left) / rect.width) * 2 - 1,
      -((event.clientY - rect.top) / rect.height) * 2 + 1,
    );
    raycaster.setFromCamera(pointer, camera);
    const hit = raycaster.intersectObjects([...hitObjects.values()], false)[0]?.object;
    const id = hit?.userData.nodeId;
    if (typeof id === "string") onSelectNode(id);
  }

  function onPointerDown(event: PointerEvent) {
    if (event.button === 0) pointerStart = { x: event.clientX, y: event.clientY };
  }

  function onPointerCancel() {
    pointerStart = null;
  }

  function onContextMenu(event: MouseEvent) {
    event.preventDefault();
  }

  function onContextLost(event: Event) {
    event.preventDefault();
    contextLost = true;
    runtime.fail(new Error("The WebGL rendering context was lost."));
  }

  function onMotionPreferenceChange(event: MediaQueryListEvent) {
    if (runtime.disposed) return;
    reducedMotion = event.matches;
    controls.enableDamping = !reducedMotion;
    if (reducedMotion && focusAnimation) {
      camera.position.copy(focusAnimation.toPosition);
      controls.target.copy(focusAnimation.toTarget);
      focusAnimation = null;
    }
    invalidate();
  }

  const runSafely = (action: () => void) => {
    if (runtime.disposed) return;
    try {
      action();
    } catch (error) {
      runtime.fail(error);
    }
  };
  const onControlsChange = () => invalidate();
  const onResize = () => runSafely(resize);
  const onCanvasClickSafely = (event: MouseEvent) => runSafely(() => onCanvasClick(event));
  const onPointerDownSafely = (event: PointerEvent) => runSafely(() => onPointerDown(event));
  const onPointerCancelSafely = () => runSafely(onPointerCancel);
  const onContextMenuSafely = (event: MouseEvent) => runSafely(() => onContextMenu(event));
  const onMotionPreferenceChangeSafely = (event: MediaQueryListEvent) =>
    runSafely(() => onMotionPreferenceChange(event));
  const resizeObserver = typeof ResizeObserver !== "undefined" ? new ResizeObserver(onResize) : null;
  runtime.addCleanup(() => resizeObserver?.disconnect());
  runtime.addCleanup(() => {
    window.removeEventListener("resize", onResize);
    controls.removeEventListener("change", onControlsChange);
    canvas.removeEventListener("pointerdown", onPointerDownSafely);
    canvas.removeEventListener("pointercancel", onPointerCancelSafely);
    canvas.removeEventListener("click", onCanvasClickSafely);
    canvas.removeEventListener("contextmenu", onContextMenuSafely);
    canvas.removeEventListener("webglcontextlost", onContextLost, false);
    reducedMotionQuery?.removeEventListener("change", onMotionPreferenceChangeSafely);
  });

  controls.addEventListener("change", onControlsChange);
  canvas.addEventListener("pointerdown", onPointerDownSafely);
  canvas.addEventListener("pointercancel", onPointerCancelSafely);
  canvas.addEventListener("click", onCanvasClickSafely);
  canvas.addEventListener("contextmenu", onContextMenuSafely);
  canvas.addEventListener("webglcontextlost", onContextLost, false);
  reducedMotionQuery?.addEventListener("change", onMotionPreferenceChangeSafely);
  resizeObserver?.observe(host);
  window.addEventListener("resize", onResize);
  controls.update();
  resize();
  updateSelection(selectedNodeId);
  updateHighlights(options.highlightIds);
  updateLabels(options.showLabels);
  refreshTheme();
  invalidate();

  const guard = <TArgs extends unknown[]>(action: (...args: TArgs) => void) =>
    (...args: TArgs) => runSafely(() => action(...args));

  return {
    updateSelection: guard(updateSelection),
    updateHighlights: guard(updateHighlights),
    updateFlat: guard(updateFlat),
    refreshTheme: guard(refreshTheme),
    updateLabels: guard(updateLabels),
    focus: guard(focus),
    dispose: runtime.dispose,
  };
}
