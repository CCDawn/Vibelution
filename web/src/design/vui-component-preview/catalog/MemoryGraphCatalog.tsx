import { useState } from "react";

import type { MemoryKnowledgeGraphEdge, MemoryKnowledgeGraphNode } from "../../../api/types";
import { VMemoryGraphCanvas } from "../../../components/vui";
import { VuiPreviewCard } from "../VuiPreviewCard";
import { VuiPreviewSection } from "../VuiPreviewSection";
import { memoryGraphCatalogStyles as styles } from "./MemoryGraphCatalog.styles";

const sampleNodes: MemoryKnowledgeGraphNode[] = [
  {
    id: "preview-project",
    type: "project",
    label: "Vibelution 项目",
    summary: "用于展示记忆图谱节点、关系与选择状态的本地示例。",
    status: "active",
    createdAt: "2026-09-30T00:00:00.000Z",
    updatedAt: "2026-09-30T00:00:00.000Z",
    metadata: {},
    responsibilityQuestion: "",
    visual: { size: "root" },
    childNodeIds: ["preview-agent"],
    contentItems: [],
  },
  {
    id: "preview-agent",
    type: "agent",
    label: "记忆助手",
    summary: "读取当前授权范围内的私有记忆与知识。",
    status: "active",
    createdAt: "2026-09-30T00:00:00.000Z",
    updatedAt: "2026-09-30T00:00:00.000Z",
    metadata: {},
    responsibilityQuestion: "如何按需检索相关记忆？",
    visual: { size: "group", agentCategory: "session_agent" },
    childNodeIds: ["preview-private-memory"],
    contentItems: [],
  },
  {
    id: "preview-private-memory",
    type: "agent_private_memory",
    label: "会话中的记忆检索",
    summary: "用户确认的重要项目偏好与恢复上下文。",
    status: "active",
    createdAt: "2026-09-30T00:00:00.000Z",
    updatedAt: "2026-09-30T00:00:00.000Z",
    metadata: {},
    responsibilityQuestion: "哪些记忆与当前会话最相关？",
    visual: { size: "leaf" },
    childNodeIds: [],
    contentItems: [],
  },
  {
    id: "preview-knowledge-base",
    type: "knowledge_base",
    label: "Agent Wiki",
    summary: "经治理后可检索的项目知识库。",
    status: "active",
    createdAt: "2026-09-30T00:00:00.000Z",
    updatedAt: "2026-09-30T00:00:00.000Z",
    metadata: {},
    responsibilityQuestion: "哪些已审核知识可以作为依据？",
    visual: { size: "container" },
    childNodeIds: [],
    contentItems: [],
  },
];

const sampleEdges: MemoryKnowledgeGraphEdge[] = [
  {
    id: "preview-project-agent",
    source: "preview-project",
    target: "preview-agent",
    type: "contains_agent",
    label: "包含 Agent",
    weight: 1,
    metadata: {},
  },
  {
    id: "preview-agent-memory",
    source: "preview-agent",
    target: "preview-private-memory",
    type: "owns_private_memory",
    label: "私有记忆",
    weight: 1,
    metadata: {},
  },
  {
    id: "preview-memory-knowledge",
    source: "preview-private-memory",
    target: "preview-knowledge-base",
    type: "references_knowledge_base",
    label: "关联知识库",
    weight: 1,
    metadata: {},
  },
];

export function MemoryGraphCatalog() {
  const [selectedNodeId, setSelectedNodeId] = useState("");
  const [selectedEdgeId, setSelectedEdgeId] = useState("");
  const selectedNode = sampleNodes.find((node) => node.id === selectedNodeId);
  const selectedEdge = sampleEdges.find((edge) => edge.id === selectedEdgeId);

  return (
    <VuiPreviewSection title="Memory Graph">
      <VuiPreviewCard name="VMemoryGraphCanvas · 示例数据，不连接 API" className={styles.card}>
        <div className={styles.content}>
          <div className={styles.canvas}>
            <VMemoryGraphCanvas
              nodes={sampleNodes}
              edges={sampleEdges}
              selectedNodeId={selectedNodeId}
              onSelectNode={(nodeId) => {
                setSelectedNodeId(nodeId);
                setSelectedEdgeId("");
              }}
              onSelectEdge={(edgeId) => { setSelectedEdgeId(edgeId); setSelectedNodeId(""); }}
              fallbackText="3D 画布不可用时，可使用下面的选择状态继续检查组件。"
            />
          </div>
          <div className={styles.selection} aria-live="polite">
            <span>
              {selectedNode
                ? `已选节点：${selectedNode.label}`
                : selectedEdge
                  ? `已选关系：${selectedEdge.label}（${selectedEdge.source} → ${selectedEdge.target}）`
                  : "点击画布中的节点或关系，查看选择回调。"}
            </span>
            <span className={styles.sampleLabel}>4 个节点 · 3 条关系 · 仅为示例数据</span>
          </div>
        </div>
      </VuiPreviewCard>
    </VuiPreviewSection>
  );
}
