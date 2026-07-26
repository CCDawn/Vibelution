/**
 * Agents bulk config / metadata / archive pure helpers (structure M7).
 * Pure: no React hooks / Query / DOM (aside from pure path helpers).
 */
import type { AgentConfigWorkspaceAgent } from "../../api/types";
import { safeReturnToPath } from "../../app/navigationReturn";
import type {
  AgentBulkConfigApply,
  AgentBulkConfigDraft,
  AgentBulkConfigField,
} from "../AgentBulkConfigPanel";
import type { AgentBulkActionItem } from "../agentWorkspaceCache";
import { agentLabel } from "./agentRouteListModel";
import { agentLlmSlotModelId, FALLBACK_AGENT_LLM_SLOTS } from "./agentRouteLlmModel";

export const DEFAULT_BULK_CONFIG_DRAFT: AgentBulkConfigDraft = {
  dialogueModelId: "",
  promptTemplateId: "",
  primaryMode: "",
  roleKey: "",
};
export const DEFAULT_BULK_CONFIG_APPLY: AgentBulkConfigApply = {
  dialogueModelId: false,
  promptTemplateId: false,
  primaryMode: false,
  roleKey: false,
};

export function safeAgentCenterReturnTo(value: string | null | undefined) {
  return safeReturnToPath(value);
}

export function agentCenterReturnLabel(value: string | null | undefined, lang: "zh" | "en") {
  const normalized = String(value || "").trim();
  if (normalized === "supervised_evolution") {
    return lang === "zh" ? "返回监督进化" : "Back to supervised evolution";
  }
  if (normalized === "self_evolution") {
    return lang === "zh" ? "返回自进化" : "Back to self evolution";
  }
  if (normalized === "tools") {
    return lang === "zh" ? "返回工具配置" : "Back to tools";
  }
  if (normalized === "teams") {
    return lang === "zh" ? "返回团队" : "Back to teams";
  }
  if (normalized === "chat") {
    return lang === "zh" ? "返回会话" : "Back to chat";
  }
  if (normalized === "memory") {
    return lang === "zh" ? "返回记忆库" : "Back to memory";
  }
  if (normalized === "research_flow") {
    return lang === "zh" ? "返回科研流程画布" : "Back to research flow";
  }
  return lang === "zh" ? "返回来源页" : "Back";
}

export function optimisticArchivedAgent(agent: AgentConfigWorkspaceAgent): AgentConfigWorkspaceAgent {
  const updatedAt = new Date().toISOString();
  return {
    ...agent,
    status: "archived",
    updatedAt,
    runtimeStatus: {
      state: "archived",
      label: "Archived",
      reason: "agent_archive_pending",
      runId: agent.runtimeStatus?.runId || "",
      runKind: agent.runtimeStatus?.runKind || "",
      sessionId: agent.runtimeStatus?.sessionId || agent.directSessionId || "",
      summary: agent.runtimeStatus?.summary || "",
      updatedAt,
      staleRuntimeRunCount: agent.runtimeStatus?.staleRuntimeRunCount,
      latestHistoricalRunId: agent.runtimeStatus?.latestHistoricalRunId,
      latestHistoricalSessionId: agent.runtimeStatus?.latestHistoricalSessionId,
      latestHistoricalUpdatedAt: agent.runtimeStatus?.latestHistoricalUpdatedAt,
    },
  };
}

export function commonBulkConfigValue(
  agents: AgentConfigWorkspaceAgent[],
  selector: (agent: AgentConfigWorkspaceAgent) => string,
) {
  if (!agents.length) {
    return "";
  }
  const first = selector(agents[0]);
  return agents.every((agent) => selector(agent) === first) ? first : "";
}

export function bulkConfigValueMixed(
  agents: AgentConfigWorkspaceAgent[],
  selector: (agent: AgentConfigWorkspaceAgent) => string,
) {
  if (agents.length < 2) {
    return false;
  }
  const first = selector(agents[0]);
  return !agents.every((agent) => selector(agent) === first);
}

export function bulkConfigDraftFromAgents(agents: AgentConfigWorkspaceAgent[]): AgentBulkConfigDraft {
  return {
    dialogueModelId: commonBulkConfigValue(agents, (agent) => agentLlmSlotModelId(agent.llmBindings, FALLBACK_AGENT_LLM_SLOTS[0])),
    promptTemplateId: commonBulkConfigValue(agents, (agent) => agent.promptTemplateId || ""),
    primaryMode: commonBulkConfigValue(agents, (agent) => agent.primaryMode || ""),
    roleKey: commonBulkConfigValue(agents, (agent) => agent.roleKey || ""),
  };
}

