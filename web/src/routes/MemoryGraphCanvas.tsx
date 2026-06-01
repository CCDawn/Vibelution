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

const NODE_SHORT_LABELS: Record<string, string> = {
  project: "P",
  team: "T",
  agent: "A",
  agent_private_memory: "M",
  knowledge_base: "KB",
  knowledge_item: "KI",
  source_artifact: "S",
  refinement_proposal: "R",
  knowledge_batch: "B",
  rating_suggestion: "!",
  runtime_scene: "RT",
  evolution: "E",
  supervision: "SV",
  tag: "#",
};

export function MemoryGraphCanvas({ nodes, edges, selectedNodeId, onSelectNode, fallbackText }: MemoryGraphCanvasProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const labelLayerRef = useRef<HTMLDivElement | null>(null);
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
    scene.add(new THREE.AmbientLight(0xffffff, 0.82));
    const light = new THREE.DirectionalLight(0xffffff, 1.2);
    light.position.set(12, 18, 16);
    scene.add(light);

    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setClearColor(0x000000, 0);
    renderer.domElement.style.width = "100%";
    renderer.domElement.style.height = "100%";
    container.replaceChildren(renderer.domElement);

    const nodeObjects = new Map<string, THREE.Mesh>();
    const hitObjects = new Map<string, THREE.Mesh>();
    const sphere = new THREE.SphereGeometry(0.42, 24, 24);
    const haloSphere = new THREE.SphereGeometry(0.58, 24, 24);
    const hitSphere = new THREE.SphereGeometry(1, 12, 12);
    const ringGeometry = new THREE.TorusGeometry(0.7, 0.025, 8, 36);
    const labelLayer = labelLayerRef.current;
    if (labelLayer) {
      labelLayer.replaceChildren();
    }
    const labelElements = new Map<string, HTMLButtonElement>();
    for (const node of nodes) {
      const degree = edges.filter((edge) => edge.source === node.id || edge.target === node.id).length;
      const color = NODE_COLORS[node.type] ?? 0xdfe6e9;
      const material = new THREE.MeshStandardMaterial({
        color,
        emissive: color,
        emissiveIntensity: selectedNodeId === node.id ? 0.58 : 0.2,
        roughness: 0.32,
        metalness: 0.18,
      });
      const mesh = new THREE.Mesh(sphere, material);
      const size = 1.15 + Math.min(2.5, Math.sqrt(degree + 1) * 0.3);
      mesh.scale.setScalar(node.type === "project" ? 2.55 : size);
      const position = positions.get(node.id) ?? new THREE.Vector3();
      mesh.position.copy(position);
      mesh.userData.nodeId = node.id;
      root.add(mesh);
      nodeObjects.set(node.id, mesh);

      const halo = new THREE.Mesh(
        haloSphere,
        new THREE.MeshBasicMaterial({
          color,
          transparent: true,
          opacity: selectedNodeId === node.id ? 0.28 : 0.1,
          depthWrite: false,
        }),
      );
      halo.position.copy(position);
      halo.scale.setScalar((node.type === "project" ? 2.7 : size) * 1.2);
      root.add(halo);

      if (selectedNodeId === node.id || node.type === "project" || node.type === "team" || node.type === "knowledge_base") {
        const ring = new THREE.Mesh(
          ringGeometry,
          new THREE.MeshBasicMaterial({
            color,
            transparent: true,
            opacity: selectedNodeId === node.id ? 0.9 : 0.48,
            depthWrite: false,
          }),
        );
        ring.position.copy(position);
        ring.scale.setScalar(node.type === "project" ? 2.4 : Math.max(1.1, size));
        ring.lookAt(camera.position);
        root.add(ring);
      }

      const hitMesh = new THREE.Mesh(
        hitSphere,
        new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false }),
      );
      hitMesh.position.copy(position);
      hitMesh.scale.setScalar(Math.max(1.25, (node.type === "project" ? 2.75 : size) * 1.35));
      hitMesh.userData.nodeId = node.id;
      root.add(hitMesh);
      hitObjects.set(node.id, hitMesh);

      if (labelLayer) {
        const label = document.createElement("button");
        label.type = "button";
        label.className = styles.graphNodeBadge;
        label.dataset.selected = selectedNodeId === node.id ? "true" : "false";
        label.dataset.nodeType = node.type;
        label.textContent = NODE_SHORT_LABELS[node.type] ?? node.type.slice(0, 2).toUpperCase();
        label.title = `${node.label} · ${node.type}`;
        label.setAttribute("aria-label", `${node.label} ${node.type}`);
        label.tabIndex = -1;
        label.addEventListener("click", (event) => {
          event.stopPropagation();
          onSelectNode(node.id);
        });
        labelLayer.appendChild(label);
        labelElements.set(node.id, label);
      }
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
      new THREE.LineBasicMaterial({ color: 0x7897ad, transparent: true, opacity: 0.42 }),
    );
    root.add(lines);

    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    let width = 1;
    let height = 1;
    let dragging = false;
    let moved = false;
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
      moved = false;
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
      if (Math.abs(dx) + Math.abs(dy) > 3) {
        moved = true;
      }
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
      if (moved) {
        return;
      }
      const rect = renderer.domElement.getBoundingClientRect();
      pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
      raycaster.setFromCamera(pointer, camera);
      const hit = raycaster.intersectObjects(Array.from(hitObjects.values()), false)[0];
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
        root.rotation.y += 0.0012;
      }
      for (const object of root.children) {
        if (object instanceof THREE.Mesh && object.geometry === ringGeometry) {
          object.lookAt(camera.position);
        }
      }
      if (labelLayer) {
        const rect = container.getBoundingClientRect();
        const projected = new THREE.Vector3();
        root.updateMatrixWorld(true);
        camera.updateMatrixWorld(true);
        for (const [nodeId, label] of labelElements) {
          const position = positions.get(nodeId);
          if (!position) {
            label.style.opacity = "0";
            continue;
          }
          projected.copy(position).applyMatrix4(root.matrixWorld).project(camera);
          const x = (projected.x * 0.5 + 0.5) * rect.width;
          const y = (-projected.y * 0.5 + 0.5) * rect.height;
          label.style.transform = `translate3d(${x}px, ${y}px, 0) translate(-50%, -50%)`;
          label.style.opacity = projected.z < 1 ? "1" : "0";
          label.style.zIndex = String(Math.max(1, Math.round((1 - projected.z) * 100)));
        }
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
      haloSphere.dispose();
      hitSphere.dispose();
      ringGeometry.dispose();
      lineGeometry.dispose();
      for (const object of nodeObjects.values()) {
        (object.material as THREE.Material).dispose();
      }
      for (const object of hitObjects.values()) {
        (object.material as THREE.Material).dispose();
      }
      if (labelLayer) {
        labelLayer.replaceChildren();
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
  return (
    <div className={styles.graphCanvasShell}>
      <div ref={containerRef} className={styles.graphCanvasMount} aria-label="memory knowledge graph 3d canvas" />
      <div ref={labelLayerRef} className={styles.graphCanvasLabels} />
    </div>
  );
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
