/**
 * Agents config/persona/task draft mappers (structure M1).
 * Pure: no React hooks / Query / DOM.
 */
import type {
  AgentConfigWorkspaceAgent,
  AgentContextCompressionPolicy,
  AgentPersonaProfile,
  AgentTaskProfile,
} from "../../api/types";
import type { AgentContextCompressionPolicyDraft } from "../AgentContextCompressionPanel";
import type { AgentConfigDraft } from "../AgentCoreConfigPanel";
import type { AgentPersonaDraft } from "../AgentPersonaProfilePanel";
import type { AgentTaskDraft } from "../AgentTaskProfilePanel";
import {
  agentReasoningEffortBySlot,
  normalizeAgentLlmBindings,
  normalizeAgentReasoningEffortBySlot,
  sameAgentLlmBindings,
  sameAgentReasoningEffortBySlot,
} from "./agentRouteLlmModel";

export type AgentToolPolicyDraft = {
  allowedTools: string[];
  preferredTools: string[];
  blockedTools: string[];
  readScopes: string[];
  writeScopes: string[];
};

export const DEFAULT_AGENT_CONTEXT_COMPRESSION_DRAFT: AgentContextCompressionPolicyDraft = {
  mode: "inherit",
  enabled: true,
  maxTokenLimit: "16000",
  maxCompressionsPerSession: "20",
  lightThreshold: "60",
  standardThreshold: "80",
  deepThreshold: "90",
  emergencyThreshold: "95",
  lightSummaryChars: "500",
  standardSummaryChars: "1000",
  deepSummaryChars: "2000",
  emergencySummaryChars: "3000",
  keepAiMessages: "5",
  preserveErrors: true,
  extractKeyDecisions: true,
};

export function sortedIds(values: string[]) {
  return Array.from(new Set(values.map((item) => String(item || "").trim()).filter(Boolean))).sort();
}

export function sameStringSet(left: string[], right: string[]) {
  const leftSorted = sortedIds(left);
  const rightSorted = sortedIds(right);
  return leftSorted.length === rightSorted.length && leftSorted.every((value, index) => value === rightSorted[index]);
}


export function numericText(value: unknown, fallback: number) {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? String(Math.round(parsed)) : String(fallback);
}

export function percentText(value: unknown, fallbackRatio: number) {
  const parsed = typeof value === "number" ? value : Number(value);
  const ratio = Number.isFinite(parsed) ? parsed : fallbackRatio;
  return String(Math.round(Math.max(0, Math.min(1, ratio)) * 100));
}

export function percentToRatio(value: string, fallback: number) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.max(0, Math.min(1, parsed / 100)) : fallback;
}

export function positiveIntegerFromText(value: string, fallback: number) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.max(0, Math.round(parsed)) : fallback;
}

export function contextCompressionDraftFromAgent(agent: AgentConfigWorkspaceAgent | null | undefined): AgentContextCompressionPolicyDraft {
  const stored = agent?.contextCompressionPolicy;
  const effective = agent?.contextCompressionEffectivePolicy;
  const source: AgentContextCompressionPolicy | undefined = stored?.mode === "custom" ? stored : effective;
  const levels = source?.levels ?? effective?.levels ?? {};
  const summaryChars = source?.summaryChars ?? effective?.summaryChars ?? {};
  const preservation = source?.preservation ?? effective?.preservation ?? {};
  const defaults = DEFAULT_AGENT_CONTEXT_COMPRESSION_DRAFT;
  return {
    mode: stored?.mode === "custom" ? "custom" : "inherit",
    enabled: source?.enabled ?? effective?.enabled ?? defaults.enabled,
    maxTokenLimit: numericText(source?.maxTokenLimit ?? effective?.effectiveTokenLimit, Number(defaults.maxTokenLimit)),
    maxCompressionsPerSession: numericText(
      source?.maxCompressionsPerSession ?? effective?.maxCompressionsPerSession,
      Number(defaults.maxCompressionsPerSession),
    ),
    lightThreshold: percentText(levels.light, 0.6),
    standardThreshold: percentText(levels.standard, 0.8),
    deepThreshold: percentText(levels.deep, 0.9),
    emergencyThreshold: percentText(levels.emergency, 0.95),
    lightSummaryChars: numericText(summaryChars.light, Number(defaults.lightSummaryChars)),
    standardSummaryChars: numericText(summaryChars.standard, Number(defaults.standardSummaryChars)),
    deepSummaryChars: numericText(summaryChars.deep, Number(defaults.deepSummaryChars)),
    emergencySummaryChars: numericText(summaryChars.emergency, Number(defaults.emergencySummaryChars)),
    keepAiMessages: numericText(preservation.keepAiMessages, Number(defaults.keepAiMessages)),
    preserveErrors: preservation.preserveErrors ?? defaults.preserveErrors,
    extractKeyDecisions: preservation.extractKeyDecisions ?? defaults.extractKeyDecisions,
  };
}

