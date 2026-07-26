/**
 * Agents tool/memory/membership/runtime policy draft mappers (structure M3).
 * Pure: no React hooks / Query / DOM.
 */
import type {
  AgentConfigWorkspace,
  AgentConfigWorkspaceAgent,
  AgentDelegationPolicy,
  AgentSupervisionPolicy,
  MemoryPolicy,
  ToolBundle,
  ToolPolicy,
  ToolRegistryItem,
} from "../../api/types";
import type { AgentConfigDraft } from "../AgentCoreConfigPanel";
import type { AgentMemoryPolicyDraft } from "../AgentMemoryPolicyPanel";
import type { AgentModeMembershipDraft } from "../AgentModeMembershipPanel";
import type { AgentPersonaDraft } from "../AgentPersonaProfilePanel";
import type { AgentTaskDraft } from "../AgentTaskProfilePanel";
import {
  draftFromAgent,
  normalizeToolPolicyDraftForAgent,
  personaDraftFromAgent,
  sameStringSet,
  sortedIds,
  taskDraftFromAgent,
  type AgentToolPolicyDraft,
} from "./agentRouteDraftModel";
import { uniqueModes } from "./agentRouteWorkspaceModel";

export type AgentToolGovernanceDraft = {
  proposedByAgentId: string;
  reason: string;
  applyMode: "auto" | "review";
};

export type AgentDelegationPolicyDraft = AgentDelegationPolicy;
export type AgentSupervisionPolicyDraft = AgentSupervisionPolicy;

export type AgentDraftSyncSource = {
  agentId: string;
  config: AgentConfigDraft;
  membership: AgentModeMembershipDraft;
  persona: AgentPersonaDraft;
  task: AgentTaskDraft;
  toolPolicy: AgentToolPolicyDraft;
  memoryPolicy: AgentMemoryPolicyDraft;
  delegationPolicy: AgentDelegationPolicyDraft;
  supervisionPolicy: AgentSupervisionPolicyDraft;
};

export type ToolPolicyMode = "inherited" | "allowed" | "blocked" | "excluded";
export type ToolPermissionGroup = {
  bundleId: string;
  label: string;
  description: string;
  category: string;
  tools: ToolRegistryItem[];
  allowedCount: number;
  blockedCount: number;
  inheritedCount: number;
  highRiskCount: number;
};
export type ToolBundleApplyMode = "merge" | "replace";
export type AgentCapabilityPreview = {
  effectiveAllowed: number;
  preferred: number;
  blocked: number;
  inherited: number;
  highRiskAllowed: number;
  explicitAllowed: number;
  writeBoundaryLabel: string;
};

export function draftSyncSourceFromAgent(
  workspace: AgentConfigWorkspace | undefined,
  agent: AgentConfigWorkspaceAgent | null | undefined,
): AgentDraftSyncSource {
  return {
    agentId: agent?.agentId ?? "",
    config: draftFromAgent(agent),
    membership: membershipDraftFromWorkspace(workspace, agent),
    persona: personaDraftFromAgent(agent),
    task: taskDraftFromAgent(agent),
    toolPolicy: toolPolicyDraftFromAgent(agent),
    memoryPolicy: memoryPolicyDraftFromAgent(agent),
    delegationPolicy: delegationPolicyDraftFromAgent(agent),
    supervisionPolicy: supervisionPolicyDraftFromAgent(agent),
  };
}

export function buildAgentCapabilityPreview(
  draft: AgentToolPolicyDraft,
  tools: ToolRegistryItem[],
  copy: { sharedWriteScope: string; privateWriteScope: string },
): AgentCapabilityPreview {
  const allowed = new Set(draft.allowedTools);
  const blocked = new Set(draft.blockedTools);
  const highRiskAllowed = tools.filter((tool) => allowed.has(tool.name) && (tool.permissionTier === "high" || (tool.riskTags ?? []).length > 0)).length;
  const explicitAllowed = tools.filter((tool) => allowed.has(tool.name) && tool.permissionPolicy?.requiresExplicitAllow).length;
  return {
    effectiveAllowed: draft.allowedTools.length,
    preferred: draft.preferredTools.length,
    blocked: draft.blockedTools.length,
    inherited: Math.max(0, tools.length - allowed.size - blocked.size),
    highRiskAllowed,
    explicitAllowed,
    writeBoundaryLabel: draft.writeScopes.includes("shared") ? copy.sharedWriteScope : copy.privateWriteScope,
  };
}