export function bulkConfigApplyFields(apply: AgentBulkConfigApply) {
  const fields: string[] = [];
  if (apply.dialogueModelId) {
    fields.push("llmBindings");
  }
  if (apply.promptTemplateId) {
    fields.push("promptTemplateId");
  }
  if (apply.primaryMode) {
    fields.push("primaryMode");
  }
  if (apply.roleKey) {
    fields.push("roleKey");
  }
  return fields;
}

export function bulkConfigPatchFromDraft(draft: AgentBulkConfigDraft, apply: AgentBulkConfigApply) {
  const patch: Record<string, unknown> = {};
  if (apply.dialogueModelId) {
    patch.llmBindings = {
      dialogue: { modelId: draft.dialogueModelId },
    };
  }
  if (apply.promptTemplateId) {
    patch.promptTemplateId = draft.promptTemplateId;
  }
  if (apply.primaryMode) {
    patch.primaryMode = draft.primaryMode;
  }
  if (apply.roleKey) {
    patch.roleKey = draft.roleKey;
  }
  return patch;
}

export function bulkConfigFieldReady(field: AgentBulkConfigField, draft: AgentBulkConfigDraft) {
  if (field === "roleKey") {
    return true;
  }
  return Boolean(draft[field].trim());
}

export function bulkConfigReady(draft: AgentBulkConfigDraft, apply: AgentBulkConfigApply) {
  return (Object.keys(apply) as AgentBulkConfigField[]).some((field) => apply[field] && bulkConfigFieldReady(field, draft));
}

export function metadataString(agent: AgentConfigWorkspaceAgent | null | undefined, key: string) {
  const value = agent?.metadata?.[key];
  if (typeof value === "string") {
    return value.trim();
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return "";
}

export const metadataText = metadataString;

export function metadataFlag(agent: AgentConfigWorkspaceAgent | null | undefined, key: string) {
  const value = agent?.metadata?.[key];
  if (typeof value === "boolean") {
    return value;
  }
  return ["1", "true", "yes"].includes(metadataString(agent, key).toLowerCase());
}

export function agentArchiveProtected(agent: AgentConfigWorkspaceAgent | null | undefined) {
  const systemRole = metadataString(agent, "systemRole");
  const researchOrgRole = metadataString(agent, "researchOrgRole");
  const systemOwnedRole = [
    systemRole,
    metadataString(agent, "selfEvolutionRole"),
    metadataString(agent, "supervisedRole"),
    metadataString(agent, "aiSearchRole"),
  ].some(Boolean);
  return metadataFlag(agent, "protected")
    || metadataFlag(agent, "fixedRole")
    || systemOwnedRole
    || ["ceo", "organization_advisor", "capability_steward", "knowledge_steward"].includes(researchOrgRole);
}

export function agentBulkActionSummary(action: string, success: number, skipped: number, failed: number, notes: string[], lang: "zh" | "en") {
  const parts = lang === "zh"
    ? [`成功 ${success}`, `跳过 ${skipped}`, `失败 ${failed}`]
    : [`success ${success}`, `skipped ${skipped}`, `failed ${failed}`];
  const preview = notes.slice(0, 3).join("；");
  return preview ? `${action}: ${parts.join(" / ")}。${preview}` : `${action}: ${parts.join(" / ")}`;
}

export function agentBulkActionItemNote(
  item: AgentBulkActionItem,
  agentsById: Map<string, AgentConfigWorkspaceAgent>,
  fallback: string,
) {
  const agentId = String(item.agentId || "").trim();
  const label = agentLabel(agentsById.get(agentId)) || agentId || "-";
  const message = String(item.message || item.reason || fallback || "").trim();
  return message ? `${label}: ${message}` : label;
}

export function agentBulkPurgeCleanupPending(item: AgentBulkActionItem) {
  const purgeSummary = item.purgeSummary;
  if (!purgeSummary || typeof purgeSummary !== "object") {
    return false;
  }
  const sessions = (purgeSummary as { sessions?: unknown }).sessions;
  return Boolean(
    sessions
    && typeof sessions === "object"
    && (sessions as { cleanupPending?: unknown }).cleanupPending,
  );
}
