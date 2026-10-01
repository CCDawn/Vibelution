import type { MemoryKnowledgeGraphNode } from "../../../../../api/types";
import type { MemoryGraphClusterKey, PositionedMemoryKnowledgeGraphNode } from "../../../product/memory/memoryGraphModel";
import type { MemoryGraphEdgePath } from "./memoryGraphLabels";

type ThreeApi = typeof import("three");
type GraphTheme = {
  clusterColors: Map<MemoryGraphClusterKey, number>;
  edgeColor: number;
  selectedColor: number;
  lightSurface: boolean;
};

// Opacity is an instance/vertex attribute so selection does not split a batch
// into hundreds of materials. Keep the original Three lighting and geometry.
function attributeOpacity(material: import("three").Material) {
  material.onBeforeCompile = (shader) => {
    shader.vertexShader = shader.vertexShader
      .replace("#include <common>", "#include <common>\nattribute float graphOpacity;\nvarying float vGraphOpacity;")
      .replace("#include <begin_vertex>", "#include <begin_vertex>\nvGraphOpacity = graphOpacity;");
    shader.fragmentShader = shader.fragmentShader
      .replace("#include <common>", "#include <common>\nvarying float vGraphOpacity;")
      .replace("#include <color_fragment>", "#include <color_fragment>\ndiffuseColor.a *= vGraphOpacity;");
  };
  material.customProgramCacheKey = () => "memory-graph-opacity-v1";
}

