import { useEffect, useId, useMemo, useRef, useState } from "react";
import type { MemoryKnowledgeGraphEdge, MemoryKnowledgeGraphNode } from "../../../../../api/types";
import type { VMemoryGraphCanvasProps } from "../../../product/memory/VMemoryGraphCanvas";
import { ShadcnButton } from "../ShadcnButton";

const RELATION_LABELS: Record<string, string> = {
  contains: "包含", belongs_to: "属于", owns: "拥有", responsible_for: "负责",
  produces: "产出", references: "引用", explains: "解释", supports: "支持",
  contradicts: "反驳", derived_from: "依据来自", evidence_from: "证据来自",
  maps_to: "映射到", inspires: "启发", approved_for_ingestion: "经审核收录",
  official_supports: "支持", official_maps_to: "映射到", official_inspires: "启发",
  official_approved_for_ingestion: "经审核收录",
  project_has_team: "包含团队", project_has_agent: "包含 Agent",
  project_has_knowledge_base: "包含知识库", team_has_agent: "包含 Agent",
  agent_has_knowledge_base: "拥有知识库", team_has_knowledge_base: "拥有知识库",
  knowledge_base_has_item: "收录", topic_has_item: "归入主题",
  source_artifact_supports_item: "支持条目", item_has_source_artifact: "来源于",
};

export function memoryRelationLabel(edge: MemoryKnowledgeGraphEdge): string {
  const label = edge.label.trim();
  if (/[\u3400-\u9fff]/.test(label)) return label;
  return RELATION_LABELS[edge.type] ?? RELATION_LABELS[label] ?? `关联（${edge.type}）`;
}

type Point = { x: number; y: number };
type Box = Point & { width: number; height: number };
type RelationGeometry = { edge: MemoryKnowledgeGraphEdge; path: string; label: Point; anchor: Point };
const NODE_WIDTH = 156;
const NODE_HEIGHT = 112;
const LABEL_WIDTH = 164;
const LABEL_HEIGHT = 72;
const buttonClass = "!h-auto min-h-11 min-w-0 !whitespace-normal break-words px-3 py-2 text-left aria-pressed:border-[var(--accent-cool)] aria-pressed:bg-[var(--vui-selection-bg)]";
const graphButtonClass = `${buttonClass} absolute left-0 top-0 -translate-x-1/2 -translate-y-1/2`;
const nodeKind = (node: MemoryKnowledgeGraphNode) => node.type === "official_research_ref"
  ? node.metadata.sourceType === "candidate" ? "入库记录" : node.metadata.sourceType === "review_record" ? "审核记录" : "科研引用"
  : ({ knowledge_item: "知识条目", source_artifact: "来源资料", knowledge_base: "知识库", agent: "智能体", team: "团队", project: "平台", topic: "主题", concept: "概念" } as Record<string, string>)[node.type] ?? "关联记录";

function columnFor(node: MemoryKnowledgeGraphNode): number {
  if (["source_artifact", "runtime_scene", "evolution", "supervision", "refinement_proposal"].includes(node.type)) return 2;
  if (["concept", "tag", "agent", "knowledge_item"].includes(node.type)) return 1;
  return 0;
}

function overlaps(left: Box, right: Box): boolean {
  return Math.abs(left.x - right.x) < (left.width + right.width) / 2 + 10
    && Math.abs(left.y - right.y) < (left.height + right.height) / 2 + 10;
}

