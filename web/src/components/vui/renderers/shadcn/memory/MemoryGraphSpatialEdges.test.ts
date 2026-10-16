import { describe, expect, it, vi } from "vitest";
import * as THREE from "three";
import type { LineSegments2 } from "three/addons/lines/LineSegments2.js";
import type { MemoryKnowledgeGraphEdge, MemoryKnowledgeGraphNode } from "../../../../../api/types";
import type { PositionedMemoryKnowledgeGraphNode } from "../../../product/memory/memoryGraphModel";
import type { MemoryGraphEdgePath } from "./memoryGraphLabels";
import { createMemoryGraphSpatialEdges } from "./MemoryGraphSpatialEdges";

function node(id: string, x: number, y: number, z: number, type = "knowledge_item"): PositionedMemoryKnowledgeGraphNode {
  const source: MemoryKnowledgeGraphNode = {
    id, type, label: id, summary: "", status: "active", createdAt: "", updatedAt: "", metadata: {},
    responsibilityQuestion: "", visual: {}, childNodeIds: [], contentItems: [],
  };
  return { id, source, clusterKey: "knowledge", clusterLabel: "知识", x, y, z };
}
function path(id: string, source: string, target: string, metadata: MemoryKnowledgeGraphEdge["metadata"] = {}): MemoryGraphEdgePath {
  return {
    edge: { id, source, target, type: "references", label: id, weight: 1, metadata },
    curve: new THREE.QuadraticBezierCurve3(new THREE.Vector3(90, 90, 0), new THREE.Vector3(30, 90, 0), new THREE.Vector3(80, 80, 0)),
  };
}
function setup(nodes: PositionedMemoryKnowledgeGraphNode[], edgePaths: MemoryGraphEdgePath[]) {
  const scene = new THREE.Scene();
  const geometries: THREE.BufferGeometry[] = [], materials: THREE.Material[] = [];
  const edges = createMemoryGraphSpatialEdges({
    THREE, scene, nodes, edgePaths,
    theme: { clusterColors: new Map(), edgeColor: 0x888888, selectedColor: 0x0a84ff, lightSurface: false },
    createNodeGeometry: () => new THREE.BufferGeometry(), getNodeScale: () => 1,
    disposeGeometry: geometry => { geometries.push(geometry); return geometry; },
    disposeMaterial: material => { materials.push(material); return material; },
  });
  return { scene, edges, geometries, materials, lines: scene.children as LineSegments2[], release() {
    edges.dispose(); geometries.forEach(geometry => geometry.dispose()); materials.forEach(material => material.dispose());
  } };
}
function xyz(attribute: THREE.BufferAttribute | THREE.InterleavedBufferAttribute, index = 0) {
  return [attribute.getX(index), attribute.getY(index), attribute.getZ(index)];
}

