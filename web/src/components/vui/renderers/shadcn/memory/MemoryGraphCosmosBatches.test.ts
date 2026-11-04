import { describe, expect, it } from "vitest";
import * as THREE from "three";
import type { MemoryKnowledgeGraphNode } from "../../../../../api/types";
import type { PositionedMemoryKnowledgeGraphNode } from "../../../product/memory/memoryGraphModel";
import { createMemoryGraphCosmosBatches } from "./MemoryGraphCosmosBatches";

describe("cosmos matte node batches", () => {
  it("keeps faceted geometry, shared opacity and physical picking through selection", () => {
    const nodes: PositionedMemoryKnowledgeGraphNode[] = ["knowledge_item", "knowledge_item", "source_artifact", "topic"].map((type, index) => {
      const source: MemoryKnowledgeGraphNode = {
        id: "record-" + index, type, label: type, summary: "", status: "active", createdAt: "", updatedAt: "",
        metadata: {}, visual: {}, responsibilityQuestion: "", childNodeIds: [], contentItems: [],
      };
      return { id: source.id, source, clusterKey: "knowledge", clusterLabel: "知识", x: index * 2, y: index, z: -index };
    });
    const scene = new THREE.Scene();
    const geometries: THREE.BufferGeometry[] = [];
    const materials: THREE.Material[] = [];
    const batches = createMemoryGraphCosmosBatches({
      THREE, scene, nodes, edgePaths: [], compact: false, pixelRatio: 1,
      theme: { clusterColors: new Map([["knowledge", 0x94aeca]]), edgeColor: 0x888888, selectedColor: 0x0a84ff, lightSurface: false },
      createNodeGeometry: () => new THREE.BufferGeometry(), getNodeScale: () => 1,
      disposeGeometry: geometry => { geometries.push(geometry); return geometry; },
      disposeMaterial: material => { materials.push(material); return material; },
    });
    try {
      const bodies = scene.children.filter(object => object.userData.memoryGraphBatch === "nodes") as THREE.InstancedMesh[];
      expect(bodies).toHaveLength(3);
      expect(batches.hits.size).toBe(nodes.length);
      for (const body of bodies) {
        const material = body.material as THREE.MeshStandardMaterial;
        expect(material.flatShading).toBe(true);
        expect(material.roughness).toBe(1);
        expect(material.metalness).toBe(0);
        expect(material.depthWrite).toBe(true);
        expect(geometries).toContain(body.geometry);
        expect(materials).toContain(material);
        const source = body.geometry.userData.cosmosKind === "source_artifact";
        if (source) {
          expect((body.geometry as THREE.BoxGeometry).parameters.width).toBe(0.12);
        } else {
          expect((body.geometry as THREE.IcosahedronGeometry).parameters.detail).toBe(0);
          expect(body.geometry.getAttribute("position").count).toBe(60);
        }
        const shader = {
          uniforms: {},
          vertexShader: "#include <common>\n#include <begin_vertex>",
          fragmentShader: "#include <common>\n#include <color_fragment>\n#include <opaque_fragment>",
        } as Parameters<THREE.MeshStandardMaterial["onBeforeCompile"]>[0];
        material.onBeforeCompile(shader, {} as THREE.WebGLRenderer);
        expect(shader.vertexShader).toContain("vGraphOpacity = graphOpacity");
        expect(shader.fragmentShader).toContain("diffuseColor.a *= vGraphOpacity");
        expect(shader.fragmentShader).toContain("outgoingLight = cosmosTint");
        expect(shader.fragmentShader).toContain("viewMatrix * vec4(-0.55, 0.8, 0.6, 0.0)");
        expect((shader.uniforms.cosmosTint.value as THREE.Color).getHex()).toBe(source ? 0x879bb7 : 0x56c5d8);
      }
      batches.updateSelection(nodes[0].id, new Set([nodes[2].id]), new Set());
      const knowledgeBody = bodies.find(body => body.geometry.userData.cosmosKind === "knowledge_item")!;
      expect(knowledgeBody.geometry.getAttribute("graphOpacity").getX(0)).toBe(1);
      expect(knowledgeBody.geometry.getAttribute("graphOpacity").getX(1)).toBeCloseTo(0.17);
      const matrix = new THREE.Matrix4();
      knowledgeBody.getMatrixAt(1, matrix);
      expect(new THREE.Vector3().setFromMatrixPosition(matrix).toArray()).toEqual([2, 1, -1]);
      const target = batches.hits.get(nodes[0].id)!;
      const ray = new THREE.Raycaster(target.position.clone().add(new THREE.Vector3(0, 0, 3)), new THREE.Vector3(0, 0, -1));
      expect(ray.intersectObject(target, false)[0].object.userData.nodeId).toBe(nodes[0].id);
      expect(target.parent).toBeNull();
      batches.updateSelection("", new Set(), new Set());
      expect(knowledgeBody.geometry.getAttribute("graphOpacity").getX(1)).toBe(1);
    } finally {
      batches.dispose();
      geometries.forEach(geometry => geometry.dispose());
      materials.forEach(material => material.dispose());
    }
  });
});