export function membershipDraftEqualsDraft(left: AgentModeMembershipDraft, right: AgentModeMembershipDraft) {
  return (Object.keys(right) as Array<keyof AgentModeMembershipDraft>).every((key) => left[key] === right[key]);
}

export function slotForAgent(slots: Record<string, string> | undefined, agentId: string) {
  return Object.entries(slots ?? {}).find(([, value]) => value === agentId)?.[0] ?? "";
}

export function membershipDraftFromWorkspace(
  workspace: AgentConfigWorkspace | undefined,
  agent: AgentConfigWorkspaceAgent | null | undefined,
): AgentModeMembershipDraft {
  const agentId = agent?.agentId ?? "";
  const chat = workspace?.modeBindings.chat;
  const research = workspace?.modeBindings.research;
  const supervised = workspace?.modeBindings.supervised_evolution;
  const selfEvolution = workspace?.modeBindings.self_evolution;
  return {
    chatDefault: Boolean(agentId && chat?.defaultAgentId === agentId),
    chatAvailable: Boolean(agentId && chat?.availableAgentIds?.includes(agentId)),
    researchPool: Boolean(agentId && research?.pool?.includes(agentId)),
    supervisedSlot: agentId ? slotForAgent(supervised?.slots, agentId) : "",
    selfEvolutionSlot: agentId ? slotForAgent(selfEvolution?.slots, agentId) : "",
  };
}

export function membershipDraftEqualsWorkspace(
  draft: AgentModeMembershipDraft,
  workspace: AgentConfigWorkspace | undefined,
  agent: AgentConfigWorkspaceAgent | null | undefined,
) {
  const base = membershipDraftFromWorkspace(workspace, agent);
  return (Object.keys(base) as Array<keyof AgentModeMembershipDraft>).every((key) => draft[key] === base[key]);
}

export function defaultToolPolicy(policyId = "default"): ToolPolicy {
  return {
    policyId,
    allowedTools: [],
    preferredTools: [],
    blockedTools: [],
    readScopes: [],
    writeScopes: [],
    allowedCommandKinds: [],
    blockedCommandPatterns: [],
    networkAccess: "inherit",
    mutationAccess: "inherit",
    maxCallsPerTurn: 0,
    perToolRules: {},
  };
}

export function toolPolicyDraftFromAgent(agent: AgentConfigWorkspaceAgent | null | undefined): AgentToolPolicyDraft {
  return normalizeToolPolicyDraftForAgent({
    allowedTools: sortedIds(agent?.toolPolicy?.allowedTools ?? []),
    preferredTools: sortedIds(agent?.toolPolicy?.preferredTools ?? []),
    blockedTools: sortedIds(agent?.toolPolicy?.blockedTools ?? []),
    readScopes: sortedIds(agent?.toolPolicy?.readScopes ?? []),
    writeScopes: sortedIds(agent?.toolPolicy?.writeScopes ?? []),
  }, agent);
}

export function toolGovernanceDraftFromAgent(agent: AgentConfigWorkspaceAgent | null | undefined): AgentToolGovernanceDraft {
  return {
    proposedByAgentId: agent?.agentId ?? "",
    reason: "",
    applyMode: "auto",
  };
}

export function toolPolicyDraftEqualsAgent(draft: AgentToolPolicyDraft, agent: AgentConfigWorkspaceAgent | null | undefined) {
  const base = toolPolicyDraftFromAgent(agent);
  return (
    sameStringSet(draft.allowedTools, base.allowedTools)
    && sameStringSet(draft.preferredTools, base.preferredTools)
    && sameStringSet(draft.blockedTools, base.blockedTools)
    && sameStringSet(draft.readScopes, base.readScopes)
    && sameStringSet(draft.writeScopes, base.writeScopes)
  );
}

export function toolPolicyDraftEqualsDraft(left: AgentToolPolicyDraft, right: AgentToolPolicyDraft) {
  return (
    sameStringSet(left.allowedTools, right.allowedTools)
    && sameStringSet(left.preferredTools, right.preferredTools)
    && sameStringSet(left.blockedTools, right.blockedTools)
    && sameStringSet(left.readScopes, right.readScopes)
    && sameStringSet(left.writeScopes, right.writeScopes)
  );
}

export function toolPolicyDeltaFromDraft(draft: AgentToolPolicyDraft, agent: AgentConfigWorkspaceAgent | null | undefined) {
  const base = toolPolicyDraftFromAgent(agent);
  return {
    grantTools: draft.allowedTools.filter((tool) => !base.allowedTools.includes(tool)),
    revokeTools: base.allowedTools.filter((tool) => !draft.allowedTools.includes(tool)),
    blockTools: draft.blockedTools.filter((tool) => !base.blockedTools.includes(tool)),
    unblockTools: base.blockedTools.filter((tool) => !draft.blockedTools.includes(tool)),
  };
}