/** Pixel geometry is the graph renderer's documented inline-style exception. */
function relationLayout(nodes: MemoryKnowledgeGraphNode[], edges: MemoryKnowledgeGraphEdge[], width: number, viewportHeight: number) {
  const columns = [0, 1, 2].map(column => nodes.filter(node => columnFor(node) === column).sort((a, b) => a.id.localeCompare(b.id)));
  const height = Math.max(viewportHeight, 420, Math.max(...columns.map(column => column.length)) * 160 + 100, edges.length * 70 + 100);
  const positions = new Map<string, Point>();
  const occupied: Box[] = [];
  columns.forEach((column, columnIndex) => column.forEach((node, index) => {
    const point = { x: 110 + columnIndex * (width - 220) / 2, y: (index + 1) * height / (column.length + 1) };
    positions.set(node.id, point);
    occupied.push({ ...point, width: NODE_WIDTH, height: NODE_HEIGHT });
  }));
  const relations: RelationGeometry[] = [];
  for (const edge of edges) {
    const source = positions.get(edge.source)!;
    const target = positions.get(edge.target)!;
    const sameColumn = source.x === target.x;
    const direction = target.x >= source.x ? 1 : -1;
    const startX = source.x + NODE_WIDTH / 2 * direction;
    const endX = sameColumn ? target.x + NODE_WIDTH / 2 : target.x - NODE_WIDTH / 2 * direction;
    const midX = sameColumn ? Math.min(width - 25, startX + 100) : (startX + endX) / 2;
    const preferred = { x: midX, y: (source.y + target.y) / 2 };
    const candidates: Point[] = [];
    for (let y = LABEL_HEIGHT / 2 + 12; y <= height - LABEL_HEIGHT / 2 - 12; y += 36) {
      for (let x = LABEL_WIDTH / 2 + 12; x <= width - LABEL_WIDTH / 2 - 12; x += 48) candidates.push({ x, y });
    }
    candidates.sort((a, b) => Math.hypot(a.x - preferred.x, a.y - preferred.y) - Math.hypot(b.x - preferred.x, b.y - preferred.y));
    const label = candidates.find(point => !occupied.some(box => overlaps({ ...point, width: LABEL_WIDTH, height: LABEL_HEIGHT }, box)));
    // Dense/long relation payloads retain every label in the readable list.
    if (!label) return null;
    occupied.push({ ...label, width: LABEL_WIDTH, height: LABEL_HEIGHT });
    const path = edge.source === edge.target
      ? `M${startX} ${source.y - 20} C${midX} ${source.y - 100},${midX} ${source.y + 100},${endX} ${source.y + 20}`
      : `M${startX} ${source.y} C${midX} ${source.y},${midX} ${target.y},${endX} ${target.y}`;
    relations.push({ edge, path, label, anchor: { x: (startX + 6 * midX + endX) / 8, y: preferred.y } });
  }
  return { height, positions, relations };
}

