/**
 * View-model mapping for Agent-private memory inventory.
 * Field names follow `get_agent_memory_inventory` (fileCount, knowledgeSummary).
 */
import type {
  MemoryAgentMemoryAgentView,
  MemoryAgentMemoryItemView,
  MemoryAgentMemorySelectedAgentView,
  MemoryAgentMemorySelectedItemView,
  MemoryAgentMemorySummaryView,
} from "../MemoryAgentMemoryPanel";

export type AgentMemoryKnowledgeBase = {
  knowledgeBaseId?: string;
  scopedKnowledgeBaseId?: string;
  name?: string;
};

export type AgentMemoryKnowledgeSummary = {
  knowledgeBaseCount?: number;
  itemCount?: number;
  error?: string;
  knowledgeBases?: AgentMemoryKnowledgeBase[];
};

export type AgentMemoryInventoryItem = {
  id: string;
  relativePath?: string;
  title?: string;
  updatedAt?: string;
  path?: string;
  summary?: string;
  sizeBytes?: number;
  contentType?: string;
  contentTruncated?: boolean;
  content?: string;
};

export type AgentMemoryInventoryAgent = {
  agentId: string;
  displayName?: string;
  agentCode?: string;
  status?: string;
  hasPrivateMemory?: boolean;
  workspacePath?: string;
  privateMemoryRoot?: string;
  fileCount?: number;
  privateFileCount?: number;
  formalKnowledgeBaseCount?: number;
  origin?: string;
  primaryMode?: string;
  roleKey?: string;
  knowledgeSummary?: AgentMemoryKnowledgeSummary;
  items?: AgentMemoryInventoryItem[];
};

export type AgentMemoryInventorySummary = {
  agentCount?: number;
  privateFileCount?: number;
  privateByteCount?: number;
  formalKnowledgeItemCount?: number;
  formalKnowledgeBaseCount?: number;
  warningCount?: number;
  warnings?: string[];
};

export type AgentMemoryInventoryPayload = {
  agents?: AgentMemoryInventoryAgent[];
  summary?: AgentMemoryInventorySummary;
  generatedAt?: string;
  selectedAgent?: AgentMemoryInventoryAgent | null;
};

export function agentPrivateFileCount(agent: AgentMemoryInventoryAgent): number {
  return Number(agent.fileCount ?? agent.privateFileCount ?? 0);
}

export function agentFormalBaseCount(agent: AgentMemoryInventoryAgent): number {
  return Number(agent.knowledgeSummary?.knowledgeBaseCount ?? agent.formalKnowledgeBaseCount ?? 0);
}

export function agentFormalItemCount(agent: AgentMemoryInventoryAgent): number {
  return Number(agent.knowledgeSummary?.itemCount ?? 0);
}

export function toAgentMemorySummaryView(
  summary: AgentMemoryInventorySummary | undefined,
  privateByteText: string,
): MemoryAgentMemorySummaryView {
  return {
    agentCount: summary?.agentCount ?? 0,
    privateFileCount: summary?.privateFileCount ?? 0,
    privateByteText,
    formalKnowledgeItemCount: summary?.formalKnowledgeItemCount ?? 0,
    formalKnowledgeBaseCount: summary?.formalKnowledgeBaseCount ?? 0,
    warningCount: summary?.warnings?.length ?? summary?.warningCount ?? 0,
  };
}

export function toAgentMemoryAgentView(
  agent: AgentMemoryInventoryAgent,
  selectedAgentId: string,
): MemoryAgentMemoryAgentView {
  return {
    id: agent.agentId,
    name: agent.displayName || agent.agentId,
    status: agent.status || "",
    origin: agent.agentCode || agent.agentId,
    path: agent.privateMemoryRoot || agent.workspacePath || "",
    privateFileCount: agentPrivateFileCount(agent),
    formalKnowledgeBaseCount: agentFormalBaseCount(agent),
    hasPrivateMemory: Boolean(agent.hasPrivateMemory),
    active: agent.agentId === selectedAgentId,
  };
}

export function toSelectedAgentMemoryView(
  agent: AgentMemoryInventoryAgent,
): MemoryAgentMemorySelectedAgentView {
  const knowledgeBases = agent.knowledgeSummary?.knowledgeBases ?? [];
  return {
    name: agent.displayName || agent.agentId,
    privateRoot: agent.privateMemoryRoot || "",
    workspacePath: agent.workspacePath || "",
    fileCount: agentPrivateFileCount(agent),
    formalKnowledgeItemCount: agentFormalItemCount(agent),
    formalKnowledgeBaseCount: agentFormalBaseCount(agent),
    knowledgeError: agent.knowledgeSummary?.error,
    knowledgeBases: knowledgeBases.map((base) => ({
      id: base.scopedKnowledgeBaseId || base.knowledgeBaseId || "",
      label: base.name || base.knowledgeBaseId || "",
      title: base.scopedKnowledgeBaseId || base.knowledgeBaseId || "",
    })),
  };
}

export function toAgentMemoryItemView(
  item: AgentMemoryInventoryItem,
  selectedItemId: string,
  updatedAtText: string,
  sizeText: string,
): MemoryAgentMemoryItemView {
  return {
    id: item.id,
    title: item.relativePath || item.title || "",
    updatedAtText,
    path: item.path || "",
    summary: item.summary || "",
    sizeText,
    contentType: item.contentType || "",
    truncated: Boolean(item.contentTruncated),
    active: item.id === selectedItemId,
  };
}

export function toSelectedAgentMemoryItemView(
  item: AgentMemoryInventoryItem,
  sizeText: string,
  contentLanguage: string,
): MemoryAgentMemorySelectedItemView {
  return {
    title: item.relativePath || item.title || "",
    path: item.path || "",
    sizeText,
    contentType: item.contentType || "",
    contentLanguage,
    content: item.content || "",
  };
}
