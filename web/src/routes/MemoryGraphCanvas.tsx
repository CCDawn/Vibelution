import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";

import type { MemoryKnowledgeGraphEdge, MemoryKnowledgeGraphNode } from "../api/types";
import styles from "./MemoryRoute.module.css";

type GraphPosition = {
  id: string;
  x: number;
  y: number;
  z: number;
};

type MemoryGraphCanvasProps = {
  nodes: MemoryKnowledgeGraphNode[];
  edges: MemoryKnowledgeGraphEdge[];
  selectedNodeId: string;
  onSelectNode: (nodeId: string) => void;
  fallbackText: string;
};

const NODE_COLORS: Record<string, number> = {
  project: 0xf2c94c,
  team: 0x6fcf97,
  agent: 0x56ccf2,
  agent_private_memory: 0x2d9cdb,
  knowledge_base: 0xbb6bd9,
  knowledge_item: 0xf2994a,
  source_artifact: 0xeb5757,
  refinement_proposal: 0x9b51e0,
  knowledge_batch: 0x27ae60,
  rating_suggestion: 0xf2c94c,
  runtime_scene: 0x828282,
  evolution: 0x00b894,
  supervision: 0xfd79a8,
  tag: 0xb2bec3,
};

export function MemoryGraphCanvas({ nodes, edges, selectedNodeId, onSelectNode, fallbackText }: MemoryGraphCanvasProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [webglReady, setWebglReady] = useState(true);
  const [positions, setPositions] = useState<Map<string, THREE.Vector3>>(new Map());
  const positionsArray = useMemo(() => Array.from(positions.entries()), [positions]);

  useEffect(() => {
    if (typeof Worker === "undefined") {
      setPositions(deterministicPositions(nodes, edges));
      return;
    }
    const worker = new Worker(new URL("./memoryGraphLayout.worker.ts", import.meta.url), { type: "module" });
    worker.onmessage = (event: MessageEvent<{ type: string; positions: GraphPosition[] }>) => {
      if (event.data?.type !== "layout") {
        return;
      }
      setPositions(
        new Map(
          event.data.positions.map((item) => [
            item.id,
            new THREE.Vector3(Number(item.x) || 0, Number(item.y) || 0, Number(item.z) || 0),
          ]),
        ),
      );
    };
    worker.postMessage({ type: "layout", nodes, edges });
    return () => worker.terminate();
  }, [nodes, edges]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || !nodes.length) {
      return;
    }
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" });
    } catch {
      setWebglReady(false);
      return;
    }
    setWebglReady(true);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(52, 1, 0.1, 1000);
    camera.position.set(0, 12, 46);
    const root = new THREE.Group();
    scene.add(root);
    scene.add(new THREE.AmbientLight(0xffffff, 0.7));
    const light = new THREE.DirectionalLight(0xffffff, 1.2);
    light.position.set(12, 18, 16);
    scene.add(light);

    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setClearColor(0x000000, 0);
    renderer.domElement.style.width = "100%";
    renderer.domElement.style.height = "100%";
    container.replaceChildren(renderer.domElement);

    const nodeObjects = new Map<string, THREE.Mesh>();
    const sphere = new THREE.SphereGeometry(0.32, 16, 16);
    for (const node of nodes) {
      const degree = edges.filter((edge) => edge.source === node.id || edge.target === node.id).length;
      const material = new THREE.MeshStandardMaterial({
        color: NODE_COLORS[node.type] ?? 0xdfe6e9,
        emissive: selectedNodeId === node.id ? 0xffffff : 0x000000,
        emissiveIntensity: selectedNodeId === node.id ? 0.28 : 0,
        roughness: 0.45,
        metalness: 0.08,
      });
      const mesh = new THREE.Mesh(sphere, material);
      const size = 0.9 + Math.min(2.2, Math.sqrt(degree + 1) * 0.22);
      mesh.scale.setScalar(node.type === "project" ? 2.1 : size);
      const position = positions.get(node.id) ?? new THREE.Vector3();
      mesh.position.copy(position);
      mesh.userData.nodeId = node.id;
      root.add(mesh);
      nodeObjects.set(node.id, mesh);
    }

    const linePositions: number[] = [];
    for (const edge of edges) {
      const source = positions.get(edge.source);
      const target = positions.get(edge.target);
      if (!source || !target) {
        continue;
      }
      linePositions.push(source.x, source.y, source.z, target.x, target.y, target.z);
    }
    const lineGeometry = new THREE.BufferGeometry();
    lineGeometry.setAttribute("position", new THREE.Float32BufferAttribute(linePositions, 3));
    const lines = new THREE.LineSegments(
      lineGeometry,
      new THREE.LineBasicMaterial({ color: 0x8aa0b5, transparent: true, opacity: 0.36 }),
    );
    root.add(lines);

    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    let width = 1;
    let height = 1;
    let dragging = false;
    let lastX = 0;
    let lastY = 0;
    let raf = 0;
    const resize = () => {
      const rect = container.getBoundingClientRect();
      width = Math.max(1, rect.width);
      height = Math.max(1, rect.height);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      renderer.setSize(width, height, false);
    };
    const onPointerDown = (event: PointerEvent) => {
      dragging = true;
      lastX = event.clientX;
      lastY = event.clientY;
      renderer.domElement.setPointerCapture(event.pointerId);
    };
    const onPointerMove = (event: PointerEvent) => {
      if (!dragging) {
        return;
      }
      const dx = event.clientX - lastX;
      const dy = event.clientY - lastY;
      lastX = event.clientX;
      lastY = event.clientY;
      root.rotation.y += dx * 0.006;
      root.rotation.x += dy * 0.004;
      root.rotation.x = Math.max(-1.2, Math.min(1.2, root.rotation.x));
    };
    const onPointerUp = (event: PointerEvent) => {
      dragging = false;
      renderer.domElement.releasePointerCapture(event.pointerId);
    };
    const onClick = (event: MouseEvent) => {
      const rect = renderer.domElement.getBoundingClientRect();
      pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
      raycaster.setFromCamera(pointer, camera);
      const hit = raycaster.intersectObjects(Array.from(nodeObjects.values()), false)[0];
      const nodeId = String(hit?.object?.userData?.nodeId ?? "");
      if (nodeId) {
        onSelectNode(nodeId);
      }
    };
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      camera.position.z = Math.max(16, Math.min(90, camera.position.z + event.deltaY * 0.025));
    };
    const animate = () => {
      if (!dragging) {
        root.rotation.y += 0.0018;
      }
      renderer.render(scene, camera);
      raf = requestAnimationFrame(animate);
    };
    resize();
    const resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(container);
    renderer.domElement.addEventListener("pointerdown", onPointerDown);
    renderer.domElement.addEventListener("pointermove", onPointerMove);
    renderer.domElement.addEventListener("pointerup", onPointerUp);
    renderer.domElement.addEventListener("click", onClick);
    renderer.domElement.addEventListener("wheel", onWheel, { passive: false });
    animate();
    return () => {
      cancelAnimationFrame(raf);
      resizeObserver.disconnect();
      renderer.domElement.removeEventListener("pointerdown", onPointerDown);
      renderer.domElement.removeEventListener("pointermove", onPointerMove);
      renderer.domElement.removeEventListener("pointerup", onPointerUp);
      renderer.domElement.removeEventListener("click", onClick);
      renderer.domElement.removeEventListener("wheel", onWheel);
      sphere.dispose();
      lineGeometry.dispose();
      for (const object of nodeObjects.values()) {
        (object.material as THREE.Material).dispose();
      }
      renderer.dispose();
      container.replaceChildren();
    };
  }, [nodes, edges, positions, positionsArray, selectedNodeId, onSelectNode]);

  if (!webglReady || !nodes.length) {
    return (
      <div className={styles.graphCanvasFallback}>
        <strong>{fallbackText}</strong>
      </div>
    );
  }
  return <div ref={containerRef} className={styles.graphCanvasMount} aria-label="memory knowledge graph 3d canvas" />;
}

function deterministicPositions(nodes: MemoryKnowledgeGraphNode[], edges: MemoryKnowledgeGraphEdge[]) {
  const degree = new Map<string, number>();
  for (const edge of edges) {
    degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1);
    degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1);
  }
  return new Map(
    nodes.map((node, index) => {
      const angle = (index / Math.max(1, nodes.length)) * Math.PI * 2;
      const radius = 7 + Math.sqrt(degree.get(node.id) ?? 1) * 2.2 + (index % 7);
      return [node.id, new THREE.Vector3(Math.cos(angle) * radius, ((index % 9) - 4) * 1.3, Math.sin(angle) * radius)];
    }),
  );
}
