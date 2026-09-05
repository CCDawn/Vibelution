/**
 * Evidence graph view for the research workflow knowledge drawer.
 *
 * Reads the run's evidence ledger and renders its graph as a grouped,
 * readable node/edge list. No local graph state: the backend projection is the
 * single source of truth, and the empty state explains the missing facts.
 */
import { useQuery } from "@tanstack/react-query";
import { queryKeys } from "../../../api/queryKeys";

import { fetchResearchWorkflowResearchLedger } from "../../../api/research-workflow";
import {
  VButton,
  VRouteLinkButton,
  VEmptyState,
  VStateSurface,
  VSurface,
} from "../../../components/vui";
import { useShellI18n } from "../../../i18n/useShellI18n";
import styles from "./EvidenceGraphView.styles";
import { evidenceTitle, relationLabelsZh, safeSourceUrl } from "./evidenceReadingModel";

export type EvidenceGraphViewProps = {
  runId: string;
  teamId: string;
};

export type EvidenceGraphDto = {
  runId?: string;
  source?: string;
  nodes: Array<{
    id: string;
    type: string;
    [key: string]: unknown;
  }>;
  edges: Array<{
    source: string;
    target: string;
    kind: string;
  }>;
};

function nodeDetail(node: EvidenceGraphDto["nodes"][number]): string {
  const parts: string[] = [];
  if (typeof node.claim === "string" && node.claim) parts.push(String(node.claim));
  if (typeof node.evidenceType === "string" && node.evidenceType) {
    parts.push(String(node.evidenceType));
  }
  if (typeof node.status === "string" && node.status) parts.push(String(node.status));
  return parts.join(" · ");
}

/** Pure graph-content renderer (separate from fetch state for testability). */
export function EvidenceGraphContent({ graph, lang = "zh" }: { graph: EvidenceGraphDto; lang?: "zh" | "en" }) {
  const isZh = lang === "zh";
  const kindLabels = isZh ? relationLabelsZh : {};
  const { nodes, edges } = graph;
  const byType = (...types: string[]) => nodes.filter((node) => types.includes(node.type));
  const titles = new Map(nodes.map(node => [node.id, evidenceTitle(node)]));
  const sections: Array<{ key: string; label: string; items: EvidenceGraphDto["nodes"] }> = [
    { key: "evidence", label: isZh ? "证据" : "Evidence", items: byType("evidence") },
    { key: "claim", label: isZh ? "声明" : "Claims", items: byType("claim") },
    { key: "source", label: isZh ? "来源" : "Sources", items: byType("source", "source_manifest") },
    { key: "topic", label: isZh ? "研究主题" : "Research topics", items: byType("source_topic") },
    {
      key: "other",
      label: isZh ? "其他节点" : "Other nodes",
      items: nodes.filter((n) => !["evidence", "claim", "source", "source_manifest", "source_topic"].includes(n.type)),
    },
  ].filter((section) => section.items.length > 0);

  return (
    <>
      <div className={styles.header}>
        <div className={styles.eyebrow}>
          {isZh
            ? `证据关系图 · ${nodes.length} 节点 / ${edges.length} 关系`
            : `Evidence graph · ${nodes.length} nodes / ${edges.length} edges`}
        </div>
      </div>
      {nodes.length > 0 ? <p className="text-sm leading-relaxed text-[var(--fg-secondary)]">{isZh ? "关系来自本次运行的证据记录，不等同于结论已被验证。" : "Relationships are recorded for this run; they do not imply verified conclusions."}</p> : null}
      {nodes.length === 0 ? (
        <VEmptyState title={isZh ? "暂无图数据" : "No graph data"} className={styles.empty}>
          {isZh
            ? "后端投影未返回节点；先完成证据卡与关系图产出。"
            : "The backend projection returned no nodes; produce evidence cards and the relation graph first."}
        </VEmptyState>
      ) : (
        <>
          {sections.map((section) => (
            <div key={section.key} className={styles.section}>
              <div className={styles.eyebrow}>
                {section.label}（{section.items.length}）
              </div>
              <ul className={styles.list}>
                {section.items.map((node) => (
                  <li
                    key={node.id}
                    className={styles.item}
                  >
                    <div className={styles.itemTitle}>
                      {evidenceTitle(node)}
                    </div>
                    {safeSourceUrl(node.sourceUrl) ? <VRouteLinkButton to={safeSourceUrl(node.sourceUrl)!} target="_blank" rel="noopener noreferrer" variant="ghost">{isZh ? "打开来源 ↗" : "Open source ↗"}</VRouteLinkButton> : null}
                    {nodeDetail(node) ? (
                      <div className={styles.itemDetail}>{nodeDetail(node)}</div>
                    ) : null}
                  </li>
                ))}
              </ul>
            </div>
          ))}
          <div className={styles.section}>
            <div className={styles.eyebrow}>
              {isZh ? "关系" : "Edges"}
            </div>
            {edges.length === 0 ? (
              <p className={styles.relationEmpty}>{isZh ? "暂无关系边" : "No edges yet"}</p>
            ) : (
              <ul className={styles.list}>
                {edges.map((edge) => (
                  <li
                    key={`${edge.source}->${edge.target}:${edge.kind}`}
                    className={styles.relation}
                  >
                    {titles.get(edge.source) ?? (isZh ? "未收录的来源" : "Unlisted source")} —{kindLabels[edge.kind] ?? (isZh ? `相关关系（${edge.kind}）` : edge.kind)}→ {titles.get(edge.target) ?? (isZh ? "未收录的目标" : "Unlisted target")}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}
    </>
  );
}

export function EvidenceGraphView({ runId, teamId }: EvidenceGraphViewProps) {
  const { lang } = useShellI18n();
  const isZh = lang === "zh";
  const ledger = useQuery({
    queryKey: queryKeys.researchWorkflowLedger(runId, teamId),
    queryFn: () => fetchResearchWorkflowResearchLedger(runId, { teamId }),
    enabled: Boolean(runId && teamId),
  });

  if (ledger.isPending) {
    return (
      <VSurface tone="panel" className={styles.root}>
        <VStateSurface tone="loading" title={isZh ? "读取证据记录" : "Loading evidence records"} fill className={styles.fill} />
      </VSurface>
    );
  }

  if (ledger.isError) {
    return (
      <VSurface tone="panel" className={styles.root}>
        <div
          className={styles.error}
          role="alert"
        >
          {isZh ? "证据记录读取失败，请重试。" : "Could not load evidence records. Please retry."}
        </div>
        <VButton type="button" variant="secondary" onClick={() => void ledger.refetch()}>
          {isZh ? "重试" : "Retry"}
        </VButton>
      </VSurface>
    );
  }

  const graph = (ledger.data?.graph ?? {}) as EvidenceGraphDto;
  const nodes = Array.isArray(graph.nodes) ? graph.nodes : [];
  const edges = Array.isArray(graph.edges) ? graph.edges : [];
  return (
    <VSurface tone="panel" className={styles.root} data-vui="evidence-graph-view">
      <EvidenceGraphContent graph={{ nodes, edges }} lang={lang} />
    </VSurface>
  );
}