export function createMemoryGraphBatches(options: {
  THREE: ThreeApi;
  scene: import("three").Scene;
  nodes: readonly PositionedMemoryKnowledgeGraphNode[];
  edgePaths: readonly MemoryGraphEdgePath[];
  theme: GraphTheme;
  createNodeGeometry: (node: MemoryKnowledgeGraphNode) => import("three").BufferGeometry;
  getNodeScale: (node: MemoryKnowledgeGraphNode) => number;
  disposeGeometry: <T extends import("three").BufferGeometry>(geometry: T) => T;
  disposeMaterial: <T extends import("three").Material>(material: T) => T;
}) {
  const { THREE, scene, nodes, edgePaths, theme, createNodeGeometry, getNodeScale, disposeGeometry, disposeMaterial } = options;
  const hits = new Map<string, import("three").Mesh>();
  const hitGeometry = disposeGeometry(new THREE.SphereGeometry(0.44, 8, 8));
  const hitMaterial = disposeMaterial(new THREE.MeshBasicMaterial());
  const transform = new THREE.Object3D();
  const groups = new Map<string, PositionedMemoryKnowledgeGraphNode[]>();
  for (const node of nodes) {
    const key = `${node.clusterKey}:${node.source.type}:${getNodeScale(node.source)}`;
    const members = groups.get(key) ?? [];
    members.push(node);
    groups.set(key, members);
    // Raycaster accepts objects outside the render scene. No transparent
    // fragment or draw call is needed for these deliberately larger targets.
    const hit = new THREE.Mesh(hitGeometry, hitMaterial);
    hit.position.set(node.x, node.y, node.z);
    hit.scale.setScalar(getNodeScale(node.source));
    hit.updateMatrixWorld();
    hit.userData.nodeId = node.id;
    hits.set(node.id, hit);
  }
  const batches = [...groups.values()].map((members) => {
    const first = members[0];
    const color = theme.clusterColors.get(first.clusterKey) ?? theme.selectedColor;
    const bodyMaterial = disposeMaterial(new THREE.MeshStandardMaterial({
      color, roughness: 0.96, metalness: 0, emissive: color,
      emissiveIntensity: theme.lightSurface ? 0.02 : 0.09, transparent: true,
    }));
    const ringMaterial = disposeMaterial(new THREE.MeshBasicMaterial({
      color, side: THREE.DoubleSide, transparent: true, depthWrite: false,
    }));
    attributeOpacity(bodyMaterial);
    attributeOpacity(ringMaterial);
    const bodyGeometry = disposeGeometry(createNodeGeometry(first.source));
    const ringGeometry = disposeGeometry(new THREE.TorusGeometry(0.3 * getNodeScale(first.source), 0.012, 6, 32));
    const bodyOpacity = new THREE.InstancedBufferAttribute(new Float32Array(members.length), 1);
    const ringOpacity = new THREE.InstancedBufferAttribute(new Float32Array(members.length), 1);
    bodyGeometry.setAttribute("graphOpacity", bodyOpacity);
    ringGeometry.setAttribute("graphOpacity", ringOpacity);
    const body = new THREE.InstancedMesh(bodyGeometry, bodyMaterial, members.length);
    const ring = new THREE.InstancedMesh(ringGeometry, ringMaterial, members.length);
    body.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    ring.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    body.frustumCulled = ring.frustumCulled = false;
    body.userData.memoryGraphBatch = "nodes";
    ring.userData.memoryGraphBatch = "rings";
    scene.add(ring, body);
    return { members, clusterKey: first.clusterKey, body, ring, bodyMaterial, ringMaterial, bodyOpacity, ringOpacity };
  });

  const linePositions: number[] = [];
  const ranges = edgePaths.map((path) => {
    const start = linePositions.length / 3;
    const points = path.curve.getPoints(20);
    for (let i = 1; i < points.length; i++) {
      linePositions.push(...points[i - 1].toArray(), ...points[i].toArray());
    }
    transform.position.copy(path.curve.getPoint(0.78));
    transform.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), path.curve.getTangent(0.78).normalize());
    transform.scale.setScalar(1);
    transform.updateMatrix();
    return { edge: path.edge, start, count: linePositions.length / 3 - start, arrowMatrix: transform.matrix.clone() };
  });
  const lineGeometry = disposeGeometry(new THREE.BufferGeometry());
  lineGeometry.setAttribute("position", new THREE.Float32BufferAttribute(linePositions, 3));
  const lineOpacity = new THREE.Float32BufferAttribute(new Float32Array(linePositions.length / 3), 1);
  lineOpacity.setUsage(THREE.DynamicDrawUsage);
  lineGeometry.setAttribute("graphOpacity", lineOpacity);
  const lineMaterial = disposeMaterial(new THREE.LineBasicMaterial({ color: theme.edgeColor, transparent: true, depthWrite: false }));
  attributeOpacity(lineMaterial);
  const lines = new THREE.LineSegments(lineGeometry, lineMaterial);
  lines.frustumCulled = false;
  lines.userData.memoryGraphBatch = "edges";
  scene.add(lines);
  const arrowMaterial = disposeMaterial(new THREE.MeshBasicMaterial({ color: theme.selectedColor, transparent: true, opacity: 0.94, depthWrite: false }));
  const arrows = new THREE.InstancedMesh(disposeGeometry(new THREE.ConeGeometry(0.075, 0.22, 8)), arrowMaterial, Math.max(1, ranges.length));
  arrows.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
  arrows.frustumCulled = false;
  arrows.renderOrder = 1;
  arrows.count = 0;
  arrows.userData.memoryGraphBatch = "arrows";
  scene.add(arrows);

  function updateSelection(id: string, neighbors: ReadonlySet<string>, highlights: ReadonlySet<string>) {
    const hasContext = Boolean(id) || highlights.size > 0;
    transform.quaternion.identity();
    for (const batch of batches) {
      batch.members.forEach((node, index) => {
        const selected = node.id === id;
        const related = neighbors.has(node.id) || highlights.has(node.id);
        const scale = selected ? 1.14 : related ? 1.05 : hasContext ? 0.9 : 1;
        transform.position.set(node.x, node.y, node.z);
        transform.scale.setScalar(scale);
        transform.updateMatrix();
        batch.body.setMatrixAt(index, transform.matrix);
        batch.ring.setMatrixAt(index, transform.matrix);
        batch.bodyOpacity.setX(index, selected ? 1 : related ? 0.98 : hasContext ? 0.28 : 0.86);
        batch.ringOpacity.setX(index, selected ? 0.76 : related ? 0.4 : hasContext ? 0.035 : 0.08);
        const hit = hits.get(node.id)!;
        hit.scale.setScalar(getNodeScale(node.source) * scale);
        hit.updateMatrixWorld();
      });
      batch.body.instanceMatrix.needsUpdate = batch.ring.instanceMatrix.needsUpdate = true;
      batch.bodyOpacity.needsUpdate = batch.ringOpacity.needsUpdate = true;
    }
    let arrowCount = 0;
    for (const { edge, start, count, arrowMatrix } of ranges) {
      const connected = Boolean(id && (edge.source === id || edge.target === id));
      const highlighted = highlights.has(edge.source) || highlights.has(edge.target);
      const opacity = connected ? 0.56 : highlighted ? 0.36 : hasContext ? 0.035 : 0.15;
      (lineOpacity.array as Float32Array).fill(opacity, start, start + count);
      if (connected) arrows.setMatrixAt(arrowCount++, arrowMatrix);
    }
    lineOpacity.needsUpdate = true;
    arrows.count = arrowCount;
    arrows.instanceMatrix.needsUpdate = true;
  }

  function refreshTheme(next: GraphTheme) {
    for (const batch of batches) {
      const color = next.clusterColors.get(batch.clusterKey) ?? next.selectedColor;
      batch.bodyMaterial.color.setHex(color);
      batch.bodyMaterial.emissive.setHex(color);
      batch.bodyMaterial.emissiveIntensity = next.lightSurface ? 0.02 : 0.09;
      batch.ringMaterial.color.setHex(color);
    }
    lineMaterial.color.setHex(next.edgeColor);
    arrowMaterial.color.setHex(next.selectedColor);
  }

  return {
    hits, updateSelection, refreshTheme,
    dispose() {
      for (const batch of batches) { batch.body.dispose(); batch.ring.dispose(); }
      arrows.dispose();
      hits.clear();
    },
  };
}
