import { ArrowDown, ArrowLeft, ArrowUpRight } from "lucide-react";
import type { MemoryKnowledgeGraphEdge, MemoryKnowledgeGraphNode } from "../api/types";
import { VButton } from "../components/vui";

export function MemoryGraphRelationInspector({ edge, nodes, onNavigate, onBack }: {
  edge: MemoryKnowledgeGraphEdge; nodes: MemoryKnowledgeGraphNode[];
  onNavigate: (id: string) => void; onBack: () => void;
}) {
  const source = nodes.find(node => node.id === edge.source);
  const target = nodes.find(node => node.id === edge.target);
  const evidence = [source, target].find(node => node?.type === "source_artifact");
  return <section className="min-h-0 flex-1 space-y-6 overflow-auto p-6" aria-label="关系与依据">
    <VButton variant="ghost" icon={<ArrowLeft size={14} />} onClick={onBack}>返回节点</VButton>
    <h2 className="break-words text-xl font-medium">{edge.label || edge.type}</h2>
    <div className="grid gap-3">
      <VButton variant="secondary" isDisabled={!source} onClick={() => source && onNavigate(source.id)} icon={<ArrowUpRight size={14} />}>起点 · {source?.label ?? "来源不可用"}</VButton>
      <p className="flex items-center justify-center gap-2 text-sm text-[var(--fg-secondary)]"><ArrowDown size={16} />{edge.label || edge.type}</p>
      <VButton variant="secondary" isDisabled={!target} onClick={() => target && onNavigate(target.id)} icon={<ArrowUpRight size={14} />}>终点 · {target?.label ?? "目标不可用"}</VButton>
    </div>
    <div className="space-y-3 border-t border-[var(--vui-border-subtle)] pt-5"><h3 className="text-sm font-medium">关联来源</h3>
      {evidence ? <VButton variant="ghost" onClick={() => onNavigate(evidence.id)}>{evidence.label}</VButton> : <p className="text-sm leading-relaxed text-[var(--fg-secondary)]">当前关系未直接连接来源节点。关系名称与方向来自服务端，不将相关性当作事实支持。</p>}
    </div>
    <details className="text-xs text-[var(--fg-tertiary)]"><summary>关系记录</summary><pre className="mt-3 whitespace-pre-wrap break-words">{JSON.stringify(edge.metadata ?? {}, null, 2)}</pre></details>
  </section>;
}
