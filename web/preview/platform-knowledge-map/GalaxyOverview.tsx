import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { VButton } from "../../src/components/vui";
import { nebulaMaterial } from "./previewNebula";
import type { GraphNode, GraphRelation, Topic, TopicId } from "./fixtures";

type TopicLink = { source: Topic; target: Topic; relations: GraphRelation[] };

export function GalaxyOverview({ topics, nodes, relations, highlightedTopics, onTopic, onRelation }: {
  topics: Topic[]; nodes: GraphNode[]; relations: GraphRelation[];
  highlightedTopics: Set<TopicId>; onTopic: (id: TopicId) => void;
  onRelation: (relation: GraphRelation) => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const labels = useRef(new Map<string, HTMLButtonElement>());
  const callbacks = useRef({ onTopic, onRelation });
  callbacks.current = { onTopic, onRelation };
  const [failed, setFailed] = useState(false);
  const nodeById = new Map(nodes.map(node => [node.id, node]));
  const links: TopicLink[] = [];
  for (const relation of relations) {
    const sourceTopic = nodeById.get(relation.source)?.topic;
    const targetTopic = nodeById.get(relation.target)?.topic;
    if (!sourceTopic || !targetTopic || sourceTopic === targetTopic) continue;
    const source = topics.find(topic => topic.id === sourceTopic)!;
    const target = topics.find(topic => topic.id === targetTopic)!;
    let group = links.find(link => link.source.id === source.id && link.target.id === target.id);
    if (!group) { group = { source, target, relations: [] }; links.push(group); }
    group.relations.push(relation);
  }
  const linkKey = links.map(link => link.relations.map(relation => relation.id).join(",")).join(";");

  useEffect(() => {
    const element = host.current;
    if (!element) return;
    let frame = 0;
    let renderer: THREE.WebGLRenderer | undefined;
    let controls: OrbitControls | undefined;
    let observer: ResizeObserver | undefined;
    const geometries = new Set<THREE.BufferGeometry>();
    const materials = new Set<THREE.Material>();
    const listeners: (() => void)[] = [];
    const dispose = () => {
      if (frame) cancelAnimationFrame(frame);
      observer?.disconnect();
      listeners.forEach(remove => remove());
      controls?.dispose();
      geometries.forEach(geometry => geometry.dispose());
      materials.forEach(material => material.dispose());
      renderer?.dispose();
      renderer?.domElement.remove();
    };
    try {
      renderer = new THREE.WebGLRenderer({ alpha: false, antialias: true });
      renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 1.5));
      renderer.setClearColor(0x101720);
      const canvas = renderer.domElement;
      canvas.setAttribute("aria-hidden", "true");
      element.appendChild(canvas);
      const scene = new THREE.Scene();
      const camera = new THREE.PerspectiveCamera(44, 1, 0.1, 160);
      camera.position.set(0, 3, 28);
      const ambient = new THREE.HemisphereLight(0xd9e7ff, 0x253743, 2.6);
      scene.add(ambient);
      const key = new THREE.DirectionalLight(0xffffff, 2.3);
      key.position.set(4, 7, 12); scene.add(key);
      const geometry = <T extends THREE.BufferGeometry>(value: T): T => { geometries.add(value); return value; };
      const material = <T extends THREE.Material>(value: T): T => { materials.add(value); return value; };
      const hits: THREE.Mesh[] = [];
      const labelPositions = new Map<string, THREE.Vector3>();
      topics.forEach((topic, topicIndex) => {
        const center = new THREE.Vector3(...topic.position);
        const cloud = new THREE.Mesh(geometry(new THREE.SphereGeometry(3.7, 28, 20)),
          material(nebulaMaterial(THREE, center, 3.7, topic.color, topicIndex * 11.71, 1.08)));
        cloud.position.copy(center); cloud.renderOrder = -3; scene.add(cloud);
        const dustPoints: number[] = [];
        for (let star = 0; star < 112; star++) {
          const y = 1 - 2 * (star + 0.5) / 112;
          const angle = star * 2.39996323;
          const r = 3.2 * Math.cbrt((((star * 17) % 111) + 1) / 112);
          const radial = Math.sqrt(1 - y * y);
          dustPoints.push(center.x + r * radial * Math.cos(angle), center.y + r * y, center.z + r * radial * Math.sin(angle));
        }
        const dustGeometry = geometry(new THREE.BufferGeometry());
        dustGeometry.setAttribute("position", new THREE.Float32BufferAttribute(dustPoints, 3));
        scene.add(new THREE.Points(dustGeometry, material(new THREE.PointsMaterial({ color: topic.color, size: 0.052, transparent: true, opacity: 0.84, depthWrite: false }))));
        const members = nodes.filter(node => node.topic === topic.id && node.access === "readable");
        members.forEach((_node, index) => {
          const mesh = new THREE.Mesh(geometry(new THREE.IcosahedronGeometry(index ? 0.15 : 0.34, 1)),
            material(new THREE.MeshStandardMaterial({ color: topic.color, roughness: 0.96, metalness: 0, emissive: topic.color, emissiveIntensity: 0.12 })));
          const angle = index * 2.39996323 + topicIndex;
          const y = 1 - 2 * (index + 0.5) / members.length;
          const r = index ? 1.55 : 0;
          mesh.position.set(center.x + Math.cos(angle) * r, center.y + y * r, center.z + Math.sin(angle) * r);
          scene.add(mesh);
        });
        const hit = new THREE.Mesh(geometry(new THREE.SphereGeometry(2.4, 12, 8)), material(new THREE.MeshBasicMaterial({ side: THREE.DoubleSide })));
        hit.position.copy(center); hit.updateMatrixWorld(); hit.userData.topic = topic.id; hits.push(hit);
        labelPositions.set(topic.id, center.clone().add(new THREE.Vector3(0, -2.1, 0)));
      });
      links.forEach((link, index) => {
        const start = new THREE.Vector3(...link.source.position);
        const end = new THREE.Vector3(...link.target.position);
        const middle = start.clone().lerp(end, 0.5).add(new THREE.Vector3(0, 1.4, 1));
        const curve = new THREE.QuadraticBezierCurve3(start, middle, end);
        const line = new THREE.Line(geometry(new THREE.BufferGeometry().setFromPoints(curve.getPoints(40))),
          material(new THREE.LineBasicMaterial({ color: 0xb2c7df, transparent: true, opacity: 0.5 })));
        scene.add(line);
        labelPositions.set(`link-${index}`, curve.getPoint(0.5));
      });
      controls = new OrbitControls(camera, canvas);
      controls.enableDamping = true; controls.dampingFactor = 0.1;
      controls.minDistance = 14; controls.maxDistance = 70;
      controls.target.set(0, 0, 0);
      const draw = () => {
        frame = 0;
        controls!.update();
        renderer!.render(scene, camera);
        const { width, height } = element.getBoundingClientRect();
        const occupied: { x: number; y: number; w: number; h: number }[] = [];
        labelPositions.forEach((position, id) => {
          const label = labels.current.get(id);
          if (!label) return;
          const point = position.clone().project(camera);
          const half = Math.min(label.offsetWidth / 2, width / 2);
          const x = Math.max(half + 5, Math.min(width - half - 5, (point.x + 1) * width / 2));
          const baseY = Math.max(40, Math.min(height - 55, (-point.y + 1) * height / 2));
          const w = label.offsetWidth; const h = label.offsetHeight;
          const y = [0, 75, -75, 150, -150, 225, -225].map(offset => Math.max(h / 2 + 8, Math.min(height - h / 2 - 55, baseY + offset)))
            .find(candidate => occupied.every(rect => Math.abs(rect.x - x) > (rect.w + w) / 2 + 8 || Math.abs(rect.y - candidate) > (rect.h + h) / 2 + 8)) ?? baseY;
          occupied.push({ x, y, w, h });
          label.style.transform = `translate(${x}px, ${y}px) translate(-50%, -50%)`;
          label.style.visibility = point.z >= -1 && point.z <= 1 ? "visible" : "hidden";
        });
      };
      const invalidate = () => { if (!frame) frame = requestAnimationFrame(draw); };
      controls.addEventListener("change", invalidate);
      const resize = () => {
        const { width, height } = element.getBoundingClientRect();
        if (!width || !height) return;
        renderer!.setSize(width, height, false); camera.aspect = width / height;
        camera.position.copy(camera.position.clone().normalize().multiplyScalar(Math.min(64, 26 * Math.max(1, 1.35 / camera.aspect))));
        camera.updateProjectionMatrix(); invalidate();
      };
      observer = new ResizeObserver(resize); observer.observe(element); resize();
      let down: { x: number; y: number } | undefined;
      const onDown = (event: PointerEvent) => { down = { x: event.clientX, y: event.clientY }; };
      const onUp = (event: PointerEvent) => {
        if (!down || Math.hypot(event.clientX - down.x, event.clientY - down.y) > 5) return;
        const rect = canvas.getBoundingClientRect();
        const ray = new THREE.Raycaster();
        ray.setFromCamera(new THREE.Vector2((event.clientX - rect.left) / rect.width * 2 - 1, -(event.clientY - rect.top) / rect.height * 2 + 1), camera);
        const hit = ray.intersectObjects(hits, false)[0];
        if (hit) callbacks.current.onTopic(hit.object.userData.topic as TopicId);
      };
      canvas.addEventListener("pointerdown", onDown); canvas.addEventListener("pointerup", onUp);
      listeners.push(() => { canvas.removeEventListener("pointerdown", onDown); canvas.removeEventListener("pointerup", onUp); });
      setFailed(false);
      return dispose;
    } catch {
      dispose(); setFailed(true); return undefined;
    }
  // This preview owns only chart geometry. The final renderer API is unchanged.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [topics, nodes, linkKey]);

  if (failed) return <div className="grid h-full content-center gap-4 p-8"><p className="text-vui-sm text-[var(--fg-secondary)]">当前浏览器无法显示 3D，可以从主题列表继续浏览。</p>{topics.map(topic => <VButton key={topic.id} onClick={() => onTopic(topic.id)}>{topic.label}</VButton>)}</div>;
  return <div className="galaxy-shell" role="region" aria-label="平台知识星系总览" data-preview-galaxy>
    <div ref={host} className="absolute inset-0" />
    <div className="pointer-events-none absolute inset-0">
      {topics.map(topic => <VButton key={topic.id} ref={element => { if (element) labels.current.set(topic.id, element); else labels.current.delete(topic.id); }}
        className="galaxy-topic pointer-events-auto" variant="secondary" contentLayout="plain" onClick={() => onTopic(topic.id)}
        data-search-match={highlightedTopics.has(topic.id)} aria-label={`进入${topic.label}`}>
        <div><strong className="block text-vui-sm">{topic.label}</strong><p>{nodes.filter(node => node.topic === topic.id && node.access === "readable").length} 个可见演示节点 · 进入主题 →</p></div>
      </VButton>)}
      {links.map((link, index) => <VButton key={`${link.source.id}-${link.target.id}`} ref={element => { if (element) labels.current.set(`link-${index}`, element); else labels.current.delete(`link-${index}`); }}
        className="galaxy-link pointer-events-auto" variant="ghost" onClick={() => onRelation(link.relations[0])}>{link.relations.length} 条跨主题关系 →</VButton>)}
    </div>
    <div className="pointer-events-none absolute bottom-4 left-5 right-5 flex flex-wrap justify-between gap-2 text-xs text-[#a6b6c9]"><span>点选星域进入主题 · 拖动环绕 · 滚轮缩放</span><span>星域按知识主题聚合，非节点类型分组</span></div>
  </div>;
}
