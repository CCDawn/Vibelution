import { useEffect, useRef, useState } from "react";
import { FileText, Lightbulb, Lock, Users, Bot, FlaskConical, BookOpen } from "lucide-react";
import { VButton } from "../../src/components/vui";
import type { GraphNode, GraphRelation, NodeKind, RelationLayer } from "./fixtures";

export const kindLabels: Record<NodeKind, string> = {
  knowledge: "知识条目", concept: "概念", source: "来源", conclusion: "结论",
  agent: "Agent", team: "团队", experiment: "实验 / 流程",
};
const icons = { knowledge: BookOpen, concept: Lightbulb, source: FileText, conclusion: Lightbulb, agent: Bot, team: Users, experiment: FlaskConical };

export function RelationGraph({ nodes, relations, layer, selectedNodeId, selectedRelationId, onNode, onRelation }: {
  nodes: GraphNode[]; relations: GraphRelation[]; layer: RelationLayer;
  selectedNodeId: string; selectedRelationId: string;
  onNode: (node: GraphNode) => void; onRelation: (relation: GraphRelation) => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 900, height: 600 });
  const [screenNarrow, setNarrow] = useState(innerWidth < 900);
  const narrow = screenNarrow || size.width < 660;
  useEffect(() => {
    const update = () => setNarrow(innerWidth < 900);
    addEventListener("resize", update); return () => removeEventListener("resize", update);
  }, []);
  useEffect(() => {
    if (!host.current) return;
    const observer = new ResizeObserver(entries => {
      const { width, height } = entries[0].contentRect;
      if (width && height) setSize({ width, height });
    });
    observer.observe(host.current); return () => observer.disconnect();
  }, [narrow]);
  const columnFor = (node: GraphNode) => layer === "ownership"
    ? node.kind === "team" ? 0 : node.kind === "agent" ? 1 : 2
    : layer === "evidence" ? node.kind === "source" || node.kind === "experiment" ? 2 : 0
      : node.kind === "concept" ? 1 : node.kind === "conclusion" ? 2 : 0;
  const positions = new Map<string, { x: number; y: number }>();
  for (let column = 0; column < 3; column++) {
    const members = nodes.filter(node => columnFor(node) === column);
    members.forEach((node, index) => positions.set(node.id, {
      x: 116 + column * Math.max(190, (size.width - 232) / 2),
      y: members.length === 1 ? size.height / 2 : 95 + index * (size.height - 180) / Math.max(1, members.length - 1),
    }));
  }
  const nodeById = new Map(nodes.map(node => [node.id, node]));
  if (narrow) return <div ref={host} className="h-full overflow-y-auto p-4" role="region" aria-label="窄屏关系列表">
    <p className="mb-3 text-vui-xs text-[var(--fg-secondary)]">窄屏按关系阅读，点选可看解释与依据。</p>
    <div className="grid gap-3">{relations.map(relation => <VButton key={relation.id} contentLayout="plain" variant="secondary"
      className="!h-auto min-h-16 w-full !justify-start !whitespace-normal p-3 text-left" onClick={() => onRelation(relation)}>
      <div><span className="block text-vui-sm">{nodeById.get(relation.source)?.label}</span><span className="block py-1 text-vui-xs text-[var(--accent-cool)]">— {relation.label} → {relation.status === "candidate" ? "待确认" : ""}</span><span className="block text-vui-sm">{nodeById.get(relation.target)?.label}</span></div>
    </VButton>)}</div>
    <div className="mt-5 grid gap-2"><p className="text-vui-xs text-[var(--fg-tertiary)]">节点详情</p>{nodes.map(node => <VButton key={node.id} className="!h-auto min-h-11 !whitespace-normal py-2" onClick={() => onNode(node)}>{node.label}</VButton>)}</div>
  </div>;
  return <div ref={host} className="relation-shell" role="region" aria-label="带方向和中文名称的知识关系图">
    <svg className="chart-svg" viewBox={`0 0 ${size.width} ${size.height}`} aria-hidden="true">
      <defs><marker id="relation-arrow" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto"><path d="M0 0L8 3L0 6Z" fill="var(--fg-tertiary)" /></marker><marker id="relation-arrow-selected" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto"><path d="M0 0L8 3L0 6Z" fill="var(--accent-cool)" /></marker></defs>
      {relations.map((relation, index) => {
        const source = positions.get(relation.source); const target = positions.get(relation.target);
        if (!source || !target) return null;
        const sameColumn = source.x === target.x;
        const direction = target.x >= source.x ? 1 : -1;
        const startX = source.x + 94 * direction;
        const endX = sameColumn ? target.x + 94 : target.x - 94 * direction;
        const midX = sameColumn ? startX + 70 : (startX + endX) / 2;
        const selected = relation.id === selectedRelationId;
        return <path key={relation.id} d={`M${startX} ${source.y} C${midX} ${source.y},${midX} ${target.y},${endX} ${target.y}`}
          fill="none" stroke={selected ? "var(--accent-cool)" : "var(--fg-tertiary)"} strokeWidth={selected ? 2.6 : 1.7}
          strokeOpacity={selectedRelationId && !selected ? 0.4 : 0.8} strokeDasharray={relation.status === "candidate" ? "5 5" : undefined}
          markerEnd={`url(#relation-arrow${selected ? "-selected" : ""})`} data-relation-path={relation.id} />;
      })}
    </svg>
    {relations.map((relation, index) => {
      const source = positions.get(relation.source); const target = positions.get(relation.target);
      if (!source || !target) return null;
      const sameColumn = source.x === target.x;
      const x = sameColumn ? source.x + 145 : (source.x + target.x) / 2;
      const y = (source.y + target.y) / 2 + (sameColumn ? 0 : (index % 3 - 1) * 14);
      return <VButton key={relation.id} variant="ghost" className="relation-label" data-selected={selectedRelationId === relation.id}
        data-candidate={relation.status === "candidate"} data-relation-id={relation.id} aria-label={`关系：${nodeById.get(relation.source)?.label} ${relation.label} ${nodeById.get(relation.target)?.label}`}
        onClick={() => onRelation(relation)} style={{ transform: `translate(${x}px, ${y}px) translate(-50%, -50%)` }}>
        {relation.label}{relation.status === "candidate" ? " · 待确认" : ""}
      </VButton>;
    })}
    {nodes.map(node => {
      const position = positions.get(node.id)!; const Icon = icons[node.kind];
      return <VButton key={node.id} className="relation-node" contentLayout="plain" data-selected={selectedNodeId === node.id}
        data-restricted={node.access === "restricted"} aria-label={`查看${node.label}`} onClick={() => onNode(node)}
        style={{ transform: `translate(${position.x}px, ${position.y}px) translate(-50%, -50%)` }}>
        <div className="min-w-0 w-full"><span className="mb-1 flex items-center gap-1.5 text-vui-xs text-[var(--fg-tertiary)]"><Icon size={13} />{kindLabels[node.kind]}{node.access === "restricted" && <Lock size={12} />}</span><strong className="block text-vui-sm font-medium leading-normal">{node.label}</strong></div>
      </VButton>;
    })}
  </div>;
}