describe("memory graph spatial relations", () => {
  it("renders every metadata-free relation once using real XYZ endpoints and an exact straight label midpoint", () => {
    const relation = path("real-edge", "a", "b");
    const fixture = setup([node("a", -2, 5, 7), node("b", 10, -3, -9)], [relation]);
    try {
      expect(fixture.lines).toHaveLength(1);
      const line = fixture.lines[0];
      expect(line.name).toBe("memory-graph-relations-knowledge");
      expect(line.geometry.instanceCount).toBe(1);
      expect(xyz(line.geometry.getAttribute("instanceStart"))).toEqual([-2, 5, 7]);
      expect(xyz(line.geometry.getAttribute("instanceEnd"))).toEqual([10, -3, -9]);
      expect(relation.curve.getPoint(0.5).toArray()).toEqual([4, 1, -1]);
      expect(relation.curve.getPoint(0.25).toArray()).toEqual([1, 3, 3]);
      expect(relation.edge.id).toBe("real-edge");
      expect(line.material.worldUnits).toBe(false);
      expect(line.material.linewidth).toBe(0.9);
    } finally { fixture.release(); }
  });

  it("isolates missing and nonfinite endpoints without dropping valid legacy/evidence/cross relations", () => {
    const invalid = path("missing", "a", "absent");
    const before = invalid.curve.getPoint(0.5).clone();
    const crossNode = { ...node("c", 9, 8, 7), clusterKey: "sources" as const };
    const fixture = setup([node("a", 1, 2, 3), node("b", 4, 5, 6), crossNode, node("bad", NaN, 0, 1)], [
      invalid, path("bad", "a", "bad"), path("legacy", "a", "b", { layer: "legacy" }),
      path("evidence", "a", "c", { layer: "evidence" }), path("cross", "b", "c"),
    ]);
    try {
      expect(fixture.lines.map(line => line.name).sort()).toEqual([
        "memory-graph-relations-cross", "memory-graph-relations-evidence", "memory-graph-relations-knowledge",
      ]);
      expect(fixture.lines.reduce((count, line) => count + line.geometry.instanceCount, 0)).toBe(3);
      expect(invalid.curve.getPoint(0.5).toArray()).toEqual(before.toArray());
      fixture.lines.forEach(line => {
        for (const name of ["instanceStart", "instanceEnd"]) {
          const attribute = line.geometry.getAttribute(name);
          for (let index = 0; index < attribute.count; index++) expect(xyz(attribute, index).every(Number.isFinite)).toBe(true);
        }
      });
    } finally { fixture.release(); }
  });

  it("keeps candidate IDs and draws visible dashes while confirmed edges stay solid", () => {
    const candidate = path("candidate:original", "a", "b", { status: "candidate" });
    const fixture = setup([node("a", 0, 0, 1), node("b", 3, 4, 1)], [candidate, path("confirmed", "a", "b")]);
    try {
      const dashed = fixture.lines.find(line => line.material.dashed)!;
      const solid = fixture.lines.find(line => !line.material.dashed)!;
      expect(dashed).toBeDefined(); expect(solid).toBeDefined();
      expect(dashed.geometry.instanceCount).toBe(1);
      expect(solid.geometry.instanceCount).toBe(1);
      expect(dashed.geometry.getAttribute("instanceDistanceStart").getX(0)).toBe(0);
      expect(dashed.geometry.getAttribute("instanceDistanceEnd").getX(0)).toBe(5);
      expect(dashed.material.dashSize).toBeGreaterThan(0);
      expect(dashed.material.gapSize).toBeGreaterThan(0);
      expect(candidate.edge.id).toBe("candidate:original");
      expect(candidate.edge.metadata.status).toBe("candidate");
    } finally { fixture.release(); }
  });

  it("highlights selection, topic neighbors and search context, then restores every base color and opacity", () => {
    const fixture = setup([node("t", 0, 0, 0, "topic"), ...["a", "b", "c", "d"].map((id, index) => node(id, index + 1, 2, 3))], [
      path("connected", "t", "a"), path("neighbors", "a", "b"), path("dim", "c", "d"),
    ]);
    try {
      const line = fixture.lines[0];
      const colors = line.geometry.getAttribute("instanceColorStart");
      const base = [0, 1, 2].map(index => xyz(colors, index));
      const opacity = line.material.opacity;
      fixture.edges.updateSelection("t", new Set(["a", "b"]), new Set());
      expect(colors.getX(0)).toBeCloseTo(base[0][0] * 1.3);
      expect(colors.getX(1)).toBeCloseTo(base[1][0] * 0.85);
      expect(colors.getX(2)).toBeCloseTo(base[2][0] * 0.075);
      expect(line.material.opacity).toBe(0.94);
      fixture.edges.updateSelection("", new Set(), new Set(["c"]));
      expect(colors.getX(2)).toBeCloseTo(base[2][0] * 1.3);
      expect(colors.getX(0)).toBeCloseTo(base[0][0] * 0.075);
      fixture.edges.updateSelection("", new Set(), new Set());
      expect([0, 1, 2].map(index => xyz(colors, index))).toEqual(base);
      expect(line.material.opacity).toBe(opacity);
      const end = line.geometry.getAttribute("instanceColorEnd");
      expect([0, 1, 2].map(index => xyz(end, index))).toEqual(base);
    } finally { fixture.release(); }
  });

  it("registers all resources and only detaches its own objects on repeated dispose", () => {
    const fixture = setup([node("a", 0, 1, 2), node("b", 3, 4, 5)], [path("edge", "a", "b")]);
    const unrelated = new THREE.Group(); fixture.scene.add(unrelated);
    try {
      for (const line of fixture.lines.filter(object => object instanceof THREE.Mesh)) {
        expect(fixture.geometries).toContain(line.geometry);
        expect(fixture.materials).toContain(line.material);
      }
      const disposal = [...fixture.geometries, ...fixture.materials].map(resource => vi.spyOn(resource, "dispose"));
      fixture.edges.dispose(); fixture.edges.dispose();
      expect(fixture.scene.children).toEqual([unrelated]);
      expect(disposal.every(spy => spy.mock.calls.length === 0)).toBe(true);
    } finally { fixture.release(); }
  });
});
