import { FileText, Network } from "lucide-react";

import type { MemoryKnowledgeGraphEdge, MemoryKnowledgeGraphNode } from "../api/types";
import { VButton } from "../components/vui";
import styles from "./MemoryGraphNodeInspectorPanel.styles";

export const GRAPH_NODE_TYPE_LABELS: Record<string, string> = {
  project: "Project",
  team: "Team",
  agent: "Agent",
  agent_private_memory: "Memory",
  knowledge_base: "KB",
  knowledge_item: "Item",
  source_artifact: "Source",
  refinement_proposal: "Proposal",
  knowledge_batch: "Batch",
  rating_suggestion: "Rating",
  runtime_scene: "Runtime",
  evolution: "Evolution",
  supervision: "Supervision",
  tag: "Tag",
};

export type MemoryGraphRelation = {
  edge: MemoryKnowledgeGraphEdge;
  neighbor: MemoryKnowledgeGraphNode;
};

export type MemoryGraphNodeInspectorCopy = {
  graphSelectedNode: string;
  graphNoSelection: string;
  graphResponsibilityQuestion: string;
  status: string;
  sourceOrigin: string;
  generatedAt: string;
  graphDirectChildren: string;
  graphNoChildren: string;
  graphNodeKnowledge: string;
  graphKnowledgeLoading: string;
  graphNoKnowledge: string;
  graphKnowledgeTruncated: string;
  graphRelations: string;
  graphNoRelations: string;
  graphIncoming: string;
  graphOutgoing: string;
};

type MemoryGraphContentItem = MemoryKnowledgeGraphNode["contentItems"][number];

type MemoryGraphNodeInspectorPanelProps = {
  copy: MemoryGraphNodeInspectorCopy;
  selectedGraphNode: MemoryKnowledgeGraphNode | null;
  selectedGraphChildren: MemoryKnowledgeGraphNode[];
  selectedGraphRelations: {
    incoming: MemoryGraphRelation[];
    outgoing: MemoryGraphRelation[];
  };
  selectedGraphDetailItems: MemoryGraphContentItem[];
  isGraphNodeDetailFetching: boolean;
  formatTimestamp: (value: string) => string;
  onFocusGraphNode: (nodeId: string) => void;
};

