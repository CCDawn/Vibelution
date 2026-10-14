import { expect, it } from "vitest";
import * as THREE from "three";
import type { MemoryKnowledgeGraphNode } from "../../../../../api/types";
import { layoutMemoryKnowledgeGraph } from "../../../product/memory/memoryGraphModel";
import { createMemoryGraphBatches } from "./MemoryGraphBatches";

it("preserves spatial picking, opacity and directed relations in a batched graph", () => {
  const nodes: MemoryKnowledgeGraphNode[] = Array.from({ length: 246 }, (_, i) => ({
    id: `n${i}`, type: "knowledge_item", label: `知识 ${i}`, summary: "", status: "active",
    createdAt: "", updatedAt: "", metadata: {}, responsibilityQuestion: "", visual: {}, childNodeIds: [], contentItems: [],
  }));
  const edges = nodes.slice(1).map((node, i) => ({ id: `e${i}`, source: "n0", target: node.id, type: "references", label: "引用", weight: 1, metadata: {} }));
  edges.push(
    { id: "highlighted", source: "n1", target: "n2", type: "references", label: "搜索关联", weight: 1, metadata: {} },
    { id: "unrelated", source: "n3", target: "n4", type: "references", label: "无关关系", weight: 1, metadata: {} },
  );
  const positioned = layoutMemoryKnowledgeGraph(nodes, edges).nodes;
  const positions = new Map(positioned.map(node => [node.id, new THREE.Vector3(node.x, node.y, node.z)]));
  const scene = new THREE.Scene();
  const geometries: THREE.BufferGeometry[] = [], materials: THREE.Material[] = [];
  const theme = { clusterColors: new Map([["knowledge" as const, 0x94aeca]]), edgeColor: 0x888888, selectedColor: 0x0a84ff, lightSurface: false };
  const batch = createMemoryGraphBatches({ THREE, scene, nodes: positioned,
    edgePaths: edges.map(edge => ({ edge, curve: new THREE.QuadraticBezierCurve3(positions.get(edge.source)!, new THREE.Vector3(), positions.get(edge.target)!) })),
    theme, createNodeGeometry: () => new THREE.SphereGeometry(0.205, 8, 8), getNodeScale: () => 1,
    disposeGeometry: geometry => { geometries.push(geometry); return geometry; },
    disposeMaterial: material => { materials.push(material); return material; },
  });
  try {
    const body = scene.children.find(o => o.userData.memoryGraphBatch === "nodes") as THREE.InstancedMesh;
    const lines = scene.children.find(o => o.userData.memoryGraphBatch === "edges") as THREE.LineSegments;
    const arrows = scene.children.find(o => o.userData.memoryGraphBatch === "arrows") as THREE.InstancedMesh;
    const opacity = lines.geometry.getAttribute("graphOpacity");
    const verticesPerEdge = opacity.count / edges.length;
    const highlightedOffset = verticesPerEdge * (edges.length - 2);
    const unrelatedOffset = verticesPerEdge * (edges.length - 1);
    expect(scene.children).toHaveLength(4);
    expect(body.count).toBe(246);
    expect(batch.hits.size).toBe(246);
    expect([...batch.hits.values()].every(hit => hit.parent === null)).toBe(true);
    batch.updateSelection("n0", new Set(["n1"]), new Set(["n2"]));
    expect(arrows.count).toBe(245);
    expect(lines.geometry.getAttribute("graphOpacity").getX(0)).toBeCloseTo(0.88);
    expect(opacity.getX(highlightedOffset)).toBeCloseTo(0.7);
    expect(opacity.getX(unrelatedOffset)).toBeCloseTo(0.08);
    batch.refreshTheme({ ...theme, lightSurface: true });
    expect(arrows.count).toBe(245);
    expect(opacity.getX(0)).toBeCloseTo(0.88);
    expect(opacity.getX(highlightedOffset)).toBeCloseTo(0.7);
    expect(opacity.getX(unrelatedOffset)).toBeCloseTo(0.08);
    batch.refreshTheme(theme);
    for (const [i, node] of positioned.entries()) {
      const matrix = new THREE.Matrix4();
      body.getMatrixAt(i, matrix);
      expect(new THREE.Vector3().setFromMatrixPosition(matrix).toArray()).toEqual(positions.get(node.id)!.toArray().map(Math.fround));
      expect(body.geometry.getAttribute("graphOpacity").getX(i)).toBeCloseTo(node.id === "n0" ? 1 : ["n1", "n2"].includes(node.id) ? 0.98 : 0.28);
    }
    const target = batch.hits.get("n0")!;
    const ray = new THREE.Raycaster(target.position.clone().add(new THREE.Vector3(0, 0, 3)), new THREE.Vector3(0, 0, -1));
    expect(ray.intersectObject(target, false)[0].object.userData.nodeId).toBe("n0");
    batch.updateSelection("", new Set(), new Set());
    expect(arrows.count).toBe(0);
    expect(lines.geometry.getAttribute("graphOpacity").getX(0)).toBeCloseTo(0.42);
    batch.refreshTheme({ ...theme, lightSurface: true, edgeColor: 0x112233 });
    expect((lines.material as THREE.LineBasicMaterial).color.getHex()).toBe(0x112233);
    expect((body.material as THREE.MeshStandardMaterial).emissiveIntensity).toBe(0.02);
    expect(lines.geometry.getAttribute("graphOpacity").getX(0)).toBeCloseTo(0.58);
    batch.refreshTheme(theme);
    expect(opacity.getX(0)).toBeCloseTo(0.42);
    expect(opacity.getX(unrelatedOffset)).toBeCloseTo(0.42);
    expect(arrows.count).toBe(0);
  } finally {
    batch.dispose();
    geometries.forEach(g => g.dispose()); materials.forEach(m => m.dispose());
  }
});