export function toolPolicyDeltaCount(delta: ReturnType<typeof toolPolicyDeltaFromDraft>) {
  return delta.grantTools.length + delta.revokeTools.length + delta.blockTools.length + delta.unblockTools.length;
}

export function toolPolicyMode(draft: AgentToolPolicyDraft, toolName: string): ToolPolicyMode {
  if (draft.blockedTools.includes(toolName)) {
    return "blocked";
  }
  if (draft.allowedTools.includes(toolName)) {
    return "allowed";
  }
  if (draft.allowedTools.length > 0) {
    return "excluded";
  }
  return "inherited";
}

export function toolPolicyModeLabel(mode: ToolPolicyMode, lang: "zh" | "en") {
  const zh = {
    inherited: "未允许",
    allowed: "允许",
    blocked: "禁用",
    excluded: "未列入",
  };
  const en = {
    inherited: "Not allowed",
    allowed: "Allowed",
    blocked: "Blocked",
    excluded: "Excluded",
  };
  return (lang === "zh" ? zh : en)[mode];
}

export function toolCategoryLabel(category: string, fallback: string | undefined, lang: "zh" | "en") {
  const normalized = String(category || "").trim();
  const zh: Record<string, string> = {
    workspace_read: "工作区读取",
    workspace_write: "工作区保存",
    code_quality: "代码质量",
    web_research: "网络与检索",
    git_evolution: "Git 与进化",
    task_runtime: "任务运行",
    agent_collaboration: "Agent 协作",
    memory_context: "记忆与上下文",
    self_model: "自我模型",
    media_research: "媒体与科研",
    custom_generated: "自定义工具",
    uncategorized: "未分类",
  };
  const en: Record<string, string> = {
    workspace_read: "Workspace read",
    workspace_write: "Workspace write",
    code_quality: "Code quality",
    web_research: "Web and research",
    git_evolution: "Git and evolution",
    task_runtime: "Task runtime",
    agent_collaboration: "Agent collaboration",
    memory_context: "Memory and context",
    self_model: "Self model",
    media_research: "Media and research",
    custom_generated: "Custom tools",
    uncategorized: "Uncategorized",
  };
  return ((lang === "zh" ? zh : en)[normalized] ?? fallback ?? normalized) || (lang === "zh" ? "未分类" : "Uncategorized");
}

export function toolTierLabel(tier: string, lang: "zh" | "en") {
  const normalized = String(tier || "").trim();
  const zh: Record<string, string> = {
    low: "低风险",
    medium: "中风险",
    high: "高风险",
    generated: "自定义",
  };
  const en: Record<string, string> = {
    low: "Low risk",
    medium: "Medium risk",
    high: "High risk",
    generated: "Generated",
  };
  return ((lang === "zh" ? zh : en)[normalized] ?? normalized) || "-";
}

export function fallbackToolBundleLabel(lang: "zh" | "en") {
  return lang === "zh" ? "未归入工具包" : "Unbundled tools";
}

