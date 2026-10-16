import { LineSegments2 } from "three/addons/lines/LineSegments2.js";
import { LineSegmentsGeometry } from "three/addons/lines/LineSegmentsGeometry.js";
import { LineMaterial } from "three/addons/lines/LineMaterial.js";
import type { createMemoryGraphBatches } from "./MemoryGraphBatches";

type Options = Parameters<typeof createMemoryGraphBatches>[0];

/** One real XYZ segment per relation, with stable screen-pixel widths. */
export function createMemoryGraphSpatialEdges(options: Options) {
  const { THREE, scene, edgePaths, nodes, disposeGeometry, disposeMaterial } = options;
  const byId = new Map(nodes.map(node => [node.id, node]));
  const definitions = [
    { kind: "evidence", width: 0.65, opacity: 0.32, color: 0x7c8da7 },
    { kind: "knowledge", width: 0.9, opacity: 0.58, color: 0xa6b8d3 },
    { kind: "cross", width: 0.9, opacity: 0.48, color: 0x9bafcf },
  ] as const;
  const paths = edgePaths.flatMap(path => {
    const source = byId.get(path.edge.source);
    const target = byId.get(path.edge.target);
    if (!source || !target || ![source.x, source.y, source.z, target.x, target.y, target.z].every(Number.isFinite)) return [];
    // The positioned nodes are authoritative, including depth. The label path
    // is straightened too, so its midpoint lies on the visible relation.
    path.curve.v0.set(source.x, source.y, source.z);
    path.curve.v2.set(target.x, target.y, target.z);
    path.curve.v1.copy(path.curve.v0).lerp(path.curve.v2, 0.5);
    const metadata = path.edge.metadata;
    const kind = metadata?.layer === "evidence" ? "evidence"
      : metadata?.crossTopic === true || source.clusterKey !== target.clusterKey ? "cross" : "knowledge";
    return [{ path, kind, candidate: metadata?.status === "candidate" }];
  });
  const draws = definitions.flatMap(definition => [false, true].flatMap(candidate => {
    const members = paths.filter(path => path.kind === definition.kind && path.candidate === candidate);
    if (!members.length) return [];
    const positions: number[] = [], colors: number[] = [];
    const tint = new THREE.Color(definition.color).toArray();
    const ranges = members.map(({ path }, index) => {
      positions.push(...path.curve.v0.toArray(), ...path.curve.v2.toArray());
      colors.push(...tint, ...tint);
      return { edge: path.edge, index };
    });
    const geometry = disposeGeometry(new LineSegmentsGeometry());
    geometry.setPositions(positions);
    geometry.setColors(colors);
    const material = disposeMaterial(new LineMaterial({
      color: 0xffffff, vertexColors: true, linewidth: definition.width,
      worldUnits: false, dashed: candidate, dashSize: 0.28, gapSize: 0.2,
      transparent: true, opacity: definition.opacity, depthWrite: false, toneMapped: false,
    }));
    const line = new LineSegments2(geometry, material);
    if (candidate) line.computeLineDistances();
    line.name = `memory-graph-relations-${definition.kind}${candidate ? "-candidate" : ""}`;
    line.userData.memoryGraphBatch = "edges";
    line.frustumCulled = false;
    line.renderOrder = -1;
    scene.add(line);
    return [{ ...definition, line, geometry, material, ranges, baseColors: colors }];
  }));
  return {
    updateSelection(id: string, related: ReadonlySet<string>, highlights: ReadonlySet<string>) {
      const context = Boolean(id) || highlights.size > 0;
      const topic = byId.get(id)?.source.type === "topic";
      for (const draw of draws) {
        draw.material.opacity = context ? 0.94 : draw.opacity;
        const startColor = draw.geometry.getAttribute("instanceColorStart");
        const endColor = draw.geometry.getAttribute("instanceColorEnd");
        for (const { edge, index } of draw.ranges) {
          const connected = Boolean(id && (edge.source === id || edge.target === id));
          const highlighted = highlights.has(edge.source) || highlights.has(edge.target);
          const inTopic = topic && related.has(edge.source) && related.has(edge.target);
          const factor = connected || highlighted ? 1.3 : inTopic ? 0.85 : context ? 0.075 : 1;
          const base = index * 6;
          startColor.setXYZ(index, draw.baseColors[base] * factor, draw.baseColors[base + 1] * factor, draw.baseColors[base + 2] * factor);
          endColor.setXYZ(index, draw.baseColors[base + 3] * factor, draw.baseColors[base + 4] * factor, draw.baseColors[base + 5] * factor);
        }
        startColor.needsUpdate = endColor.needsUpdate = true;
      }
    },
    dispose() {
      // GPU resources belong to the engine's supplied resource registry.
      for (const draw of draws) draw.line.removeFromParent();
    },
  };
}