export function MemoryGraphNodeInspectorPanel({
  copy,
  selectedGraphNode,
  selectedGraphChildren,
  selectedGraphRelations,
  selectedGraphDetailItems,
  isGraphNodeDetailFetching,
  formatTimestamp,
  onFocusGraphNode,
}: MemoryGraphNodeInspectorPanelProps) {
  return (
    <aside className={styles.detailPanel}>
      <div className={styles.detailHeader}>
        <p className={styles.panelEyebrow}>{copy.graphSelectedNode}</p>
        <h2>{selectedGraphNode?.label ?? copy.graphNoSelection}</h2>
      </div>
      {selectedGraphNode ? (
        <>
          <section className={styles.selectedConfigSummary}>
            <strong>{selectedGraphNode.type}</strong>
            <p>{selectedGraphNode.summary || selectedGraphNode.id}</p>
          </section>
          <section className={styles.graphResponsibilityPanel}>
            <span>{copy.graphResponsibilityQuestion}</span>
            <strong>{selectedGraphNode.responsibilityQuestion || "-"}</strong>
          </section>
          <div className={styles.detailMeta}>
            <span>{copy.status}: {selectedGraphNode.status || "-"}</span>
            <span>{copy.sourceOrigin}: {selectedGraphNode.id}</span>
            <span>{copy.generatedAt}: {formatTimestamp(selectedGraphNode.createdAt || selectedGraphNode.updatedAt)}</span>
          </div>
          <section className={styles.graphRelationPanel}>
            <div className={styles.graphRelationHeader}>
              <p className={styles.panelEyebrow}>{copy.graphDirectChildren}</p>
              <strong>{selectedGraphChildren.length}</strong>
            </div>
            {!selectedGraphChildren.length ? (
              <p className={styles.graphRelationEmpty}>{copy.graphNoChildren}</p>
            ) : (
              <div className={styles.graphRelationGroup}>
                {selectedGraphChildren.map((child) => (
                  <VButton
                    key={child.id}
                    type="button"
                    data-node-type={child.type}
                    data-agent-category={String(child.visual?.agentCategory || child.metadata?.agentCategory || "")}
                    onClick={() => onFocusGraphNode(child.id)}
                  >
                    <small>{GRAPH_NODE_TYPE_LABELS[child.type] ?? child.type}</small>
                    <strong>{child.label}</strong>
                  </VButton>
                ))}
              </div>
            )}
          </section>
          <section className={styles.graphKnowledgePanel}>
            <div className={styles.graphRelationHeader}>
              <p className={styles.panelEyebrow}>{copy.graphNodeKnowledge}</p>
              <strong>{selectedGraphDetailItems.length}</strong>
            </div>
            {isGraphNodeDetailFetching ? (
              <p className={styles.graphRelationEmpty}>{copy.graphKnowledgeLoading}</p>
            ) : null}
            {!selectedGraphDetailItems.length && !isGraphNodeDetailFetching ? (
              <p className={styles.graphRelationEmpty}>{copy.graphNoKnowledge}</p>
            ) : (
              <div className={styles.graphKnowledgeList}>
                {selectedGraphDetailItems.map((item) => (
                  <article key={`${item.type}:${item.id}`} className={styles.graphKnowledgeItem}>
                    <div>
                      <strong>{item.title}</strong>
                      <small>{item.knowledgeBaseName || item.type}</small>
                    </div>
                    {item.summary ? <p>{item.summary}</p> : null}
                    {item.content ? (
                      <pre className={styles.graphKnowledgeContent}>{item.content}</pre>
                    ) : null}
                    {item.contentTruncated ? <em>{copy.graphKnowledgeTruncated}</em> : null}
                    <span>{item.status || "-"} · {formatTimestamp(String(item.updatedAt || item.createdAt || ""))}</span>
                  </article>
                ))}
              </div>
            )}
          </section>
          <section className={styles.graphRelationPanel}>
            <div className={styles.graphRelationHeader}>
              <p className={styles.panelEyebrow}>{copy.graphRelations}</p>
              <strong>{selectedGraphRelations.incoming.length + selectedGraphRelations.outgoing.length}</strong>
            </div>
            {!selectedGraphRelations.incoming.length && !selectedGraphRelations.outgoing.length ? (
              <p className={styles.graphRelationEmpty}>{copy.graphNoRelations}</p>
            ) : (
              <>
                <div className={styles.graphRelationGroup}>
                  <span>{copy.graphIncoming}</span>
                  {selectedGraphRelations.incoming.map((relation) => (
                    <VButton
                      key={relation.edge.id}
                      type="button"
                      data-node-type={relation.neighbor.type}
                      data-agent-category={String(relation.neighbor.visual?.agentCategory || relation.neighbor.metadata?.agentCategory || "")}
                      onClick={() => onFocusGraphNode(relation.neighbor.id)}
                    >
                      <small>{relation.edge.label || relation.edge.type}</small>
                      <strong>{relation.neighbor.label}</strong>
                    </VButton>
                  ))}
                </div>
                <div className={styles.graphRelationGroup}>
                  <span>{copy.graphOutgoing}</span>
                  {selectedGraphRelations.outgoing.map((relation) => (
                    <VButton
                      key={relation.edge.id}
                      type="button"
                      data-node-type={relation.neighbor.type}
                      data-agent-category={String(relation.neighbor.visual?.agentCategory || relation.neighbor.metadata?.agentCategory || "")}
                      onClick={() => onFocusGraphNode(relation.neighbor.id)}
                    >
                      <small>{relation.edge.label || relation.edge.type}</small>
                      <strong>{relation.neighbor.label}</strong>
                    </VButton>
                  ))}
                </div>
              </>
            )}
          </section>
          <details className={styles.rawPanel}>
            <summary>
              <FileText size={15} />
              <span>metadata</span>
            </summary>
            <pre>{JSON.stringify(selectedGraphNode.metadata ?? {}, null, 2)}</pre>
          </details>
        </>
      ) : (
        <section className={styles.emptyDetail}>
          <Network size={22} />
          <strong>{copy.graphNoSelection}</strong>
        </section>
      )}
    </aside>
  );
}