export function groupPolicyToolsByBundle(
  tools: ToolRegistryItem[],
  bundles: ToolBundle[],
  draft: AgentToolPolicyDraft,
  lang: "zh" | "en",
): ToolPermissionGroup[] {
  const toolByName = new Map(tools.map((tool) => [tool.name, tool]));
  const groups: ToolPermissionGroup[] = [];
  const pushedToolKeys = new Set<string>();

  const pushTool = (group: ToolPermissionGroup, tool: ToolRegistryItem) => {
    const mode = toolPolicyMode(draft, tool.name);
    group.tools.push(tool);
    if (mode === "allowed") {
      group.allowedCount += 1;
    } else if (mode === "blocked") {
      group.blockedCount += 1;
    } else {
      group.inheritedCount += 1;
    }
    if (tool.permissionTier === "high" || tool.permissionPolicy?.requiresExplicitAllow) {
      group.highRiskCount += 1;
    }
  };

  for (const bundle of bundles) {
    const group: ToolPermissionGroup = {
      bundleId: bundle.bundleId,
      label: bundle.label,
      description: bundle.description,
      category: bundle.category,
      tools: [],
      allowedCount: 0,
      blockedCount: 0,
      inheritedCount: 0,
      highRiskCount: 0,
    };
    for (const toolName of bundle.toolNames) {
      const tool = toolByName.get(toolName);
      if (!tool) {
        continue;
      }
      pushedToolKeys.add(tool.name);
      pushTool(group, tool);
    }
    if (group.tools.length) {
      groups.push(group);
    }
  }

  const unbundled: ToolPermissionGroup = {
    bundleId: "unbundled",
    label: fallbackToolBundleLabel(lang),
    description: lang === "zh" ? "这些工具暂未归入任何工具包，建议单独审查后再授权。" : "Tools not yet assigned to a package. Review them individually before allowing them.",
    category: "unbundled",
    tools: [],
    allowedCount: 0,
    blockedCount: 0,
    inheritedCount: 0,
    highRiskCount: 0,
  };
  for (const tool of tools) {
    if (!pushedToolKeys.has(tool.name)) {
      pushTool(unbundled, tool);
    }
  }
  if (unbundled.tools.length) {
    groups.push(unbundled);
  }

  return groups.sort((left, right) => {
    const leftTouched = left.allowedCount + left.blockedCount;
    const rightTouched = right.allowedCount + right.blockedCount;
    if (leftTouched !== rightTouched) {
      return rightTouched - leftTouched;
    }
    return left.label.localeCompare(right.label);
  });
}

export function defaultMemoryPolicy(policyId = ""): MemoryPolicy {
  return {
    policyId,
    privateMemoryRoot: "",
    episodicEventsPath: "",
    groupContextEventsPath: "",
    agentInboxMessagesPath: "",
    toolObservationsPath: "",
    summariesPath: "",
    readSharedGroups: [],
    writeSharedGroups: [],
    readKnowledgeBaseIds: [],
    proposeKnowledgeBaseIds: [],
    reviewKnowledgeBaseIds: [],
    rateKnowledgeBaseIds: [],
  };
}

export function memoryPolicyDraftFromAgent(agent: AgentConfigWorkspaceAgent | null | undefined): AgentMemoryPolicyDraft {
  return {
    readSharedGroups: sortedIds(agent?.memoryPolicy?.readSharedGroups ?? []),
    writeSharedGroups: sortedIds(agent?.memoryPolicy?.writeSharedGroups ?? []),
    readKnowledgeBaseIds: sortedIds(agent?.memoryPolicy?.readKnowledgeBaseIds ?? []),
    proposeKnowledgeBaseIds: sortedIds(agent?.memoryPolicy?.proposeKnowledgeBaseIds ?? []),
    reviewKnowledgeBaseIds: sortedIds(agent?.memoryPolicy?.reviewKnowledgeBaseIds ?? []),
    rateKnowledgeBaseIds: sortedIds(agent?.memoryPolicy?.rateKnowledgeBaseIds ?? []),
    newReadGroup: "",
    newWriteGroup: "",
    newReadKnowledgeBaseId: "",
    newProposeKnowledgeBaseId: "",
    newReviewKnowledgeBaseId: "",
    newRateKnowledgeBaseId: "",
  };
}

export function memoryPolicyDraftEqualsAgent(draft: AgentMemoryPolicyDraft, agent: AgentConfigWorkspaceAgent | null | undefined) {
  const base = memoryPolicyDraftFromAgent(agent);
  return (
    sameStringSet(draft.readSharedGroups, base.readSharedGroups)
    && sameStringSet(draft.writeSharedGroups, base.writeSharedGroups)
    && sameStringSet(draft.readKnowledgeBaseIds, base.readKnowledgeBaseIds)
    && sameStringSet(draft.proposeKnowledgeBaseIds, base.proposeKnowledgeBaseIds)
    && sameStringSet(draft.reviewKnowledgeBaseIds, base.reviewKnowledgeBaseIds)
    && sameStringSet(draft.rateKnowledgeBaseIds, base.rateKnowledgeBaseIds)
  );
}

export function memoryPolicyDraftEqualsDraft(left: AgentMemoryPolicyDraft, right: AgentMemoryPolicyDraft) {
  return (
    sameStringSet(left.readSharedGroups, right.readSharedGroups)
    && sameStringSet(left.writeSharedGroups, right.writeSharedGroups)
    && sameStringSet(left.readKnowledgeBaseIds, right.readKnowledgeBaseIds)
    && sameStringSet(left.proposeKnowledgeBaseIds, right.proposeKnowledgeBaseIds)
    && sameStringSet(left.reviewKnowledgeBaseIds, right.reviewKnowledgeBaseIds)
    && sameStringSet(left.rateKnowledgeBaseIds, right.rateKnowledgeBaseIds)
  );
}

