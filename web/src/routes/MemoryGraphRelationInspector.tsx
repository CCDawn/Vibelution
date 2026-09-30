import { ArrowDown, ArrowLeft, ArrowUpRight } from "lucide-react";
import type { MemoryKnowledgeGraphEdge, MemoryKnowledgeGraphNode } from "../api/types";
import { VButton } from "../components/vui";
import styles from "./MemoryGraphRelationInspector.styles";

export function MemoryGraphRelationInspector({ edge, nodes, onNavigate, onBack }: {
  edge: MemoryKnowledgeGraphEdge; nodes: MemoryKnowledgeGraphNode[];
  onNavigate: (id: string) => void; onBack: () => void;
}) {
  const source = nodes.find(node => node.id === edge.source);
  const target = nodes.find(node => node.id === edge.target);
  const evidence = [source, target].find(node => node?.type === "source_artifact");
  return <section className={styles.panel} aria-label="关系与依据">
    <VButton variant="ghost" icon={<ArrowLeft size={14} />} onClick={onBack}>返回节点</VButton>
    <h2 className={styles.title}>{edge.label || edge.type}</h2>
    <div className={styles.endpoints}>
      <VButton variant="secondary" isDisabled={!source} onClick={() => source && onNavigate(source.id)} icon={<ArrowUpRight size={14} />}>起点 · {source?.label ?? "来源不可用"}</VButton>
      <p className={styles.direction}><ArrowDown size={16} />{edge.label || edge.type}</p>
      <VButton variant="secondary" isDisabled={!target} onClick={() => target && onNavigate(target.id)} icon={<ArrowUpRight size={14} />}>终点 · {target?.label ?? "目标不可用"}</VButton>
    </div>
    <div className={styles.sources}><h3 className={styles.sourceTitle}>关联来源</h3>
      {evidence ? <VButton variant="ghost" onClick={() => onNavigate(evidence.id)}>{evidence.label}</VButton> : <p className={styles.sourceEmpty}>当前关系未直接连接来源节点。关系名称与方向来自服务端，不将相关性当作事实支持。</p>}
    </div>
    <details className={styles.metadata}><summary>关系记录</summary><pre className={styles.metadataBody}>{JSON.stringify(edge.metadata ?? {}, null, 2)}</pre></details>
  </section>;
}