export function contextCompressionPolicyFromDraft(draft: AgentContextCompressionPolicyDraft): AgentContextCompressionPolicy {
  if (draft.mode !== "custom") {
    return { mode: "inherit" };
  }
  return {
    mode: "custom",
    enabled: draft.enabled,
    maxTokenLimit: positiveIntegerFromText(draft.maxTokenLimit, Number(DEFAULT_AGENT_CONTEXT_COMPRESSION_DRAFT.maxTokenLimit)),
    maxCompressionsPerSession: positiveIntegerFromText(
      draft.maxCompressionsPerSession,
      Number(DEFAULT_AGENT_CONTEXT_COMPRESSION_DRAFT.maxCompressionsPerSession),
    ),
    levels: {
      light: percentToRatio(draft.lightThreshold, 0.6),
      standard: percentToRatio(draft.standardThreshold, 0.8),
      deep: percentToRatio(draft.deepThreshold, 0.9),
      emergency: percentToRatio(draft.emergencyThreshold, 0.95),
    },
    summaryChars: {
      light: positiveIntegerFromText(draft.lightSummaryChars, Number(DEFAULT_AGENT_CONTEXT_COMPRESSION_DRAFT.lightSummaryChars)),
      standard: positiveIntegerFromText(draft.standardSummaryChars, Number(DEFAULT_AGENT_CONTEXT_COMPRESSION_DRAFT.standardSummaryChars)),
      deep: positiveIntegerFromText(draft.deepSummaryChars, Number(DEFAULT_AGENT_CONTEXT_COMPRESSION_DRAFT.deepSummaryChars)),
      emergency: positiveIntegerFromText(draft.emergencySummaryChars, Number(DEFAULT_AGENT_CONTEXT_COMPRESSION_DRAFT.emergencySummaryChars)),
    },
    preservation: {
      keepAiMessages: positiveIntegerFromText(draft.keepAiMessages, Number(DEFAULT_AGENT_CONTEXT_COMPRESSION_DRAFT.keepAiMessages)),
      preserveErrors: draft.preserveErrors,
      extractKeyDecisions: draft.extractKeyDecisions,
    },
  };
}

export function contextCompressionDraftEqualsDraft(left: AgentContextCompressionPolicyDraft, right: AgentContextCompressionPolicyDraft) {
  return JSON.stringify(contextCompressionPolicyFromDraft(left)) === JSON.stringify(contextCompressionPolicyFromDraft(right));
}

export function draftFromAgent(agent: AgentConfigWorkspaceAgent | null | undefined): AgentConfigDraft {
  return {
    displayName: agent?.displayName ?? "",
    llmBindings: normalizeAgentLlmBindings(agent?.llmBindings),
    reasoningEffortBySlot: agentReasoningEffortBySlot(agent),
    promptTemplateId: agent?.promptTemplateId ?? "",
    toolPolicyId: agent?.toolPolicyId ?? "",
    memoryPolicyId: agent?.memoryPolicyId ?? "",
    contextCompressionPolicy: contextCompressionDraftFromAgent(agent),
    status: agent?.status ?? "active",
  };
}

export function configChangeSnapshotFromDraft(draft: AgentConfigDraft): Record<string, unknown> {
  return {
    displayName: draft.displayName,
    llmBindings: normalizeAgentLlmBindings(draft.llmBindings),
    reasoningEffortBySlot: normalizeAgentReasoningEffortBySlot(draft.reasoningEffortBySlot),
    promptTemplateId: draft.promptTemplateId,
    toolPolicyId: draft.toolPolicyId,
    memoryPolicyId: draft.memoryPolicyId,
    contextCompressionPolicy: contextCompressionPolicyFromDraft(draft.contextCompressionPolicy),
    status: draft.status,
  };
}

export function draftEqualsAgent(draft: AgentConfigDraft, agent: AgentConfigWorkspaceAgent | null | undefined) {
  if (!agent) {
    return true;
  }
  const base = draftFromAgent(agent);
  return (
    draft.displayName === base.displayName
    && sameAgentLlmBindings(draft.llmBindings, base.llmBindings)
    && sameAgentReasoningEffortBySlot(draft.reasoningEffortBySlot, base.reasoningEffortBySlot)
    && draft.promptTemplateId === base.promptTemplateId
    && draft.toolPolicyId === base.toolPolicyId
    && draft.memoryPolicyId === base.memoryPolicyId
    && contextCompressionDraftEqualsDraft(draft.contextCompressionPolicy, base.contextCompressionPolicy)
    && draft.status === base.status
  );
}