export function ShadcnMemoryRelationGraph({ nodes, edges, selectedNodeId, selectedEdgeId, onSelectNode, onSelectEdge }: VMemoryGraphCanvasProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  const markerId = "memory-relation-" + useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const nodeById = useMemo(() => new Map(nodes.map(node => [node.id, node])), [nodes]);
  const visibleEdges = useMemo(() => edges.filter(edge => nodeById.has(edge.source) && nodeById.has(edge.target)), [edges, nodeById]);
  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const measure = () => {
      const bounds = host.getBoundingClientRect();
      setSize(previous => previous.width === bounds.width && previous.height === bounds.height ? previous : { width: bounds.width, height: bounds.height });
    };
    measure();
    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", measure);
      return () => window.removeEventListener("resize", measure);
    }
    const observer = new ResizeObserver(entries => {
      const bounds = entries[0]?.contentRect;
      if (bounds) setSize(previous => previous.width === bounds.width && previous.height === bounds.height ? previous : { width: bounds.width, height: bounds.height });
    });
    observer.observe(host);
    return () => observer.disconnect();
  }, []);
  const geometry = useMemo(() => {
    if (size.width < 660 || nodes.length > 12 || visibleEdges.length > 18
      || nodes.some(node => node.label.length > 48) || visibleEdges.some(edge => memoryRelationLabel(edge).length > 26)) return null;
    return relationLayout(nodes, visibleEdges, size.width, size.height);
  }, [nodes, visibleEdges, size]);
  const relationName = (edge: MemoryKnowledgeGraphEdge) => `${nodeById.get(edge.source)?.label} — ${memoryRelationLabel(edge)} → ${nodeById.get(edge.target)?.label}`;
  const candidate = (edge: MemoryKnowledgeGraphEdge) => edge.metadata.status === "candidate";
  return (
    <div ref={hostRef} className="relative h-full min-h-0 min-w-0 flex-1 overflow-auto" role="region"
      aria-label="带方向和中文名称的知识关系图" data-memory-graph-mode="relations" data-relation-layout={geometry ? "graph" : "list"}>
      {nodes.length === 0 ? <p className="p-4 text-vui-sm text-[var(--fg-tertiary)]" role="status">当前范围没有可见节点。</p> : !geometry ? (
        <div className="grid min-w-0 gap-4 p-4">
          <p className="text-vui-xs text-[var(--fg-tertiary)]">按关系阅读，点选查看解释与依据。</p>
          {visibleEdges.length === 0 ? <p role="status" className="text-vui-sm text-[var(--fg-secondary)]">当前范围没有可见关系，可阅读下方节点的标题和摘要。</p> : null}
          <ul className="m-0 grid min-w-0 list-none gap-3 p-0" aria-label="知识关系列表">
            {visibleEdges.map(edge => <li key={edge.id} className="min-w-0">
              <ShadcnButton className={`${buttonClass} w-full !justify-start ${candidate(edge) ? "!border-dashed" : ""}`} aria-label={relationName(edge)} aria-pressed={selectedEdgeId === edge.id}
                data-relation-id={edge.id} data-candidate={candidate(edge)} isDisabled={!onSelectEdge} onClick={() => onSelectEdge?.(edge.id)}>
                <span className="block min-w-0">
                  <span className="block">{nodeById.get(edge.source)?.label}</span>
                  <span className="block py-1 text-[var(--accent-cool)]">— {memoryRelationLabel(edge)} →{candidate(edge) ? " · 待确认" : ""}</span>
                  <span className="block">{nodeById.get(edge.target)?.label}</span>
                </span>
              </ShadcnButton>
            </li>)}
          </ul>
          <div className="grid min-w-0 gap-2" role="group" aria-label="节点详情">
            {nodes.map(node => <ShadcnButton key={node.id} className={`${buttonClass} w-full !justify-start`}
              aria-label={`查看${node.label}`} aria-pressed={selectedNodeId === node.id} data-node-id={node.id} onClick={() => onSelectNode(node.id)}><span className="block min-w-0"><small className="mb-1 block text-vui-xs text-[var(--fg-tertiary)]">{nodeKind(node)}</small><strong className="block font-medium">{node.label}</strong>{node.summary && <span className="mt-2 line-clamp-3 block text-vui-xs leading-relaxed text-[var(--fg-secondary)]">{node.summary}</span>}</span></ShadcnButton>)}
          </div>
        </div>
      ) : (
        <div className="relative min-w-0" style={{ height: geometry.height }}>
          {visibleEdges.length === 0 ? <p className="absolute left-4 top-4 text-vui-xs text-[var(--fg-tertiary)]" role="status">当前范围没有可见关系，可点选节点。</p> : null}
          <svg className="pointer-events-none absolute inset-0 h-full w-full" viewBox={`0 0 ${size.width} ${geometry.height}`} aria-hidden="true">
            <defs>{[false, true].map(selected => <marker key={String(selected)} id={`${markerId}-${selected ? "selected" : "normal"}`} markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto">
              <path d="M0 0L8 3L0 6Z" fill={selected ? "var(--accent-cool)" : "var(--fg-tertiary)"} />
            </marker>)}</defs>
            {geometry.relations.map(({ edge, path, label, anchor }) => {
              const selected = selectedEdgeId === edge.id;
              return <g key={edge.id}>
                <path d={path} fill="none" stroke={selected ? "var(--accent-cool)" : "var(--fg-tertiary)"} strokeWidth={selected ? 2.6 : 1.7}
                  strokeOpacity={selectedEdgeId && !selected ? 0.45 : 0.8} strokeDasharray={candidate(edge) ? "5 5" : undefined}
                  markerEnd={`url(#${markerId}-${selected ? "selected" : "normal"})`} data-relation-path={edge.id} />
                <path d={`M${label.x} ${label.y} L${anchor.x} ${anchor.y}`}
                  stroke="var(--vui-border-subtle)" strokeDasharray="2 4" fill="none" />
              </g>;
            })}
          </svg>
          {geometry.relations.map(({ edge, label }) => <ShadcnButton key={edge.id} className={`${graphButtonClass} z-10 !w-[164px] !max-w-[164px] !h-[72px] !justify-center text-center text-vui-xs ${candidate(edge) ? "!border-dashed" : ""}`}
            aria-label={relationName(edge)} aria-pressed={selectedEdgeId === edge.id} data-relation-id={edge.id} data-candidate={candidate(edge)}
            isDisabled={!onSelectEdge} onClick={() => onSelectEdge?.(edge.id)} style={{ left: label.x, top: label.y }}>
            {memoryRelationLabel(edge)}{candidate(edge) ? " · 待确认" : ""}
          </ShadcnButton>)}
          {nodes.map(node => {
            const point = geometry.positions.get(node.id)!;
            return <ShadcnButton key={node.id} className={`${graphButtonClass} z-20 !w-[156px] !max-w-[156px] !h-[112px] !justify-start text-vui-sm`}
              aria-label={`查看${node.label}`} aria-pressed={selectedNodeId === node.id} data-node-id={node.id}
              onClick={() => onSelectNode(node.id)} style={{ left: point.x, top: point.y }}>{node.label}</ShadcnButton>;
          })}
        </div>
      )}
    </div>
  );
}
