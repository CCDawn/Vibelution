// @vitest-environment happy-dom
import { expect, it, vi } from "vitest";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import type { MemoryKnowledgeGraphNode } from "../../../../../api/types";
import { layoutMemoryKnowledgeGraph } from "../../../product/memory/memoryGraphModel";
import { createMemoryGraphEngine } from "./MemoryGraphEngine";

it.each([150, 165, 180, 195, 210])("fits a rotated and panned overview at yaw %s while preserving the current viewing direction", yawDegrees => {
  class RendererStub {
    domElement = document.createElement("canvas");
    pixelRatio = 1;
    setPixelRatio(value: number) { this.pixelRatio = value; }
    getPixelRatio() { return this.pixelRatio; }
    setClearColor() {}
    setSize() {}
    dispose() {}
  }
  let controls: OrbitControls | undefined;
  class CapturedControls extends OrbitControls {
    constructor(camera: THREE.Camera, element?: HTMLElement | null) {
      super(camera, element);
      controls = this;
    }
  }
  vi.spyOn(window, "requestAnimationFrame").mockReturnValue(1);
  vi.spyOn(window, "matchMedia").mockReturnValue({
    matches: true, addEventListener() {}, removeEventListener() {},
  } as unknown as MediaQueryList);
  const sourceNodes: MemoryKnowledgeGraphNode[] = Array.from({ length: 30 }, (_, index) => ({
    id: "knowledge-" + index, type: "knowledge_item", label: "知识 " + index, summary: "", status: "active",
    createdAt: "", updatedAt: "", metadata: { topicId: "topic-" + Math.floor(index / 10), topicLabel: "主题 " + Math.floor(index / 10) },
    visual: {}, responsibilityQuestion: "", childNodeIds: [], contentItems: [],
  }));
  const layout = layoutMemoryKnowledgeGraph(sourceNodes, [], { groupByTopic: true });
  const root = document.createElement("div");
  const host = document.createElement("div");
  const labelLayer = document.createElement("div");
  root.append(host, labelLayer);
  document.body.append(root);
  Object.defineProperties(host, { clientWidth: { value: 900 }, clientHeight: { value: 600 } });
  const onFailure = vi.fn();
  const engine = createMemoryGraphEngine({
    THREE: { ...THREE, WebGLRenderer: RendererStub as unknown as typeof THREE.WebGLRenderer },
    OrbitControls: CapturedControls, host, labelLayer, ...layout, edges: [], selectedNodeId: "",
    flat: false, highlightIds: [], showLabels: true, onSelectNode() {}, onSelectEdge() {},
    canSelectEdge: () => false, onFailure, appearance: "cosmos",
  });
  try {
    expect(onFailure).not.toHaveBeenCalled();
    expect(engine).not.toBeNull();
    const orbit = controls!;
    const camera = orbit.object as THREE.PerspectiveCamera;
    const initialTarget = orbit.target.clone();
    const initialDistance = camera.position.distanceTo(initialTarget);
    const yaw = THREE.MathUtils.degToRad(yawDegrees);
    const direction = new THREE.Vector3(Math.sin(yaw), 0.15, Math.cos(yaw)).normalize();
    const staleOverview = camera.clone();
    staleOverview.position.copy(initialTarget).addScaledVector(direction, initialDistance);
    staleOverview.lookAt(initialTarget);
    staleOverview.updateMatrixWorld();
    const staleExtent = Math.max(...layout.nodes.map(node => {
      const point = new THREE.Vector3(node.x, node.y, node.z).project(staleOverview);
      return Math.max(Math.abs(point.x), Math.abs(point.y));
    }));
    expect(staleExtent).toBeGreaterThan(1);
    orbit.target.add(new THREE.Vector3(3, 2, -4));
    camera.position.copy(orbit.target).addScaledVector(direction, initialDistance * 0.5);
    orbit.update();
    engine!.focus("");
    expect(onFailure).not.toHaveBeenCalled();
    expect(orbit.target.distanceTo(initialTarget)).toBeLessThan(0.000001);
    expect(camera.position.clone().sub(orbit.target).normalize().distanceTo(direction)).toBeLessThan(0.000001);
    for (const node of layout.nodes) {
      const projected = new THREE.Vector3(node.x, node.y, node.z).project(camera);
      expect(Math.abs(projected.x)).toBeLessThan(1);
      expect(Math.abs(projected.y)).toBeLessThan(1);
      expect(projected.z).toBeGreaterThan(-1);
      expect(projected.z).toBeLessThan(1);
    }
  } finally {
    engine?.dispose();
    root.remove();
    vi.restoreAllMocks();
  }
});