export function defaultPersonaProfile(): AgentPersonaProfile {
  return {
    gender: "",
    age: "",
    pronouns: "",
    personality: "",
    communicationStyle: "",
    background: "",
    expertise: [],
    collaborationPreference: "",
    identityNotes: "",
  };
}

export function normalizePersonaProfile(profile: Partial<AgentPersonaProfile> | null | undefined): AgentPersonaProfile {
  const base = defaultPersonaProfile();
  return {
    ...base,
    ...(profile ?? {}),
    gender: String(profile?.gender ?? "").trim(),
    age: String(profile?.age ?? "").trim(),
    pronouns: String(profile?.pronouns ?? "").trim(),
    personality: String(profile?.personality ?? "").trim(),
    communicationStyle: String(profile?.communicationStyle ?? "").trim(),
    background: String(profile?.background ?? "").trim(),
    expertise: sortedIds((profile?.expertise ?? []).map((item) => String(item || "").trim()).filter(Boolean)),
    collaborationPreference: String(profile?.collaborationPreference ?? "").trim(),
    identityNotes: String(profile?.identityNotes ?? "").trim(),
  };
}

export function personaDraftFromAgent(agent: AgentConfigWorkspaceAgent | null | undefined): AgentPersonaDraft {
  const profile = normalizePersonaProfile(agent?.personaProfile);
  return {
    ...profile,
    expertise: profile.expertise.join(", "),
  };
}

export function expertiseFromDraft(value: string) {
  return sortedIds(String(value || "").split(/[,，;；\n]+/).map((item) => item.trim()).filter(Boolean));
}

export function personaProfileFromDraft(draft: AgentPersonaDraft): AgentPersonaProfile {
  return normalizePersonaProfile({
    ...draft,
    expertise: expertiseFromDraft(draft.expertise),
  });
}

export function personaDraftEqualsAgent(draft: AgentPersonaDraft, agent: AgentConfigWorkspaceAgent | null | undefined) {
  const current = normalizePersonaProfile(agent?.personaProfile);
  const next = personaProfileFromDraft(draft);
  return (
    current.gender === next.gender
    && current.age === next.age
    && current.pronouns === next.pronouns
    && current.personality === next.personality
    && current.communicationStyle === next.communicationStyle
    && current.background === next.background
    && sameStringSet(current.expertise, next.expertise)
    && current.collaborationPreference === next.collaborationPreference
    && current.identityNotes === next.identityNotes
  );
}

export function personaProfileSummary(agent: AgentConfigWorkspaceAgent | null | undefined, lang: "zh" | "en") {
  const profile = normalizePersonaProfile(agent?.personaProfile);
  const parts = [profile.gender, profile.age, profile.personality].filter(Boolean);
  if (parts.length) {
    return parts.slice(0, 3).join(" / ");
  }
  return lang === "zh" ? "未设置人物档案" : "No persona profile";
}

export function defaultTaskProfile(): AgentTaskProfile {
  return {
    mission: "",
    taskTypes: [],
    responsibilities: "",
    preferredTasks: "",
    avoidTasks: "",
    successCriteria: "",
    deliverables: "",
    constraints: "",
    handoffNotes: "",
  };
}

export function normalizeTaskProfile(profile: Partial<AgentTaskProfile> | null | undefined): AgentTaskProfile {
  const base = defaultTaskProfile();
  return {
    ...base,
    ...(profile ?? {}),
    mission: String(profile?.mission ?? "").trim(),
    taskTypes: sortedIds((profile?.taskTypes ?? []).map((item) => String(item || "").trim()).filter(Boolean)),
    responsibilities: String(profile?.responsibilities ?? "").trim(),
    preferredTasks: String(profile?.preferredTasks ?? "").trim(),
    avoidTasks: String(profile?.avoidTasks ?? "").trim(),
    successCriteria: String(profile?.successCriteria ?? "").trim(),
    deliverables: String(profile?.deliverables ?? "").trim(),
    constraints: String(profile?.constraints ?? "").trim(),
    handoffNotes: String(profile?.handoffNotes ?? "").trim(),
  };
}

export function taskDraftFromAgent(agent: AgentConfigWorkspaceAgent | null | undefined): AgentTaskDraft {
  const profile = normalizeTaskProfile(agent?.taskProfile);
  return {
    ...profile,
    taskTypes: profile.taskTypes.join(", "),
  };
}

export function taskProfileFromDraft(draft: AgentTaskDraft): AgentTaskProfile {
  return normalizeTaskProfile({
    ...draft,
    taskTypes: expertiseFromDraft(draft.taskTypes),
  });
}

