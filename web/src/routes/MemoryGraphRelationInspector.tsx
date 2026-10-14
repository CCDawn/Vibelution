import { ArrowDown, ArrowLeft, ArrowUpRight } from "lucide-react";
import type { MemoryKnowledgeGraphEdge, MemoryKnowledgeGraphNode } from "../api/types";
import { VButton } from "../components/vui";
import styles from "./MemoryGraphRelationInspector.styles";

const sourceTypeLabels: Record<string, string> = { candidate: "已审核入库记录", review_record: "入库审核记录", source: "研究来源", source_artifact: "来源资料", paper_note: "论文笔记", mechanism: "机制记录", neuro_mechanism: "神经机制记录", mechanism_mapping: "机制映射记录", web: "网页来源", file: "文件来源" };

export function MemoryGraphRelationInspector({ edge, nodes, onNavigate, onBack }: {
  edge: MemoryKnowledgeGraphEdge; nodes: MemoryKnowledgeGraphNode[];
  onNavigate: (id: string) => void; onBack: () => void;
}) {
  const source = nodes.find(node => node.id === edge.source);
  const target = nodes.find(node => node.id === edge.target);
  const evidenceIds = Array.isArray(edge.metadata.evidenceNodeIds) ? edge.metadata.evidenceNodeIds.filter((id): id is string => typeof id === "string") : [];
  const evidence = nodes.filter(node => evidenceIds.includes(node.id) || ([source?.id, target?.id].includes(node.id) && ["source_artifact", "official_research_ref"].includes(node.type)));
  const reason = typeof edge.metadata.reason === "string" ? edge.metadata.reason : "关系名称与方向来自已有记录，不将相关性当作事实支持。";
  return <section className={styles.panel} aria-label="关系与依据">
    <VButton variant="ghost" icon={<ArrowLeft size={14} />} onClick={onBack}>返回节点</VButton>
    <h2 className={styles.title}>{edge.label || edge.type}</h2>
    <p className={styles.sourceEmpty}>{edge.metadata.status === "candidate" ? "待确认关联" : "已记录关系"}</p>
    <div className={styles.endpoints}>
      <VButton variant="secondary" isDisabled={!source} onClick={() => source && onNavigate(source.id)} icon={<ArrowUpRight size={14} />}>起点 · {source?.label ?? "来源不可用"}</VButton>
      <p className={styles.direction}><ArrowDown size={16} />{edge.label || edge.type}</p>
      <VButton variant="secondary" isDisabled={!target} onClick={() => target && onNavigate(target.id)} icon={<ArrowUpRight size={14} />}>终点 · {target?.label ?? "目标不可用"}</VButton>
    </div>
    <div className={styles.sources}><h3 className={styles.sourceTitle}>为什么相连</h3><p className={styles.sourceEmpty}>{reason}</p></div>
    <div className={styles.sources}><h3 className={styles.sourceTitle}>关联来源</h3>
      {evidence.length ? evidence.map(node => <div key={node.id} className={styles.evidenceItem}><VButton variant="ghost" className={styles.evidenceButton} onClick={() => onNavigate(node.id)}>{node.label}</VButton><p className={styles.sourceEmpty}>{sourceTypeLabels[String(node.metadata.sourceType)] ?? "来源记录"} · {String(node.metadata.reviewedAt ?? node.metadata.capturedAt ?? "")}</p>{Boolean(node.metadata.sourceRef) && <p className={styles.evidenceLocation}>{JSON.stringify(node.metadata.sourceRef)}</p>}</div>) : <p className={styles.sourceEmpty}>当前关系未提供直接来源节点。归属和主题分组不代表事实支持。</p>}
    </div>
    <details className={styles.metadata}><summary>关系记录</summary><pre className={styles.metadataBody}>{JSON.stringify(edge.metadata ?? {}, null, 2)}</pre></details>
  </section>;
}
