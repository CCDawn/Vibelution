import { createMemoryGraphBatches as createOriginalBatches } from "./MemoryGraphBatches";
import { createMemoryGraphSpatialEdges } from "./MemoryGraphSpatialEdges";
import { createMemoryGraphCosmosBackground } from "./MemoryGraphCosmosBackground";

type Options = Parameters<typeof createOriginalBatches>[0];

// Reuse instancing, physical picking, real source edges and selection. Each
// halo belongs to a real record; no decorative/fictitious records are added.
export function createMemoryGraphCosmosBatches(options: Options & { compact: boolean; pixelRatio: number }) {
  const { THREE, scene, nodes, disposeGeometry, disposeMaterial } = options;
  const colors = new Map(options.theme.clusterColors);
  const positioned = new Map(nodes.map(node => [node.id, node]));
  const overview = nodes.some(node => node.source.type === "topic");
  const cosmos = createMemoryGraphCosmosBackground({ THREE, scene, compact: options.compact, pixelRatio: options.pixelRatio, disposeGeometry, disposeMaterial });
  // Straighten paths before shared batches build directional arrow matrices.
  const spatialEdges = createMemoryGraphSpatialEdges({ ...options, theme: {...options.theme,clusterColors:colors} });
  const batches = createOriginalBatches({ ...options,
    theme: { ...options.theme, clusterColors: colors, edgeColor: 0x7f9aa8 },
    getNodeScale: node => node.type === "topic" ? 1.1 : 1,
    createNodeGeometry: node => {
      const geometry = node.type === "source_artifact" ? new THREE.BoxGeometry(0.19, 0.19, 0.19)
        : new THREE.IcosahedronGeometry(node.type === "topic" ? 0.21 : overview ? 0.11 : 0.135, 2);
      geometry.userData.cosmosKind = node.type;
      geometry.userData.cosmosCluster = positioned.get(node.id)?.clusterKey;
      return geometry;
    },
  });
  const bodies = scene.children.filter((object): object is import("three").InstancedMesh => object instanceof THREE.InstancedMesh && object.userData.memoryGraphBatch === "nodes");
  for (const body of bodies) {
    const material = body.material as import("three").MeshStandardMaterial;
    const accent = colors.get(body.geometry.userData.cosmosCluster) ?? 0x9abfdc;
    material.color.setHex(accent).lerp(new THREE.Color(0xffffff), 0.65);
    material.emissive.setHex(accent); material.emissiveIntensity = 0.7;
    material.roughness = 0.6; material.metalness = 0.05; material.depthWrite = true;
  }
  const haloGeometry = disposeGeometry(new THREE.BufferGeometry());
  haloGeometry.setAttribute("position", new THREE.Float32BufferAttribute(nodes.flatMap(node => [node.x, node.y, node.z]), 3));
  haloGeometry.setAttribute("color", new THREE.Float32BufferAttribute(nodes.flatMap(node => new THREE.Color(colors.get(node.clusterKey) ?? 0x9abfdc).toArray()), 3));
  haloGeometry.setAttribute("pointSize", new THREE.Float32BufferAttribute(nodes.map(node => node.source.type === "topic" ? 9 : node.source.type === "source_artifact" ? 3 : 5), 1));
  const opacity = new THREE.Float32BufferAttribute(new Float32Array(nodes.length).fill(0.65), 1);
  haloGeometry.setAttribute("pointOpacity", opacity);
  const haloMaterial = disposeMaterial(new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    vertexShader: `attribute vec3 color; attribute float pointSize; attribute float pointOpacity;
      varying vec3 tint; varying float strength;
      void main() { tint = color; strength = pointOpacity; vec4 p = modelViewMatrix * vec4(position,1.0);
      gl_Position = projectionMatrix * p; gl_PointSize = clamp(pointSize * 140.0 / max(4.0,-p.z), 2.0, 38.0); }`,
    fragmentShader: `varying vec3 tint; varying float strength;
      void main() { float r = length(gl_PointCoord - vec2(0.5)) * 2.0;
      if (r > 1.0) discard; gl_FragColor = vec4(tint, exp(-r*r*5.0) * 0.36 * strength); }`,
  }));
  const halos = new THREE.Points(haloGeometry, haloMaterial);
  halos.frustumCulled = false; scene.add(halos);
  scene.fog = new THREE.Fog(0x030610, 100, 220);
  for (const object of scene.children) if (object instanceof THREE.LineSegments && object.userData.memoryGraphBatch === "edges") object.visible = false;
  let selection: [string, ReadonlySet<string>, ReadonlySet<string>] = ["", new Set(), new Set()];
  const updateSelection: typeof batches.updateSelection = (id, neighbors, highlights) => {
    selection = [id, neighbors, highlights];
    const selected = nodes.find(node => node.id === id);
    const topicSelected = selected?.source.type === "topic";
    const related = topicSelected ? new Set(nodes.filter(node => node.clusterKey === selected.clusterKey).map(node => node.id)) : neighbors;
    const hasContext = Boolean(id) || highlights.size>0;
    batches.updateSelection(id, related, highlights);
    nodes.forEach((node, i) => opacity.setX(i, !hasContext || node.id === id || related.has(node.id) || highlights.has(node.id) ? 1 : 0.12));
    opacity.needsUpdate = true;
    for (const body of bodies) {
      const members = nodes.filter(node => node.clusterKey === body.geometry.userData.cosmosCluster && node.source.type === body.geometry.userData.cosmosKind);
      const alpha = body.geometry.getAttribute("graphOpacity");
      members.forEach((node, i) => alpha.setX(i, !hasContext || node.id === id || related.has(node.id) || highlights.has(node.id) ? 1 : 0.17));
      alpha.needsUpdate = true;
    }
    for (const object of scene.children) if (object.userData.memoryGraphBatch === "rings") object.visible = false;
    spatialEdges.updateSelection(id,related,highlights);
  };
  return { ...batches, updateSelection,
    refreshTheme() { updateSelection(...selection); },
    dispose() { batches.dispose(); spatialEdges.dispose(); cosmos.dispose(); scene.remove(halos); },
  };
}
