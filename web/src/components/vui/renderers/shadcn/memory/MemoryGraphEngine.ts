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
import { nebulaMaterial } from "./NebulaField";
import { createMemoryGraphBatches } from "./MemoryGraphBatches";
import { memoryGraphRendererStyles as styles } from "./memoryGraphRenderer.styles";

type ThreeApi = typeof import("three");
type OrbitControlsApi = typeof import("three/addons/controls/OrbitControls.js").OrbitControls;
type Vector3 = import("three").Vector3;

type MemoryGraphTheme = {
  clusterColors: Map<MemoryGraphClusterKey, number>;
  edgeColor: number;
  selectedColor: number;
  lightSurface: boolean;
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
    lightSurface,
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
    return new THREE.SphereGeometry(0.205 * size, 32, 24);
  }
  if (node.type === "source_artifact" || node.type === "knowledge_batch") {
    return new THREE.OctahedronGeometry(0.235 * size, 0);
  }
  if (node.type === "agent" || node.type === "team") {
    return new THREE.IcosahedronGeometry(0.27 * size, 1);
  }
  if (node.type === "project") {
    return new THREE.DodecahedronGeometry(0.235 * size, 0);
  }
  return new THREE.SphereGeometry(0.18 * size, 32, 24);
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
  scene.add(new THREE.HemisphereLight(0xe1eeff, 0x29313a, 1.65));
  const keyLight = new THREE.DirectionalLight(0xf0f3ed, 1.05);
  keyLight.position.set(-12, 18, 25);
  scene.add(keyLight);
  const rimLight = new THREE.DirectionalLight(0x9fbedb, 0.65);
  rimLight.position.set(15, -4, -14);
  scene.add(rimLight);
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
  const contentDepth = nodes.length ? bounds.maxZ - bounds.minZ : 0;
  const initialAspect = Math.max(0.65, host.clientWidth / Math.max(1, host.clientHeight));
  const planarFitDistance = Math.max(
    18,
    Math.max(contentHeight / (2 * tangent), contentWidth / (2 * tangent * initialAspect)) * 1.1,
  );
  const initialDistance = planarFitDistance + contentDepth * 0.5;
  let overviewDistance = initialDistance;
  const perspectiveDirection = new THREE.Vector3(0.32, 0.22, 1).normalize();
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
  controls.minPolarAngle = 0.04;
  controls.maxPolarAngle = Math.PI - 0.04;

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
  const clusterMaterials = new Map<MemoryGraphClusterKey, {
    nebula: import("three").ShaderMaterial;
    dust: import("three").PointsMaterial;
  }>();
  const edgePaths: MemoryGraphEdgePath[] = [];
  const adjacency = buildMemoryGraphAdjacency(nodes, edges);
  runtime.addCleanup(() => {
    positions.clear();
    clusterMaterials.clear();
    edgePaths.length = 0;
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
    const members = nodes.filter((node) => node.clusterKey === cluster.key);
    if (!members.length || options.flat) continue;
    const clusterColor = theme.clusterColors.get(cluster.key) ?? theme.selectedColor;
    const center = new THREE.Vector3(cluster.center.x, cluster.center.y, cluster.center.z);
    const radius = Math.max(
      2.6,
      ...members.map((node) => positions.get(node.id)?.distanceTo(center) ?? 0),
    ) + 1.1;
    const nebula = disposeMaterial(
      nebulaMaterial(THREE, center, radius, clusterColor, index * 11.71, theme.lightSurface ? 0.65 : 1),
    );
    const cloud = new THREE.Mesh(
      disposeGeometry(new THREE.SphereGeometry(radius, 28, 20)),
      nebula,
    );
    cloud.position.copy(center);
    cloud.renderOrder = -3;
    scene.add(cloud);

    const dustPositions: number[] = [];
    for (let star = 0; star < 44; star += 1) {
      const vertical = 1 - (2 * (star + 0.5)) / 44;
      const angle = star * 2.39996323;
      const radial = radius * 0.84 * Math.cbrt((((star * 17) % 43) + 1) / 44);
      const circle = Math.sqrt(1 - vertical * vertical);
      dustPositions.push(
        center.x + radial * circle * Math.cos(angle),
        center.y + radial * vertical,
        center.z + radial * circle * Math.sin(angle),
      );
    }
    const dustGeometry = disposeGeometry(new THREE.BufferGeometry());
    dustGeometry.setAttribute("position", new THREE.Float32BufferAttribute(dustPositions, 3));
    const dust = disposeMaterial(
      new THREE.PointsMaterial({
        color: clusterColor,
        size: 0.026,
        transparent: true,
        opacity: 0.42,
        depthWrite: false,
      }),
    );
    scene.add(new THREE.Points(dustGeometry, dust));
    clusterMaterials.set(cluster.key, { nebula, dust });
  }

  for (const edge of edges) {
    const start = positions.get(edge.source);
    const end = positions.get(edge.target);
    if (!start || !end) continue;

    const middle = start.clone().add(end).multiplyScalar(0.5);
    if (!options.flat) middle.z += 0.22 + Math.min(0.32, start.distanceTo(end) * 0.02);
    const curve = new THREE.QuadraticBezierCurve3(start, middle, end);
    edgePaths.push({ edge, curve });
  }

  const batches = createMemoryGraphBatches({
    THREE, scene, nodes, edgePaths, theme,
    createNodeGeometry: (node) => createNodeGeometry(THREE, node),
    getNodeScale, disposeGeometry, disposeMaterial,
  });
  runtime.addCleanup(() => batches.dispose());
  const hitObjects = batches.hits;

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
    batches.updateSelection(id, neighbors, highlightedIds);
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

    batches.refreshTheme(next);
    for (const [key, appearance] of clusterMaterials) {
      const color = theme.clusterColors.get(key) ?? theme.selectedColor;
      appearance.nebula.uniforms.tint.value.setHex(color);
      appearance.nebula.uniforms.strength.value = next.lightSurface ? 0.65 : 1;
      appearance.dust.color.setHex(color);
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
    const planarFitDistance = Math.max(
      18,
      Math.max(contentHeight / (2 * tangent), contentWidth / (2 * tangent * camera.aspect)) * 1.1,
    );
    const nextDistance = planarFitDistance + contentDepth * 0.5;
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
  const onFontsLoaded = () => invalidate();
  const labelEvents = ["pointerover", "pointerout", "focusin", "focusout"] as const;
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
    document.fonts?.removeEventListener("loadingdone", onFontsLoaded);
    for (const event of labelEvents) labelLayer.removeEventListener(event, onControlsChange);
    canvas.removeEventListener("pointerdown", onPointerDownSafely);
    canvas.removeEventListener("pointercancel", onPointerCancelSafely);
    canvas.removeEventListener("click", onCanvasClickSafely);
    canvas.removeEventListener("contextmenu", onContextMenuSafely);
    canvas.removeEventListener("webglcontextlost", onContextLost, false);
    reducedMotionQuery?.removeEventListener("change", onMotionPreferenceChangeSafely);
  });

  controls.addEventListener("change", onControlsChange);
  document.fonts?.addEventListener("loadingdone", onFontsLoaded);
  for (const event of labelEvents) labelLayer.addEventListener(event, onControlsChange);
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
