/**
 * Evidence graph view for the research workflow knowledge drawer.
 *
 * Fetches the run's evidence graph through the real backend command
 * (`open_evidence_graph` projection) and renders the DTO as a grouped,
 * readable node/edge list. No local graph state: the backend projection is the
 * single source of truth, and the empty state explains the missing facts.
 */
import { useCallback, useState } from "react";

import {
  VButton,
  VEmptyState,
  VStateSurface,
  VSurface,
} from "../../../components/vui";
import { executeNodeCommand } from "./nodeCommandAdapter";
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

const KIND_LABELS: Record<string, string> = {
  supports: "支持",
  derives: "推导",
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
export function EvidenceGraphContent({ graph }: { graph: EvidenceGraphDto }) {
  const { nodes, edges } = graph;
  const byType = (type: string) => nodes.filter((node) => node.type === type);
  const sections: Array<{ key: string; label: string; items: EvidenceGraphDto["nodes"] }> = [
    { key: "evidence", label: "证据", items: byType("evidence") },
    { key: "claim", label: "声明", items: byType("claim") },
    { key: "source", label: "来源", items: byType("source") },
    {
      key: "other",
      label: "其他节点",
      items: nodes.filter((n) => !["evidence", "claim", "source"].includes(n.type)),
    },
  ].filter((section) => section.items.length > 0);

  return (
    <>
      <div className={styles.header}>
        <div className={styles.eyebrow}>
          证据关系图 · {nodes.length} 节点 / {edges.length} 关系
        </div>
      </div>
      {nodes.length === 0 ? (
        <VEmptyState title="暂无图数据" className={styles.empty}>
          后端投影未返回节点；先完成证据卡与关系图产出。
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
              关系
            </div>
            {edges.length === 0 ? (
              <p className={styles.relationEmpty}>暂无关系边</p>
            ) : (
              <ul className={styles.list}>
                {edges.map((edge) => (
                  <li
                    key={`${edge.source}->${edge.target}:${edge.kind}`}
                    className={styles.relation}
                  >
                    {edge.source} —{KIND_LABELS[edge.kind] ?? edge.kind}→ {edge.target}
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

export function EvidenceGraphView({ runId, nodeId, teamId, runVersion }: EvidenceGraphViewProps) {
  const [state, setState] = useState<LoadState>({ kind: "idle" });

  const loadGraph = useCallback(() => {
    setState({ kind: "loading" });
    executeNodeCommand(
      { runId, nodeId, teamId, runVersion },
      { command: "open_evidence_graph", available: true, reason: "" },
    )
      .then((result) => {
        const graph = (result.raw?.graph ?? {}) as EvidenceGraphDto;
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
  }, [runId, nodeId, teamId, runVersion]);

  if (state.kind === "idle") {
    return (
      <VSurface tone="panel" className={styles.root} data-vui="evidence-graph-view">
        <VEmptyState
          title="证据关系图"
          className={styles.empty}
          actions={
            <VButton type="button" variant="secondary" onClick={() => void loadGraph()}>
              生成证据图
            </VButton>
          }
        >
          从运行记录与证据记录投影证据/来源/声明关系。
        </VEmptyState>
      </VSurface>
    );
  }

  if (state.kind === "loading") {
    return (
      <VSurface tone="panel" className={styles.root}>
        <VStateSurface tone="loading" title="生成证据图" fill className={styles.fill} />
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
          重试
        </VButton>
      </VSurface>
    );
  }

  const { nodes, edges } = state.graph;
  return (
    <VSurface tone="panel" className={styles.root} data-vui="evidence-graph-view">
      <EvidenceGraphContent graph={{ nodes, edges }} />
    </VSurface>
  );
}