export function taskDraftEqualsAgent(draft: AgentTaskDraft, agent: AgentConfigWorkspaceAgent | null | undefined) {
  const current = normalizeTaskProfile(agent?.taskProfile);
  const next = taskProfileFromDraft(draft);
  return (
    current.mission === next.mission
    && sameStringSet(current.taskTypes, next.taskTypes)
    && current.responsibilities === next.responsibilities
    && current.preferredTasks === next.preferredTasks
    && current.avoidTasks === next.avoidTasks
    && current.successCriteria === next.successCriteria
    && current.deliverables === next.deliverables
    && current.constraints === next.constraints
    && current.handoffNotes === next.handoffNotes
  );
}

export function taskProfileSummary(agent: AgentConfigWorkspaceAgent | null | undefined, lang: "zh" | "en") {
  const profile = normalizeTaskProfile(agent?.taskProfile);
  const parts = [profile.mission, profile.preferredTasks, profile.successCriteria].filter(Boolean);
  if (parts.length) {
    return parts[0];
  }
  return lang === "zh" ? "未设置任务档案" : "No task profile";
}

export function hasPersonaProfile(agent: AgentConfigWorkspaceAgent | null | undefined) {
  const profile = normalizePersonaProfile(agent?.personaProfile);
  return Boolean(
    profile.gender
      || profile.age
      || profile.pronouns
      || profile.personality
      || profile.communicationStyle
      || profile.background
      || profile.expertise.length
      || profile.collaborationPreference
      || profile.identityNotes,
  );
}

export function hasTaskProfile(agent: AgentConfigWorkspaceAgent | null | undefined) {
  const profile = normalizeTaskProfile(agent?.taskProfile);
  return Boolean(
    profile.mission
      || profile.taskTypes.length
      || profile.responsibilities
      || profile.preferredTasks
      || profile.avoidTasks
      || profile.successCriteria
      || profile.deliverables
      || profile.constraints
      || profile.handoffNotes,
  );
}

export function hasToolPolicyConfiguration(agent: AgentConfigWorkspaceAgent | null | undefined) {
  const policy = agent?.toolPolicy;
  return Boolean(
    policy?.allowedTools?.length
      || policy?.preferredTools?.length
      || policy?.blockedTools?.length,
  );
}

export function agentBoundaryType(agent: AgentConfigWorkspaceAgent | null | undefined) {
  return String(agent?.agentBoundary?.type || (agent?.status === "archived" ? "archived" : "")).trim();
}

export function isWorkSessionAgent(agent: AgentConfigWorkspaceAgent | null | undefined) {
  return agentBoundaryType(agent) === "work_session";
}

export function normalizeToolPolicyDraftForAgent(
  draft: AgentToolPolicyDraft,
  _agent: AgentConfigWorkspaceAgent | null | undefined,
): AgentToolPolicyDraft {
  const blocked = new Set(sortedIds(draft.blockedTools));
  const allowed = new Set(sortedIds(draft.allowedTools).filter((tool) => !blocked.has(tool)));
  const preferred = new Set(sortedIds(draft.preferredTools));
  const allowedTools = sortedIds(Array.from(allowed));
  const allowedSet = new Set(allowedTools);
  return {
    ...draft,
    allowedTools,
    preferredTools: sortedIds(Array.from(preferred).filter((tool) => allowedSet.has(tool))),
    blockedTools: sortedIds(Array.from(blocked)),
    readScopes: sortedIds(draft.readScopes),
    writeScopes: sortedIds(draft.writeScopes),
  };
}

export function requiresPersonaProfile(agent: AgentConfigWorkspaceAgent | null | undefined) {
  return agent?.agentBoundary?.requiresPersonaProfile === "true";
}

export function requiresTaskProfile(agent: AgentConfigWorkspaceAgent | null | undefined) {
  return agent?.agentBoundary?.requiresTaskProfile === "true";
}

export function requiresTeamMembership(agent: AgentConfigWorkspaceAgent | null | undefined) {
  return agent?.agentBoundary?.requiresTeamMembership === "true";
}

export function hasModelAndPromptConfiguration(agent: AgentConfigWorkspaceAgent | null | undefined) {
  return Boolean(agent?.llmBindings?.dialogue?.modelId && agent.promptTemplateId);
}

export function hasWorkspaceConfiguration(agent: AgentConfigWorkspaceAgent | null | undefined) {
  return Boolean(agent?.workspacePath || agent?.workspaceTerritory?.privateRoot);
}

export function agentHasTeamReference(agent: AgentConfigWorkspaceAgent | null | undefined) {
  return Boolean(agent?.references?.some((reference) => reference.kind === "team"));
}
