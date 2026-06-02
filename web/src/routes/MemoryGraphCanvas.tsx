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

type DragMode = "rotate" | "pan" | "";

const LABEL_ALWAYS_TYPES = new Set(["project", "team", "knowledge_base", "evolution", "supervision"]);
const DENSE_LABEL_LIMIT = 12;
const SEARCH_LABEL_LIMIT = 28;
const STELLAR_NODE_TYPES = new Set(["project", "evolution", "supervision"]);
const SATELLITE_NODE_TYPES = new Set(["runtime_scene", "source_artifact", "tag"]);

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

function trimText(value: unknown, limit: number) {
  const text = String(value || "").trim();
  if (text.length <= limit) {
    return text;
  }
  return `${text.slice(0, Math.max(0, limit - 1)).trim()}...`;
}

function buildDegreeMap(edges: MemoryKnowledgeGraphEdge[]) {
  const degree = new Map<string, number>();
  for (const edge of edges) {
    degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1);
    degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1);
  }
  return degree;
}

function pickVisibleLabelIds(nodes: MemoryKnowledgeGraphNode[], edges: MemoryKnowledgeGraphEdge[], selectedNodeId: string) {
  const degree = buildDegreeMap(edges);
  const visible = new Set<string>();
  const isSearchSized = nodes.length <= SEARCH_LABEL_LIMIT;
  const budget = isSearchSized ? Math.min(SEARCH_LABEL_LIMIT, nodes.length) : DENSE_LABEL_LIMIT;

  for (const node of nodes) {
    if (LABEL_ALWAYS_TYPES.has(node.type)) {
      visible.add(node.id);
    }
  }
  if (selectedNodeId) {
    visible.add(selectedNodeId);
  }
  if (visible.size < budget) {
    [...nodes]
      .sort((left, right) => (degree.get(right.id) ?? 0) - (degree.get(left.id) ?? 0))
      .slice(0, Math.max(0, budget - visible.size))
      .forEach((node) => visible.add(node.id));
  }
  if (isSearchSized) {
    nodes.slice(0, budget).forEach((node) => visible.add(node.id));
  }
  return visible;
}

