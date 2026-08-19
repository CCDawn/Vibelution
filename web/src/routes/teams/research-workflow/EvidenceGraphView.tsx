/**
 * Evidence graph view for the research workflow knowledge drawer.
 *
 * Fetches the run's evidence graph through the real backend command
 * (`open_evidence_graph` projection) and renders the DTO as a grouped,
 * readable node/edge list. No local graph state: the backend projection is the
 * single source of truth, and the empty state explains the missing facts.
 */
import { useCallback, useState } from "react";

import { fetchResearchWorkflowResearchLedger } from "../../../api/research-workflow";
import {
  VButton,
  VEmptyState,
  VStateSurface,
  VSurface,
} from "../../../components/vui";
import { useShellI18n } from "../../../i18n/useShellI18n";
import styles from "./EvidenceGraphView.styles";

export type EvidenceGraphViewProps = {
  runId: string;
  nodeId: string;
  teamId: string;
  runVersion: number;
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

type LoadState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ready"; graph: EvidenceGraphDto }
  | { kind: "error"; message: string };

const KIND_LABELS_ZH: Record<string, string> = {
  supports: "支持",
  derives: "推导",
};

const KIND_LABELS_EN: Record<string, string> = {
  supports: "supports",
  derives: "derives",
};

function nodeTitle(node: EvidenceGraphDto["nodes"][number]): string {
  if (typeof node.evidenceId === "string" && node.evidenceId) return node.evidenceId;
  if (typeof node.title === "string" && node.title) return node.title;
  return node.id;
}

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
  const kindLabels = isZh ? KIND_LABELS_ZH : KIND_LABELS_EN;
  const { nodes, edges } = graph;
  const byType = (type: string) => nodes.filter((node) => node.type === type);
  const sections: Array<{ key: string; label: string; items: EvidenceGraphDto["nodes"] }> = [
    { key: "evidence", label: isZh ? "证据" : "Evidence", items: byType("evidence") },
    { key: "claim", label: isZh ? "声明" : "Claims", items: byType("claim") },
    { key: "source", label: isZh ? "来源" : "Sources", items: byType("source") },
    {
      key: "other",
      label: isZh ? "其他节点" : "Other nodes",
      items: nodes.filter((n) => !["evidence", "claim", "source"].includes(n.type)),
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
                      {nodeTitle(node)}
                    </div>
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
                    {edge.source} —{kindLabels[edge.kind] ?? edge.kind}→ {edge.target}
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
  const [state, setState] = useState<LoadState>({ kind: "idle" });
  const { lang } = useShellI18n();
  const isZh = lang === "zh";

  const loadGraph = useCallback(() => {
    setState({ kind: "loading" });
    fetchResearchWorkflowResearchLedger(runId, { teamId })
      .then((ledger) => {
        const graph = (ledger.graph ?? {}) as EvidenceGraphDto;
        setState({
          kind: "ready",
          graph: {
            nodes: Array.isArray(graph.nodes) ? graph.nodes : [],
            edges: Array.isArray(graph.edges) ? graph.edges : [],
          },
        });
      })
      .catch((err: unknown) => {
        setState({ kind: "error", message: err instanceof Error ? err.message : String(err) });
      });
  }, [runId, teamId]);

  if (state.kind === "idle") {
    return (
      <VSurface tone="panel" className={styles.root} data-vui="evidence-graph-view">
        <VEmptyState
          title={isZh ? "证据关系图" : "Evidence graph"}
          className={styles.empty}
          actions={
            <VButton type="button" variant="secondary" onClick={() => void loadGraph()}>
              {isZh ? "生成证据图" : "Build evidence graph"}
            </VButton>
          }
        >
          {isZh
            ? "从运行记录与证据记录投影证据/来源/声明关系。"
            : "Projects evidence/source/claim relations from run and evidence records."}
        </VEmptyState>
      </VSurface>
    );
  }

  if (state.kind === "loading") {
    return (
      <VSurface tone="panel" className={styles.root}>
        <VStateSurface tone="loading" title={isZh ? "生成证据图" : "Building evidence graph"} fill className={styles.fill} />
      </VSurface>
    );
  }

  if (state.kind === "error") {
    return (
      <VSurface tone="panel" className={styles.root}>
        <div
          className={styles.error}
          role="alert"
        >
          {state.message}
        </div>
        <VButton type="button" variant="secondary" onClick={() => void loadGraph()}>
          {isZh ? "重试" : "Retry"}
        </VButton>
      </VSurface>
    );
  }

  const { nodes, edges } = state.graph;
  return (
    <VSurface tone="panel" className={styles.root} data-vui="evidence-graph-view">
      <EvidenceGraphContent graph={{ nodes, edges }} lang={lang} />
    </VSurface>
  );
}