export function sharedGroupCandidates(workspace: AgentConfigWorkspace | undefined, selectedAgent: AgentConfigWorkspaceAgent | null | undefined) {
  const values = new Set<string>();
  for (const agent of workspace?.agents ?? []) {
    for (const group of agent.memoryPolicy?.readSharedGroups ?? []) {
      values.add(group);
    }
    for (const group of agent.memoryPolicy?.writeSharedGroups ?? []) {
      values.add(group);
    }
  }
  if (selectedAgent) {
    for (const mode of uniqueModes(selectedAgent)) {
      values.add(mode);
    }
  }
  values.add("project");
  values.add("research");
  values.add("group_chat");
  values.add("supervised_evolution");
  values.add("self_evolution");
  return sortedIds(Array.from(values));
}

export function clampNumber(value: unknown, minimum: number, maximum: number, fallback: number) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return fallback;
  }
  return Math.max(minimum, Math.min(maximum, Math.trunc(parsed)));
}

export function delegationPolicyDraftFromAgent(agent: AgentConfigWorkspaceAgent | null | undefined): AgentDelegationPolicyDraft {
  const policy = agent?.metadata?.delegationPolicy;
  const allowedModes = sortedIds((policy?.allowedContextModes ?? []).filter((mode) => mode === "isolated" || mode === "fork"));
  return {
    allowSubagents: Boolean(policy?.allowSubagents),
    maxConcurrent: clampNumber(policy?.maxConcurrent, 0, 8, 0),
    maxDepth: clampNumber(policy?.maxDepth, 0, 4, 0),
    allowWakeMessages: policy?.allowWakeMessages !== false,
    allowedContextModes: allowedModes.length ? allowedModes : ["isolated"],
  };
}

export function delegationPolicyDraftEqualsAgent(draft: AgentDelegationPolicyDraft, agent: AgentConfigWorkspaceAgent | null | undefined) {
  const base = delegationPolicyDraftFromAgent(agent);
  return (
    draft.allowSubagents === base.allowSubagents &&
    draft.maxConcurrent === base.maxConcurrent &&
    draft.maxDepth === base.maxDepth &&
    draft.allowWakeMessages === base.allowWakeMessages &&
    sameStringSet(draft.allowedContextModes, base.allowedContextModes)
  );
}

export function supervisionPolicyDraftFromAgent(agent: AgentConfigWorkspaceAgent | null | undefined): AgentSupervisionPolicyDraft {
  const policy = agent?.metadata?.supervisionPolicy;
  const reviewMode = ["advisory", "required", "disabled"].includes(String(policy?.reviewMode ?? ""))
    ? String(policy?.reviewMode)
    : "advisory";
  const evidenceLevel = ["light", "standard", "strict"].includes(String(policy?.evidenceLevel ?? ""))
    ? String(policy?.evidenceLevel)
    : "standard";
  return {
    supervisionEnabled: Boolean(policy?.supervisionEnabled),
    requiresReview: reviewMode === "required" ? true : reviewMode === "disabled" ? false : Boolean(policy?.requiresReview),
    reviewMode,
    evidenceLevel,
  };
}

export function supervisionPolicyDraftEqualsAgent(draft: AgentSupervisionPolicyDraft, agent: AgentConfigWorkspaceAgent | null | undefined) {
  const base = supervisionPolicyDraftFromAgent(agent);
  return (
    draft.supervisionEnabled === base.supervisionEnabled &&
    draft.requiresReview === base.requiresReview &&
    draft.reviewMode === base.reviewMode &&
    draft.evidenceLevel === base.evidenceLevel
  );
}

export function delegationPolicyDraftEqualsDraft(left: AgentDelegationPolicyDraft, right: AgentDelegationPolicyDraft) {
  return (
    left.allowSubagents === right.allowSubagents &&
    left.maxConcurrent === right.maxConcurrent &&
    left.maxDepth === right.maxDepth &&
    left.allowWakeMessages === right.allowWakeMessages &&
    sameStringSet(left.allowedContextModes, right.allowedContextModes)
  );
}

export function supervisionPolicyDraftEqualsDraft(left: AgentSupervisionPolicyDraft, right: AgentSupervisionPolicyDraft) {
  return (
    left.supervisionEnabled === right.supervisionEnabled &&
    left.requiresReview === right.requiresReview &&
    left.reviewMode === right.reviewMode &&
    left.evidenceLevel === right.evidenceLevel
  );
}