export function MemoryGraphCanvas({ nodes, edges, selectedNodeId, onSelectNode, fallbackText }: MemoryGraphCanvasProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const labelLayerRef = useRef<HTMLDivElement | null>(null);
  const [webglReady, setWebglReady] = useState(true);
  const [positions, setPositions] = useState<Map<string, THREE.Vector3>>(new Map());
  const degree = useMemo(() => buildDegreeMap(edges), [edges]);
  const visibleLabelIds = useMemo(() => pickVisibleLabelIds(nodes, edges, selectedNodeId), [nodes, edges, selectedNodeId]);
  const searchSizedLabels = nodes.length <= SEARCH_LABEL_LIMIT;

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
    camera.lookAt(0, 0, 0);
    const root = new THREE.Group();
    root.position.set(0, 2.4, 0);
    scene.add(root);
    scene.add(new THREE.AmbientLight(0xffffff, 0.74));
    const light = new THREE.DirectionalLight(0xffffff, 0.82);
    light.position.set(12, 18, 16);
    scene.add(light);

    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
    renderer.setClearColor(0x000000, 0);
    renderer.domElement.style.width = "100%";
    renderer.domElement.style.height = "100%";
    container.replaceChildren(renderer.domElement);

    const nodeObjects = new Map<string, THREE.Mesh>();
    const hitObjects = new Map<string, THREE.Mesh>();
    const planetGeometry = new THREE.SphereGeometry(0.3, 18, 18);
    const starGeometry = new THREE.IcosahedronGeometry(0.42, 1);
    const satelliteGeometry = new THREE.DodecahedronGeometry(0.28, 0);
    const hitSphere = new THREE.SphereGeometry(1, 12, 12);
    const labelLayer = labelLayerRef.current;
    if (labelLayer) {
      labelLayer.replaceChildren();
    }
    const labelElements = new Map<string, HTMLButtonElement>();
    for (const node of nodes) {
      const nodeDegree = degree.get(node.id) ?? 0;
      const color = NODE_COLORS[node.type] ?? 0xdfe6e9;
      const isStellar = STELLAR_NODE_TYPES.has(node.type);
      const isSatellite = SATELLITE_NODE_TYPES.has(node.type);
      const material = new THREE.MeshStandardMaterial({
        color,
        emissive: color,
        emissiveIntensity: isStellar ? (selectedNodeId === node.id ? 0.22 : 0.1) : selectedNodeId === node.id ? 0.1 : 0.015,
        roughness: isStellar ? 0.58 : 0.78,
        metalness: isSatellite ? 0.18 : 0.05,
      });
      const geometry = isStellar ? starGeometry : isSatellite ? satelliteGeometry : planetGeometry;
      const mesh = new THREE.Mesh(geometry, material);
      const size = isStellar
        ? 1.05 + Math.min(1.25, Math.sqrt(nodeDegree + 1) * 0.16)
        : 0.78 + Math.min(1.55, Math.sqrt(nodeDegree + 1) * 0.2);
      const selectedScale = selectedNodeId === node.id ? 1.16 : 1;
      mesh.scale.setScalar((node.type === "project" ? 1.86 : size) * selectedScale);
      const position = positions.get(node.id) ?? new THREE.Vector3();
      mesh.position.copy(position);
      mesh.rotation.set(nodeDegree * 0.13, nodeDegree * 0.19, nodeDegree * 0.07);
      mesh.userData.nodeId = node.id;
      root.add(mesh);
      nodeObjects.set(node.id, mesh);

      const hitMesh = new THREE.Mesh(
        hitSphere,
        new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false }),
      );
      hitMesh.position.copy(position);
      hitMesh.scale.setScalar(Math.max(1.35, (node.type === "project" ? 2.45 : size) * 1.85));
      hitMesh.userData.nodeId = node.id;
      root.add(hitMesh);
      hitObjects.set(node.id, hitMesh);

      if (labelLayer && visibleLabelIds.has(node.id)) {
        const showDetail = selectedNodeId === node.id || searchSizedLabels;
        const label = document.createElement("button");
        label.type = "button";
        label.className = styles.graphNodeBadge;
        label.dataset.selected = selectedNodeId === node.id ? "true" : "false";
        label.dataset.detail = showDetail ? "true" : "false";
        label.dataset.nodeType = node.type;
        const typeMark = document.createElement("span");
        typeMark.className = styles.graphNodeBadgeType;
        typeMark.textContent = NODE_SHORT_LABELS[node.type] ?? node.type.slice(0, 2).toUpperCase();
        const title = document.createElement("strong");
        title.textContent = trimText(node.label, showDetail ? 32 : 24);
        const summary = document.createElement("small");
        summary.textContent = trimText(node.summary || node.status || node.type, showDetail ? 72 : 40);
        label.replaceChildren(typeMark, title, ...(showDetail ? [summary] : []));
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
    let dragMode: DragMode = "";
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
      if (event.button !== 0 && event.button !== 1) {
        return;
      }
      event.preventDefault();
      dragMode = event.button === 1 ? "pan" : "rotate";
      moved = false;
      lastX = event.clientX;
      lastY = event.clientY;
      renderer.domElement.setPointerCapture(event.pointerId);
    };
    const onPointerMove = (event: PointerEvent) => {
      if (!dragMode) {
        return;
      }
      const dx = event.clientX - lastX;
      const dy = event.clientY - lastY;
      if (Math.abs(dx) + Math.abs(dy) > 3) {
        moved = true;
      }
      lastX = event.clientX;
      lastY = event.clientY;
      if (dragMode === "pan") {
        const worldPerPixel = (camera.position.z / Math.max(1, height)) * 1.18;
        root.position.x += dx * worldPerPixel;
        root.position.y -= dy * worldPerPixel;
        root.position.y = Math.max(-28, Math.min(28, root.position.y));
        root.position.x = Math.max(-36, Math.min(36, root.position.x));
        return;
      }
      root.rotation.y += dx * 0.006;
      root.rotation.x += dy * 0.004;
      root.rotation.x = Math.max(-1.2, Math.min(1.2, root.rotation.x));
    };
    const onPointerUp = (event: PointerEvent) => {
      dragMode = "";
      if (renderer.domElement.hasPointerCapture(event.pointerId)) {
        renderer.domElement.releasePointerCapture(event.pointerId);
      }
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
      camera.lookAt(0, 0, 0);
    };
    const preventAuxClick = (event: MouseEvent) => {
      if (event.button === 1) {
        event.preventDefault();
      }
    };
    const animate = () => {
      if (!dragMode) {
        root.rotation.y += 0.0012;
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
          label.style.transform = `translate3d(${x}px, ${y}px, 0) translate(-50%, calc(-100% - 20px)) scale(${selectedNodeId === nodeId ? 1.08 : 1})`;
          label.style.opacity = projected.z < 1 ? (selectedNodeId === nodeId ? "1" : "0.86") : "0";
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
    renderer.domElement.addEventListener("auxclick", preventAuxClick);
    renderer.domElement.addEventListener("wheel", onWheel, { passive: false });
    animate();
    return () => {
      cancelAnimationFrame(raf);
      resizeObserver.disconnect();
      renderer.domElement.removeEventListener("pointerdown", onPointerDown);
      renderer.domElement.removeEventListener("pointermove", onPointerMove);
      renderer.domElement.removeEventListener("pointerup", onPointerUp);
      renderer.domElement.removeEventListener("click", onClick);
      renderer.domElement.removeEventListener("auxclick", preventAuxClick);
      renderer.domElement.removeEventListener("wheel", onWheel);
      planetGeometry.dispose();
      starGeometry.dispose();
      satelliteGeometry.dispose();
      hitSphere.dispose();
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
  }, [nodes, edges, positions, selectedNodeId, onSelectNode, degree, visibleLabelIds, searchSizedLabels]);

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
