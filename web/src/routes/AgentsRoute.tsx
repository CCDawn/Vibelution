import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Archive,
  ArrowLeft,
  Bot,
  Brain,
  CheckSquare,
  CheckCircle2,
  Database,
  FolderTree,
  Layers3,
  MessageSquare,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  Square,
  ExternalLink,
  Trash2,
  UserRound,
  Users,
  Wrench,
} from "lucide-react";
import { type MouseEvent, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import {
  AgentDelegationPolicy,
  AgentInboxMessage,
  AgentAvatarOptionsPayload,
  AgentAvatarUploadResponse,
  AgentRuntimeEvidence,
  AgentRuntimeEvidenceMatch,
  AgentRunHistory,
  AgentConfigHealthIssue,
  AgentModeBindings,
  AgentPersonaProfile,
  AgentTaskProfile,
  AgentToolGovernanceRequest,
  AgentConfigReference,
  AgentSupervisionPolicy,
  AgentBoundary,
  AgentConfigWorkspace,
  AgentConfigWorkspaceAgent,
  AgentConfigWorkspaceGroup,
  AgentContextCompressionPolicy,
  AgentLlmBindings,
  AgentLlmSlotDefinition,
  AgentModelChoice,
  MemoryPolicy,
  ToolPolicy,
  ToolBundle,
  ToolRegistryItem,
  ToolRegistryPayload,
} from "../api/types";
import { resolvePollingInterval, usePageVisibility } from "../app/pollingPolicy";
import { useShellI18n } from "../i18n/useShellI18n";
import { AgentManagementNav } from "./AgentManagementNav";
import { agentCenterToolsRoute } from "./agentCenterRoutes";
import { agentDisplayInfo } from "./agentDisplay";
import { createChatWorkspaceCache } from "./chatWorkspaceCache";
import styles from "./AgentsRoute.module.css";

type FilterId = string;

type AgentConfigDraft = {
  displayName: string;
  llmBindings: AgentLlmBindings;
  reasoningEffortBySlot: Record<string, string>;
  promptTemplateId: string;
  toolPolicyId: string;
  memoryPolicyId: string;
  contextCompressionPolicy: AgentContextCompressionPolicyDraft;
  status: string;
};

type AgentContextCompressionPolicyDraft = {
  mode: "inherit" | "custom";
  enabled: boolean;
  maxTokenLimit: string;
  maxCompressionsPerSession: string;
  lightThreshold: string;
  standardThreshold: string;
  deepThreshold: string;
  emergencyThreshold: string;
  lightSummaryChars: string;
  standardSummaryChars: string;
  deepSummaryChars: string;
  emergencySummaryChars: string;
  keepAiMessages: string;
  preserveErrors: boolean;
  extractKeyDecisions: boolean;
};

type AgentPersonaDraft = Omit<AgentPersonaProfile, "expertise"> & {
  expertise: string;
};

type AgentTaskDraft = Omit<AgentTaskProfile, "taskTypes"> & {
  taskTypes: string;
};

type AgentCreateDraft = {
  displayName: string;
  llmBindings: AgentLlmBindings;
  primaryMode: string;
  roleKey: string;
  promptTemplateId: string;
  personaSummary: string;
  taskMission: string;
  selectedToolBundleIds: string[];
  allowedTools: string;
};

type AgentModeMembershipDraft = {
  chatDefault: boolean;
  chatAvailable: boolean;
  researchPool: boolean;
  supervisedSlot: string;
  selfEvolutionSlot: string;
};

type AgentToolPolicyDraft = {
  allowedTools: string[];
  preferredTools: string[];
  blockedTools: string[];
  readScopes: string[];
  writeScopes: string[];
};

type AgentToolGovernanceDraft = {
  proposedByAgentId: string;
  reason: string;
  applyMode: "auto" | "review";
};

type AgentMemoryPolicyDraft = {
  readSharedGroups: string[];
  writeSharedGroups: string[];
  readKnowledgeBaseIds: string[];
  proposeKnowledgeBaseIds: string[];
  reviewKnowledgeBaseIds: string[];
  rateKnowledgeBaseIds: string[];
  newReadGroup: string;
  newWriteGroup: string;
  newReadKnowledgeBaseId: string;
  newProposeKnowledgeBaseId: string;
  newReviewKnowledgeBaseId: string;
  newRateKnowledgeBaseId: string;
};

type AgentResetOptions = {
  clearRuntimeState: boolean;
  resetDirectSession: boolean;
  resetPersonaProfile: boolean;
  resetTaskProfile: boolean;
  resetToolPolicy: boolean;
  resetMemoryPolicy: boolean;
  resetRuntimePolicy: boolean;
};

type AgentDelegationPolicyDraft = AgentDelegationPolicy;
type AgentSupervisionPolicyDraft = AgentSupervisionPolicy;

type AgentDraftSyncSource = {
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

type ToolPolicyMode = "inherited" | "allowed" | "blocked" | "excluded";
type AgentConfigPaneId = "overview" | "config" | "activity";
type ToolPermissionGroup = {
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
type ToolBundleApplyMode = "merge" | "replace";
type AgentManagementAction = {
  id: string;
  label: string;
  detail: string;
  pane: AgentConfigPaneId;
  route?: string;
};
type AgentManagementBrief = {
  score: number;
  completed: number;
  total: number;
  statusLabel: string;
  statusDetail: string;
  items: Array<{
    id: string;
    label: string;
    complete: boolean;
    pane: AgentConfigPaneId;
  }>;
  actions: AgentManagementAction[];
};
type AgentCapabilityPreview = {
  effectiveAllowed: number;
  preferred: number;
  blocked: number;
  inherited: number;
  highRiskAllowed: number;
  explicitAllowed: number;
  writeBoundaryLabel: string;
};
type AgentManagementFilterGroup = {
  id: string;
  label: string;
  count: number;
  description?: string;
  healthCount?: number;
};
type AgentTeamIndexGroup = AgentManagementFilterGroup & {
  section: "team_index" | "source_scope";
  agentIds: string[];
  teamId?: string;
  teamKind?: string;
  teamCategory?: string;
  sourceScopeGroupId?: string;
  sourceCount?: number;
  enabledByDefault?: boolean;
  evidenceRole?: string;
  source?: string;
};
type AgentFilterGroup = AgentConfigWorkspaceGroup | AgentTeamIndexGroup;
type AgentConfigWorkspaceWithTeamIndexes = AgentConfigWorkspace & {
  teamIndexes?: AgentTeamIndexGroup[];
};
type AgentActivityTimelineItem = {
  id: string;
  kind: "run" | "sub_run" | "inbox" | "context";
  title: string;
  body: string;
  meta: string;
  timestamp: string;
  sessionId: string;
  messageId: string;
  canOpenLogs: boolean;
  evidence: AgentRuntimeEvidenceMatch | null;
};
type AgentBulkActionItem = {
  agentId: string;
  reason?: string;
  message?: string;
  status?: string;
  deleted?: boolean;
  archiveSummary?: Record<string, unknown>;
  purgeSummary?: Record<string, unknown>;
};
type AgentBulkActionResponse = {
  status: string;
  requestedAgentIds: string[];
  success: AgentBulkActionItem[];
  skipped: AgentBulkActionItem[];
  failed: AgentBulkActionItem[];
  summary: {
    requestedCount: number;
    successCount: number;
    skippedCount: number;
    failedCount: number;
  };
  cleanupSummary?: Record<string, unknown>;
  timingsMs?: Record<string, number>;
  durationMs?: number;
};
type AgentBulkPromptTemplateResponse = Omit<AgentBulkActionResponse, "success"> & {
  success: AgentConfigWorkspaceAgent[];
  promptTemplateId?: string;
};
type AgentBulkConfigResponse = Omit<AgentBulkActionResponse, "success"> & {
  success: AgentConfigWorkspaceAgent[];
  appliedFields?: string[];
};
type AgentBulkConfigField = "dialogueModelId" | "promptTemplateId" | "primaryMode" | "roleKey";
type AgentBulkConfigDraft = Record<AgentBulkConfigField, string>;
type AgentBulkConfigApply = Record<AgentBulkConfigField, boolean>;
type ModelProfileChoice = {
  key: string;
  modelId: string;
  label: string;
  modelLabel: string;
  unresolved?: boolean;
};
type RuntimeFocusEvidenceResult = {
  match: AgentRuntimeEvidenceMatch | null;
  reason: "run" | "source_run" | "session" | "fallback" | "missing";
};

const AGENT_PRIMARY_MODE_OPTIONS = ["chat", "research", "supervised_evolution", "self_evolution", "general"];
const FALLBACK_AGENT_LLM_SLOTS: AgentLlmSlotDefinition[] = [
  {
    slot: "dialogue",
    label: "对话模型",
    description: "处理用户对话、工具规划和主回复生成。",
    required: true,
    requiresImageInput: false,
  },
  {
    slot: "mentalModel",
    label: "心智模型",
    description: "用于心智状态、长期偏好和自我解释相关推理。",
    required: false,
    requiresImageInput: false,
  },
  {
    slot: "summary",
    label: "摘要模型",
    description: "用于会话压缩、运行摘要和交接材料整理。",
    required: false,
    requiresImageInput: false,
  },
  {
    slot: "subagentPlanning",
    label: "子 Agent 规划",
    description: "用于拆解委派任务、确定子 Agent 目标和边界。",
    required: false,
    requiresImageInput: false,
  },
  {
    slot: "subagentExecution",
    label: "子 Agent 执行",
    description: "用于执行被委派的窄任务和返回结构化证据。",
    required: false,
    requiresImageInput: false,
  },
  {
    slot: "vision",
    label: "视觉理解",
    description: "用于图片输入、截图分析和多模态理解。",
    required: false,
    requiresImageInput: true,
  },
];
const EMPTY_TOOL_BUNDLES: ToolBundle[] = [];
const EMPTY_TOOL_REGISTRY_ITEMS: ToolRegistryItem[] = [];
const EMPTY_AGENT_CONFIG_GROUPS: AgentConfigWorkspaceGroup[] = [];
const LIGHTWEIGHT_AGENT_CONFIG_STORAGE = {
  agentRegistryPath: "workspace/agents/agents.json",
  modeBindingPath: "workspace/agent_config/mode_bindings.json",
  promptTemplatePath: "workspace/agent_config/prompt_templates.json",
};
const DEFAULT_AGENT_RESET_OPTIONS: AgentResetOptions = {
  clearRuntimeState: true,
  resetDirectSession: true,
  resetPersonaProfile: false,
  resetTaskProfile: false,
  resetToolPolicy: false,
  resetMemoryPolicy: false,
  resetRuntimePolicy: false,
};
const DEFAULT_AGENT_CONTEXT_COMPRESSION_DRAFT: AgentContextCompressionPolicyDraft = {
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
const DEFAULT_BULK_CONFIG_DRAFT: AgentBulkConfigDraft = {
  dialogueModelId: "",
  promptTemplateId: "",
  primaryMode: "",
  roleKey: "",
};
const DEFAULT_BULK_CONFIG_APPLY: AgentBulkConfigApply = {
  dialogueModelId: false,
  promptTemplateId: false,
  primaryMode: false,
  roleKey: false,
};
const DEFAULT_SESSION_AGENT_ALLOWED_TOOLS = [
  "grep_search_tool",
  "glob_tool",
  "read_file_tool",
  "get_core_context_tool",
  "get_current_goal_tool",
  "task_list_tool",
  "get_git_status_summary_tool",
  "get_recent_changes_tool",
  "conversation_log_inspect_tool",
];
const DEFAULT_SESSION_AGENT_PREFERRED_TOOLS = [
  "grep_search_tool",
  "read_file_tool",
  "conversation_log_inspect_tool",
  "get_core_context_tool",
];

function normalizeText(value: unknown) {
  return String(value ?? "").trim().toLowerCase();
}

function formatTimestamp(value: string, lang: "zh" | "en") {
  const text = String(value || "").trim();
  if (!text) {
    return "-";
  }
  const parsed = new Date(text);
  if (Number.isNaN(parsed.getTime())) {
    return text;
  }
  return new Intl.DateTimeFormat(lang === "zh" ? "zh-CN" : "en-US", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(parsed);
}

function timestampValue(value: string) {
  const parsed = new Date(String(value || ""));
  return Number.isNaN(parsed.getTime()) ? 0 : parsed.getTime();
}

function agentLabel(agent: AgentConfigWorkspaceAgent | null | undefined) {
  if (!agent) {
    return "-";
  }
  return agentDisplayInfo(agent, "zh").name || agent.agentId || "-";
}

function avatarInitials(agentCode?: string, name?: string, fallback = "AI") {
  const code = String(agentCode ?? "").trim();
  const numericTail = code.match(/\d{2,}$/)?.[0];
  if (numericTail) {
    return numericTail.slice(-2);
  }
  const compactCode = code.replace(/[^A-Za-z0-9]/g, "");
  if (compactCode && compactCode.length <= 3) {
    return compactCode.slice(0, 2).toUpperCase();
  }
  const title = String(name ?? "").trim();
  return title.slice(0, 2) || fallback;
}

function renderAgentAvatar(className: string, imageUrl: string | undefined, fallback: string) {
  return (
    <span className={className} aria-hidden="true">
      {imageUrl ? <img src={imageUrl} alt="" className={styles.agentAvatarImage} /> : fallback}
    </span>
  );
}

function encodeArrayBufferBase64(buffer: ArrayBuffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  bytes.forEach((byte) => {
    binary += String.fromCharCode(byte);
  });
  return btoa(binary);
}

function agentFunctionalLabel(agent: AgentConfigWorkspaceAgent | null | undefined, lang: "zh" | "en" = "zh") {
  if (!agent) {
    return "-";
  }
  return agentDisplayInfo(agent, lang).functionLabel || "-";
}

function agentFunctionTone(agent: AgentConfigWorkspaceAgent | null | undefined, lang: "zh" | "en") {
  return agentDisplayInfo(agent, lang).tone;
}

function agentSearchText(agent: AgentConfigWorkspaceAgent) {
  return normalizeText(
    [
      agent.agentId,
      agent.agentCode,
      agent.displayName,
      agent.primaryMode,
      agent.roleKey,
      Object.values(agent.llmBindings ?? {}).map((binding) => binding?.modelId).join(" "),
      agent.dialogueModel?.label,
      agent.dialogueModel?.model,
      agent.promptTemplateId,
      agent.toolPolicyId,
      agent.memoryPolicyId,
      agent.directSessionId,
      agent.workspacePath,
      agent.references.map((item) => `${item.kind} ${item.sourceLabel} ${item.mode} ${item.field}`).join(" "),
      agent.health.map((item) => `${item.code} ${item.title} ${item.detail}`).join(" "),
    ].join(" "),
  );
}

function promptTemplateDisplayName(
  template: { name?: string; promptTemplateId?: string; templateId?: string; category?: string } | null | undefined,
  fallbackId: string | undefined,
  lang: "zh" | "en",
) {
  const templateId = String(template?.promptTemplateId || template?.templateId || fallbackId || "").trim();
  const name = String(template?.name || "").trim();
  if (lang !== "zh") {
    return name || templateId || "-";
  }
  const normalized = (name || templateId).trim().toLowerCase();
  const zhNames: Record<string, string> = {
    "research capability steward": "科研能力管理员",
    "research organization advisor": "科研组织顾问",
    "research ceo": "科研负责人",
    "chat default": "会话默认",
    "supervised judge": "监督裁判",
    "supervised auditor": "监督审计员",
    "supervised reviewer": "监督评审员",
    "supervised candidate": "监督候选",
    "supervised baseline": "监督基线",
    "self-evolution executor": "自进化执行者",
    "self-evolution summarizer": "自进化总结者",
    "self-evolution reviewer": "自进化审查者",
  };
  return zhNames[normalized] ?? (name || templateId || "-");
}

function promptTemplateOptionLabel(
  template: { name?: string; promptTemplateId?: string; templateId?: string; category?: string },
  lang: "zh" | "en",
) {
  const id = String(template.promptTemplateId || template.templateId || "").trim();
  const category = String(template.category || "").trim();
  const name = promptTemplateDisplayName(template, id, lang);
  return category ? `${name} · ${category}` : name;
}

function agentModelLabel(model: AgentModelChoice | null | undefined) {
  return String(model?.label || model?.model || model?.modelId || "").trim() || "-";
}

function unresolvedDialogueModelIssue(agent: AgentConfigWorkspaceAgent | null | undefined) {
  return (agent?.health ?? []).find((item) => item.code === "unresolved_model_reference_dialogue");
}

function agentDialogueModelDisplay(agent: AgentConfigWorkspaceAgent | null | undefined, lang: "zh" | "en") {
  const model = agent?.dialogueModel;
  const rawModelId = String(agent?.llmBindings?.dialogue?.modelId || "").trim();
  const unresolved = unresolvedDialogueModelIssue(agent);
  if (model) {
    return {
      label: agentModelLabel(model),
      detail: String(model.providerKind || model.apiKeyState || model.modelId || "").trim() || "-",
      unresolved: false,
    };
  }
  if (rawModelId) {
    return {
      label: rawModelId,
      detail: unresolved
        ? (lang === "zh" ? "模型库未注册" : "Model reference unresolved")
        : (lang === "zh" ? "模型详情不可用" : "Model details unavailable"),
      unresolved: Boolean(unresolved),
    };
  }
  return {
    label: "-",
    detail: lang === "zh" ? "未绑定对话模型" : "No dialogue model",
    unresolved: false,
  };
}

function agentModelChoiceLabel(model: AgentModelChoice) {
  const label = agentModelLabel(model);
  const provider = String(model.providerKind || "").trim();
  const modelName = String(model.model || "").trim();
  return [label, provider && provider !== label ? provider : "", modelName && modelName !== label ? modelName : ""]
    .filter(Boolean)
    .join(" · ") || "-";
}

function agentModelChoiceAllowed(model: AgentModelChoice) {
  const text = normalizeText([
    agentModelLabel(model),
    model.model,
    model.modelId,
    model.providerKind,
  ].join(" "));
  return !/\bimage\d*\b/.test(text) && !text.includes("image2");
}

function buildAgentModelChoices(models: AgentModelChoice[]): ModelProfileChoice[] {
  return models
    .filter(agentModelChoiceAllowed)
    .map((model) => ({
      key: model.modelId,
      modelId: model.modelId,
      label: agentModelChoiceLabel(model),
      modelLabel: agentModelLabel(model),
    }))
    .sort((left, right) => left.label.localeCompare(right.label) || left.modelId.localeCompare(right.modelId));
}

function buildAgentSlotModelChoices(
  models: AgentModelChoice[],
  slot: AgentLlmSlotDefinition | undefined,
): ModelProfileChoice[] {
  const filtered = slot?.requiresImageInput
    ? models.filter((model) => agentModelChoiceAllowed(model) && model.supportsImageInput !== false)
    : models.filter(agentModelChoiceAllowed);
  return filtered
    .map((model) => ({
      key: model.modelId,
      modelId: model.modelId,
      label: agentModelChoiceLabel(model),
      modelLabel: agentModelLabel(model),
    }))
    .sort((left, right) => left.label.localeCompare(right.label) || left.modelId.localeCompare(right.modelId));
}

function buildAgentSlotModelChoicesWithCurrent(
  models: AgentModelChoice[],
  slot: AgentLlmSlotDefinition | undefined,
  currentModelId: string,
  lang: "zh" | "en",
): ModelProfileChoice[] {
  const choices = buildAgentSlotModelChoices(models, slot);
  const normalizedCurrent = String(currentModelId || "").trim();
  if (!normalizedCurrent || choices.some((choice) => choice.modelId === normalizedCurrent)) {
    return choices;
  }
  const currentModel = models.find((model) => String(model.modelId || "").trim() === normalizedCurrent);
  const unresolvedReason = currentModel
    ? (lang === "zh" ? "当前绑定，当前槽位不可选" : "current binding, unavailable for this slot")
    : (lang === "zh" ? "当前绑定，模型库未注册" : "current binding, not in model library");
  return [
    {
      key: `${slot?.slot ?? "slot"}:${normalizedCurrent}:unresolved`,
      modelId: normalizedCurrent,
      label: lang === "zh" ? `${normalizedCurrent}（${unresolvedReason}）` : `${normalizedCurrent} (${unresolvedReason})`,
      modelLabel: normalizedCurrent,
      unresolved: true,
    },
    ...choices,
  ];
}

function agentLlmSlots(workspace: AgentConfigWorkspace | undefined): AgentLlmSlotDefinition[] {
  return workspace?.agentLlmSlots?.length ? workspace.agentLlmSlots : FALLBACK_AGENT_LLM_SLOTS;
}

const AGENT_REASONING_EFFORT_VALUES = ["low", "medium", "high"] as const;

function normalizeAgentReasoningEffort(value: unknown) {
  const normalized = String(value ?? "").trim().toLowerCase();
  return AGENT_REASONING_EFFORT_VALUES.includes(normalized as typeof AGENT_REASONING_EFFORT_VALUES[number]) ? normalized : "";
}

function agentModelSupportsReasoningEffort(model: AgentModelChoice | null | undefined) {
  return Boolean((model as Record<string, unknown> | null | undefined)?.supportsReasoningEffort);
}

function agentModelById(models: AgentModelChoice[] | null | undefined, modelId: string) {
  const normalizedModelId = String(modelId || "").trim();
  if (!normalizedModelId) {
    return undefined;
  }
  return (models ?? []).find((model) => String(model.modelId || "").trim() === normalizedModelId);
}

function normalizeAgentLlmBindings(bindings: AgentLlmBindings | null | undefined): AgentLlmBindings {
  return Object.fromEntries(
    Object.entries(bindings ?? {})
      .map(([slot, binding]) => [slot, String(binding?.modelId ?? "").trim()])
      .filter(([, modelId]) => modelId)
      .map(([slot, modelId]) => [slot, { modelId }]),
  ) as AgentLlmBindings;
}

function agentLlmSlotModelId(bindings: AgentLlmBindings | null | undefined, slot: AgentLlmSlotDefinition | undefined) {
  const slotKey = slot?.slot ?? "dialogue";
  return String(bindings?.[slotKey]?.modelId ?? "").trim();
}

function updateAgentLlmSlotBinding(
  bindings: AgentLlmBindings,
  slot: AgentLlmSlotDefinition,
  modelId: string,
): AgentLlmBindings {
  const next = { ...normalizeAgentLlmBindings(bindings) };
  const normalizedModelId = String(modelId || "").trim();
  if (normalizedModelId) {
    next[slot.slot] = { modelId: normalizedModelId };
  } else {
    delete next[slot.slot];
  }
  return next;
}

function sameAgentLlmBindings(left: AgentLlmBindings | null | undefined, right: AgentLlmBindings | null | undefined) {
  const normalizedLeft = normalizeAgentLlmBindings(left);
  const normalizedRight = normalizeAgentLlmBindings(right);
  const keys = Array.from(new Set([...Object.keys(normalizedLeft), ...Object.keys(normalizedRight)])).sort();
  return keys.every((key) => {
    const slot = key as keyof AgentLlmBindings;
    return String(normalizedLeft[slot]?.modelId ?? "") === String(normalizedRight[slot]?.modelId ?? "");
  });
}

function normalizeAgentReasoningEffortBySlot(value: unknown): Record<string, string> {
  if (!value || typeof value !== "object") {
    return {};
  }
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>)
      .map(([slot, effort]) => [String(slot || "").trim(), normalizeAgentReasoningEffort(effort)])
      .filter(([slot, effort]) => slot && effort),
  );
}

function agentReasoningEffortBySlot(agent: AgentConfigWorkspaceAgent | null | undefined): Record<string, string> {
  const metadata = agent?.metadata && typeof agent.metadata === "object"
    ? agent.metadata as Record<string, unknown>
    : {};
  return normalizeAgentReasoningEffortBySlot(metadata.llmReasoningEffort);
}

function pruneAgentReasoningEffortBySlot(
  efforts: Record<string, string>,
  bindings: AgentLlmBindings,
  models: AgentModelChoice[] | null | undefined,
) {
  const normalizedBindings = normalizeAgentLlmBindings(bindings);
  return Object.fromEntries(
    Object.entries(efforts)
      .map(([slot, effort]) => {
        const slotKey = slot as keyof AgentLlmBindings;
        const modelId = String(normalizedBindings[slotKey]?.modelId || "").trim();
        const model = agentModelById(models, modelId);
        return [slot, agentModelSupportsReasoningEffort(model) ? normalizeAgentReasoningEffort(effort) : ""];
      })
      .filter(([slot, effort]) => slot && effort),
  );
}

function updateAgentReasoningEffortBySlot(efforts: Record<string, string>, slot: string, effort: string) {
  const next = { ...normalizeAgentReasoningEffortBySlot(efforts) };
  const normalizedEffort = normalizeAgentReasoningEffort(effort);
  if (normalizedEffort) {
    next[slot] = normalizedEffort;
  } else {
    delete next[slot];
  }
  return next;
}

function sameAgentReasoningEffortBySlot(left: Record<string, string>, right: Record<string, string>) {
  const normalizedLeft = normalizeAgentReasoningEffortBySlot(left);
  const normalizedRight = normalizeAgentReasoningEffortBySlot(right);
  const keys = Array.from(new Set([...Object.keys(normalizedLeft), ...Object.keys(normalizedRight)])).sort();
  return keys.every((key) => normalizedLeft[key] === normalizedRight[key]);
}

function agentMetadataWithReasoningEffort(draft: AgentConfigDraft, models: AgentModelChoice[] | null | undefined) {
  const metadata: Record<string, unknown> = {};
  const pruned = pruneAgentReasoningEffortBySlot(draft.reasoningEffortBySlot, draft.llmBindings, models);
  metadata.llmReasoningEffort = pruned;
  return metadata;
}

function issueTone(issues: AgentConfigHealthIssue[]) {
  if (issues.some((item) => item.severity === "blocking")) {
    return "blocking";
  }
  if (issues.some((item) => item.severity === "warning")) {
    return "warning";
  }
  if (issues.length > 0) {
    return "info";
  }
  return "ok";
}

function issueLabel(issues: AgentConfigHealthIssue[], lang: "zh" | "en") {
  const tone = issueTone(issues);
  if (tone === "blocking") {
    return lang === "zh" ? "阻塞" : "Blocked";
  }
  if (tone === "warning") {
    return lang === "zh" ? "需处理" : "Review";
  }
  if (tone === "info") {
    return lang === "zh" ? "提醒" : "Notice";
  }
  return lang === "zh" ? "正常" : "OK";
}

function issuePanelLabel(issues: AgentConfigHealthIssue[], copy: ReturnType<typeof agentsRouteCopy>) {
  return issueTone(issues) === "info" ? copy.statusReminders : copy.healthIssues;
}

function workspaceHealthStatusLabel(status: string, lang: "zh" | "en") {
  const normalized = String(status || "ok").trim().toLowerCase();
  const zh: Record<string, string> = {
    ok: "正常",
    warning: "需处理",
    blocked: "阻塞",
  };
  const en: Record<string, string> = {
    ok: "OK",
    warning: "Needs review",
    blocked: "Blocked",
  };
  return (lang === "zh" ? zh : en)[normalized] ?? status;
}

function workspaceHealthStatusDescription(status: string, summary: AgentConfigWorkspace["summary"] | undefined, lang: "zh" | "en") {
  const normalized = String(status || "ok").trim().toLowerCase();
  const issueCount = summary?.healthIssueCount ?? 0;
  const blockingCount = summary?.blockingIssueCount ?? 0;
  const warningCount = summary?.warningIssueCount ?? 0;
  if (normalized === "ok" || issueCount === 0) {
    return lang === "zh" ? "当前没有需处理问题。" : "No issues need review.";
  }
  if (lang === "zh") {
    return `共 ${issueCount} 个需处理问题，阻塞 ${blockingCount} 个，警告 ${warningCount} 个。`;
  }
  return `${issueCount} issues need review: ${blockingCount} blocking, ${warningCount} warning.`;
}

function sortedHealthIssues(issues: AgentConfigHealthIssue[]) {
  const order: Record<string, number> = { blocking: 0, warning: 1, info: 2 };
  return [...issues].sort((left, right) => (order[left.severity] ?? 3) - (order[right.severity] ?? 3));
}

function issueSummary(issues: AgentConfigHealthIssue[], lang: "zh" | "en") {
  const [first] = sortedHealthIssues(issues);
  if (!first) {
    return lang === "zh" ? "配置完整，可直接引用" : "Ready to use";
  }
  const rest = issues.length > 1 ? (lang === "zh" ? `，另有 ${issues.length - 1} 项` : `, +${issues.length - 1} more`) : "";
  return `${issueDisplayTitle(first, lang)}${rest}`;
}

function issueDisplayTitle(issue: AgentConfigHealthIssue, lang: "zh" | "en") {
  if (issue.code === "pending_inbox_messages") {
    return lang === "zh" ? "Inbox 有待处理消息" : "Pending inbox messages";
  }
  return issue.title;
}

function issueNextStep(issues: AgentConfigHealthIssue[], lang: "zh" | "en") {
  const [first] = sortedHealthIssues(issues);
  const tone = issueTone(issues);
  if (tone === "blocking") {
    return lang === "zh" ? "先补齐阻塞项，否则不要加入可调度池。" : "Fix blocking items before routing this Agent.";
  }
  if (tone === "warning") {
    return lang === "zh" ? "建议在配置页处理，避免运行时缺上下文。" : "Review config to avoid missing runtime context.";
  }
  if (tone === "info") {
    if (first?.code === "pending_inbox_messages") {
      return lang === "zh"
        ? "这是 Inbox 待办提醒，不代表配置坏了；进入活动页处理消息即可。"
        : "This is an inbox reminder, not a broken config; handle the messages in Activity.";
    }
    return lang === "zh" ? "这是提醒项，不影响当前配置完整度。" : "This is a reminder and does not affect current config readiness.";
  }
  return lang === "zh" ? "当前没有需要处理的问题或提醒。" : "No issue or reminder needs action.";
}

function runtimeStatusLabel(agent: AgentConfigWorkspaceAgent | null | undefined, lang: "zh" | "en") {
  const state = String(agent?.runtimeStatus?.state || (agent?.status === "archived" ? "archived" : "idle")).trim();
  const zh: Record<string, string> = {
    idle: "空闲",
    running: "运行中",
    failed: "失败",
    blocked: "阻塞",
    stopped: "已停止",
    archived: "已归档",
    unknown: "未知",
  };
  const en: Record<string, string> = {
    idle: "Idle",
    running: "Running",
    failed: "Failed",
    blocked: "Blocked",
    stopped: "Stopped",
    archived: "Archived",
    unknown: "Unknown",
  };
  return (lang === "zh" ? zh : en)[state] ?? agent?.runtimeStatus?.label ?? (state || "-");
}

function runtimeStatusTone(agent: AgentConfigWorkspaceAgent | null | undefined) {
  const state = String(agent?.runtimeStatus?.state || (agent?.status === "archived" ? "archived" : "idle")).trim();
  return ["idle", "running", "failed", "blocked", "stopped", "archived", "unknown"].includes(state) ? state : "unknown";
}

function runtimeNextStep(agent: AgentConfigWorkspaceAgent | null | undefined, lang: "zh" | "en") {
  const state = runtimeStatusTone(agent);
  if (state === "running") {
    return lang === "zh"
      ? "先打开会话确认实时输出；如果出现卡住，再进入日志证据查看当前 run。"
      : "Open the session first to inspect live output; if it stalls, open log evidence for the current run.";
  }
  if (state === "failed") {
    return lang === "zh"
      ? "优先打开日志证据，定位失败事件和 raw log；再对照下方运行历史。"
      : "Open log evidence first to locate the failed event and raw log, then compare the run history below.";
  }
  if (state === "blocked") {
    return lang === "zh"
      ? "先检查 Inbox 和运行历史，确认是在等输入、等证据，还是需要人工复核。"
      : "Check Inbox and run history first to see whether it is waiting for input, evidence, or review.";
  }
  if (state === "stopped") {
    return lang === "zh"
      ? "查看最近运行记录确认停止原因；需要继续时从关联会话恢复上下文。"
      : "Inspect the latest run record for the stop reason; resume from the linked session when needed.";
  }
  if (state === "archived") {
    return lang === "zh"
      ? "该 Agent 已归档；只适合查看历史会话、记忆和日志，不建议继续分配新任务。"
      : "This Agent is archived; inspect historical sessions, memory, and logs instead of assigning new work.";
  }
  if (state === "unknown") {
    return lang === "zh"
      ? "运行态来源不可用；先刷新配置，再查看日志总入口确认是否缺少 WorkRun 快照。"
      : "Runtime status is unavailable; refresh config, then inspect Logs to confirm whether WorkRun snapshots are missing.";
  }
  return lang === "zh"
    ? "当前没有活跃运行；可查看最近运行历史、Inbox，或打开直连会话分配下一步任务。"
    : "No active run is visible; inspect recent run history, Inbox, or open the direct session for the next task.";
}

function runtimeEvidenceReasonLabel(reason: RuntimeFocusEvidenceResult["reason"], lang: "zh" | "en") {
  const zh: Record<RuntimeFocusEvidenceResult["reason"], string> = {
    run: "按 run 命中",
    source_run: "按 source run 命中",
    session: "按 session 命中",
    fallback: "回落证据",
    missing: "暂无证据",
  };
  const en: Record<RuntimeFocusEvidenceResult["reason"], string> = {
    run: "Matched by run",
    source_run: "Matched by source run",
    session: "Matched by session",
    fallback: "Fallback evidence",
    missing: "No evidence",
  };
  return (lang === "zh" ? zh : en)[reason];
}

function modeLabel(mode: string, lang: "zh" | "en") {
  const zh: Record<string, string> = {
    chat: "会话",
    research: "科研",
    supervised_evolution: "监督",
    self_evolution: "自进化",
    general: "通用",
  };
  const en: Record<string, string> = {
    chat: "Chat",
    research: "Research",
    supervised_evolution: "Supervised",
    self_evolution: "Self evolution",
    general: "General",
  };
  return (lang === "zh" ? zh : en)[mode] ?? mode;
}

function referenceLabel(reference: AgentConfigReference, lang: "zh" | "en") {
  const kind = reference.kind;
  const zh: Record<string, string> = {
    direct_session: "直连会话",
    mode_default: "模式默认",
    mode_available: "模式可选",
    mode_pool: "模式池",
    mode_slot: "角色槽位",
    flow_binding: "流程绑定",
    chat_room: "群聊",
    team: "团队",
  };
  const en: Record<string, string> = {
    direct_session: "Direct session",
    mode_default: "Mode default",
    mode_available: "Mode available",
    mode_pool: "Mode pool",
    mode_slot: "Role slot",
    flow_binding: "Flow binding",
    chat_room: "Group room",
    team: "Team",
  };
  return (lang === "zh" ? zh : en)[kind] ?? kind;
}

function referenceRoute(reference: AgentConfigReference) {
  if (reference.kind === "team" && reference.sourceId) {
    return `/teams?team=${encodeURIComponent(reference.sourceId)}`;
  }
  return reference.route || "";
}

function uniqueModes(agent: AgentConfigWorkspaceAgent) {
  return Array.from(
    new Set(
      [agent.primaryMode, ...agent.references.map((item) => item.mode)]
        .map((item) => String(item || "").trim())
        .filter(Boolean),
    ),
  );
}

function buildActivityTimeline(
  agent: AgentConfigWorkspaceAgent,
  runs: AgentRunHistory | undefined,
  messages: AgentInboxMessage[] | undefined,
  copy: ReturnType<typeof agentsRouteCopy>,
  lang: "zh" | "en",
  evidence: AgentRuntimeEvidence | undefined,
): AgentActivityTimelineItem[] {
  const items: AgentActivityTimelineItem[] = [];
  const evidenceMatches = evidence?.matches ?? [];
  const findEvidence = (sessionId: string, runId: string, messageId = "") => {
    const normalizedSession = String(sessionId || "").trim();
    const normalizedRun = String(runId || "").trim();
    const normalizedMessage = String(messageId || "").trim();
    return evidenceMatches.find((item) => {
      const fields = item.matchedFields ?? {};
      return (
        (normalizedRun && Object.values(fields).includes(normalizedRun))
        || (normalizedSession && Object.values(fields).includes(normalizedSession))
        || (normalizedMessage && Object.values(fields).includes(normalizedMessage))
      );
    }) ?? evidenceMatches[0] ?? null;
  };
  for (const run of runs?.runs ?? []) {
    const timestamp = run.updatedAt || run.finishedAt || run.startedAt || "";
    items.push({
      id: `run:${run.runId}`,
      kind: "run",
      title: run.status || run.currentPhase || run.runKind || copy.parentRuns,
      body: run.summary || run.runId || "-",
      meta: `${copy.parentRuns} · ${run.currentPhase || run.sessionId || "-"}`,
      timestamp,
      sessionId: run.sessionId || agent.directSessionId || "",
      messageId: "",
      canOpenLogs: true,
      evidence: findEvidence(run.sessionId || agent.directSessionId || "", run.sourceRunId || run.runId || ""),
    });
  }
  for (const run of runs?.subAgentRuns ?? []) {
    const timestamp = run.updatedAt || run.endedAt || run.createdAt || "";
    items.push({
      id: `sub:${run.runId}`,
      kind: "sub_run",
      title: `${copy.subAgentRuns} · ${run.status || run.currentPhase || run.runKind || "-"}`,
      body: run.summary || run.subRunId || run.runId || "-",
      meta: `${run.contextMode || "-"} · ${copy.maxDepth} ${run.depth}/${run.maxDepth}`,
      timestamp,
      sessionId: run.parentSessionId || agent.directSessionId || "",
      messageId: "",
      canOpenLogs: true,
      evidence: findEvidence(run.parentSessionId || agent.directSessionId || "", run.runId || run.subRunId || ""),
    });
  }
  for (const message of messages ?? []) {
    const messageId = message.messageId || message.eventId || "";
    items.push({
      id: `inbox:${messageId}`,
      kind: "inbox",
      title: message.sourceAgentName || message.sourceAgentCode || message.sourceAgentId || copy.inboxTitle,
      body: message.summary || message.content || message.threadId || messageId || "-",
      meta: `${copy.inboxTitle} · ${copy.wakeStatus}: ${message.delivery?.wakeStatus || "pending"}`,
      timestamp: message.createdAt || "",
      sessionId: message.targetSessionId || agent.directSessionId || "",
      messageId,
      canOpenLogs: false,
      evidence: findEvidence(message.targetSessionId || agent.directSessionId || "", "", messageId),
    });
  }
  for (const event of agent.groupContextEvents ?? []) {
    items.push({
      id: `context:${event.eventId}`,
      kind: "context",
      title: event.topic || copy.context,
      body: event.summary || event.ownMessage || event.sourceRoomId || "-",
      meta: `${copy.context} · ${event.sourceRoomId || "-"}`,
      timestamp: event.createdAt || "",
      sessionId: event.targetSessionId || agent.directSessionId || "",
      messageId: "",
      canOpenLogs: true,
      evidence: findEvidence(event.targetSessionId || agent.directSessionId || "", event.sourceRoundId || ""),
    });
  }
  return items
    .sort((left, right) => timestampValue(right.timestamp) - timestampValue(left.timestamp))
    .slice(0, 10)
    .map((item) => ({
      ...item,
      meta: `${item.meta} · ${formatTimestamp(item.timestamp, lang)}`,
    }));
}

function findRuntimeFocusEvidence(
  agent: AgentConfigWorkspaceAgent | null | undefined,
  evidence: AgentRuntimeEvidence | undefined,
): RuntimeFocusEvidenceResult {
  const matches = evidence?.matches ?? [];
  if (!matches.length || !agent?.runtimeStatus) {
    return { match: matches[0] ?? null, reason: matches[0] ? "fallback" : "missing" };
  }
  const runId = String(agent.runtimeStatus.runId || "").trim();
  const sessionId = String(agent.runtimeStatus.sessionId || agent.directSessionId || "").trim();
  const sourceRunId = runId.includes("-") ? runId.split("-").at(-1) ?? "" : "";
  const fieldValues = (item: AgentRuntimeEvidenceMatch) =>
    Object.values(item.matchedFields ?? {}).map((value) => String(value || "").trim());
  const runMatch = matches.find((item) => runId && fieldValues(item).includes(runId));
  if (runMatch) {
    return { match: runMatch, reason: "run" };
  }
  const sourceRunMatch = matches.find((item) => sourceRunId && fieldValues(item).includes(sourceRunId));
  if (sourceRunMatch) {
    return { match: sourceRunMatch, reason: "source_run" };
  }
  const sessionMatch = matches.find((item) => sessionId && fieldValues(item).includes(sessionId));
  if (sessionMatch) {
    return { match: sessionMatch, reason: "session" };
  }
  return { match: matches[0] ?? null, reason: matches[0] ? "fallback" : "missing" };
}

function workspaceTeamIndexes(workspace: AgentConfigWorkspace | undefined): AgentTeamIndexGroup[] {
  const rawIndexes = (workspace as AgentConfigWorkspaceWithTeamIndexes | undefined)?.teamIndexes;
  const indexes = Array.isArray(rawIndexes) ? rawIndexes : [];
  return indexes.filter(
    (item): item is AgentTeamIndexGroup =>
      Boolean(
        item &&
          (item.section === "team_index" || item.section === "source_scope") &&
          item.id &&
          item.label &&
          Array.isArray(item.agentIds),
      ),
  );
}

function lightweightAgentBoundary(agent: AgentConfigWorkspaceAgent): AgentBoundary {
  if (agent.agentBoundary) {
    return agent.agentBoundary;
  }
  const archived = agent.status === "archived";
  const teamManaged = String(agent.primaryMode || "").trim() === "research";
  return {
    type: archived ? "archived" : teamManaged ? "team_role" : "work_session",
    label: archived ? "已归档 Agent" : teamManaged ? "团队/科研角色 Agent" : "会话入口 Agent",
    ownership: archived ? "archive" : teamManaged ? "team" : "user",
    directSessionRole: agent.directSessionId ? "primary_entry" : "none",
    reason: archived ? "archived" : teamManaged ? "summary_research_mode" : "summary_agent",
    configurationSurface: archived ? "archive" : teamManaged ? "team_role" : "work_session",
    requiresPersonaProfile: teamManaged ? "true" : "false",
    requiresTaskProfile: teamManaged ? "true" : "false",
    requiresTeamMembership: teamManaged ? "true" : "false",
  };
}

function normalizeLightweightAgent(agent: AgentConfigWorkspaceAgent): AgentConfigWorkspaceAgent {
  const normalized = {
    ...agent,
    references: Array.isArray(agent.references) ? agent.references : [],
    health: Array.isArray(agent.health) ? agent.health : [],
  };
  return {
    ...normalized,
    agentBoundary: lightweightAgentBoundary(normalized),
  };
}

function lightweightAgentGroup(
  id: string,
  label: string,
  section: string,
  description: string,
  agents: AgentConfigWorkspaceAgent[],
  predicate: (agent: AgentConfigWorkspaceAgent) => boolean,
): AgentConfigWorkspaceGroup {
  const agentIds = agents.filter(predicate).map((agent) => agent.agentId);
  return {
    id,
    label,
    section,
    description,
    agentIds,
    count: agentIds.length,
    healthCount: agents.filter((agent) => agentIds.includes(agent.agentId) && hasActionableHealthIssue(agent)).length,
  };
}

function buildLightweightAgentWorkspace(
  rawAgents: AgentConfigWorkspaceAgent[],
  updatedAt: number,
): AgentConfigWorkspaceWithTeamIndexes {
  const agents = rawAgents.map(normalizeLightweightAgent);
  const activeAgents = agents.filter((agent) => agent.status !== "archived");
  const issues = agents.flatMap((agent) => agent.health ?? []);
  const groups = [
    lightweightAgentGroup("active", "可用 Agent", "status", "当前可被业务页面引用或调度的 Agent。", agents, (agent) => agent.status !== "archived"),
    lightweightAgentGroup("archived", "已归档", "status", "只保留历史数据、不再进入可用池的 Agent。", agents, (agent) => agent.status === "archived"),
    lightweightAgentGroup("chat", "会话模式", "mode", "属于 Chat 运行模式或会话可用池的 Agent。", activeAgents, (agent) => agent.primaryMode === "chat"),
    lightweightAgentGroup("research", "科研模式", "mode", "属于 Research 运行模式或科研池的 Agent。", activeAgents, (agent) => agent.primaryMode === "research"),
    lightweightAgentGroup(
      "supervised_evolution",
      "监督进化模式",
      "mode",
      "占用监督进化模式引用的 Agent。",
      activeAgents,
      (agent) => agent.primaryMode === "supervised_evolution",
    ),
    lightweightAgentGroup("self_evolution", "自进化模式", "mode", "占用自进化模式引用的 Agent。", activeAgents, (agent) => agent.primaryMode === "self_evolution"),
  ].filter((group) => group.count > 0 || group.id === "active" || group.id === "archived");
  return {
    schemaVersion: 1,
    generatedAt: new Date(updatedAt || Date.now()).toISOString(),
    storage: LIGHTWEIGHT_AGENT_CONFIG_STORAGE,
    summary: {
      agentCount: agents.length,
      activeAgentCount: activeAgents.length,
      archivedAgentCount: agents.length - activeAgents.length,
      runningAgentCount: 0,
      blockedAgentCount: 0,
      modeCount: new Set(activeAgents.map((agent) => agent.primaryMode).filter(Boolean)).size,
      chatRoomCount: 0,
      groupCount: groups.length,
      healthIssueCount: issues.length,
      blockingIssueCount: issues.filter((issue) => issue.severity === "blocking").length,
      warningIssueCount: issues.filter((issue) => issue.severity === "warning").length,
      inboxPendingCount: 0,
      teamCount: 0,
    },
    groups,
    teamIndexes: [],
    agents,
    modeBindings: {},
    promptTemplates: [],
    agentLlmSlots: FALLBACK_AGENT_LLM_SLOTS,
    agentModelChoices: [],
    modelOptions: [],
    toolPolicies: [],
    memoryPolicies: [],
    chatRooms: [],
    teams: [],
    references: Object.fromEntries(agents.map((agent) => [agent.agentId, agent.references ?? []])),
    health: {
      status: issues.some((issue) => issue.severity === "blocking") ? "blocked" : issues.some((issue) => issue.severity === "warning") ? "warning" : "ok",
      issues,
      counts: {
        blocking: issues.filter((issue) => issue.severity === "blocking").length,
        warning: issues.filter((issue) => issue.severity === "warning").length,
        info: issues.filter((issue) => issue.severity === "info").length,
      },
      byAgent: Object.fromEntries(agents.map((agent) => [agent.agentId, agent.health ?? []])),
    },
    repairWarnings: {
      modeBindings: [],
      promptTemplates: [],
    },
    diagnostics: {
      source: "agent_summary_fallback",
    },
  };
}

function filterAgents(
  workspace: AgentConfigWorkspace | undefined,
  activeFilter: FilterId,
  searchText: string,
) {
  const agents = workspace?.agents ?? [];
  const query = normalizeText(searchText);
  const managementFilter = activeFilter.startsWith("setup:");
  const group = (workspace?.groups ?? []).find((item) => item.id === activeFilter);
  const teamIndexGroup = workspaceTeamIndexes(workspace).find((item) => item.id === activeFilter);
  const groupIds = new Set((group ?? teamIndexGroup)?.agentIds ?? []);
  return agents.filter((agent) => {
    const archived = agent.status === "archived";
    if (activeFilter === "archived") {
      if (!archived) {
        return false;
      }
    } else if (archived) {
      return false;
    }
    if (managementFilter && !managementFilterMatches(agent, activeFilter)) {
      return false;
    }
    if (!managementFilter && (group || teamIndexGroup) && !groupIds.has(agent.agentId)) {
      return false;
    }
    return !query || agentSearchText(agent).includes(query);
  });
}

function selectedAgentFromList(
  agents: AgentConfigWorkspaceAgent[],
  selectedAgentId: string,
  fallbackAgents: AgentConfigWorkspaceAgent[],
  activeFilter: FilterId,
) {
  const fallbackCandidates = activeFilter === "archived"
    ? fallbackAgents.filter((agent) => agent.status === "archived")
    : fallbackAgents.filter((agent) => agent.status !== "archived");
  return (
    agents.find((agent) => agent.agentId === selectedAgentId) ??
    agents[0] ??
    fallbackCandidates[0] ??
    null
  );
}

function buildVisibleAgentColumns(
  agents: AgentConfigWorkspaceAgent[],
  copy: ReturnType<typeof agentsRouteCopy>,
  teamIndexGroups: AgentTeamIndexGroup[],
) {
  const sessionAgents = agents.filter(isWorkSessionAgent);
  const nonSessionAgents = agents.filter((agent) => !isWorkSessionAgent(agent));
  const visibleNonSessionIds = new Set(nonSessionAgents.map((agent) => agent.agentId));
  const assignedTeamAgentIds = new Set<string>();
  const teamColumns = teamIndexGroups
    .filter((group) => group.section === "team_index")
    .map((group) => {
      const groupIds = new Set(group.agentIds);
      const teamAgents = nonSessionAgents.filter((agent) => {
        if (!groupIds.has(agent.agentId) || assignedTeamAgentIds.has(agent.agentId)) {
          return false;
        }
        return visibleNonSessionIds.has(agent.agentId);
      });
      teamAgents.forEach((agent) => assignedTeamAgentIds.add(agent.agentId));
      return {
        id: `team_agents:${group.id}`,
        label: group.label,
        description: group.description || copy.teamAgentColumnHint,
        agents: teamAgents,
      };
    })
    .filter((column) => column.agents.length > 0);
  const unassignedNonSessionAgents = nonSessionAgents.filter((agent) => !assignedTeamAgentIds.has(agent.agentId));
  return [
    {
      id: "session_agents",
      label: copy.sessionAgentColumn,
      description: copy.sessionAgentColumnHint,
      agents: sessionAgents,
    },
    ...teamColumns,
    {
      id: "non_session_agents",
      label: copy.nonSessionAgentColumn,
      description: copy.nonSessionAgentColumnHint,
      agents: unassignedNonSessionAgents,
    },
  ].filter((column) => column.agents.length > 0);
}

function normalizeAgentConfigPane(value: string | null | undefined): AgentConfigPaneId {
  const normalized = String(value || "").trim();
  return normalized === "config" || normalized === "activity" || normalized === "overview"
    ? normalized
    : "overview";
}

function safeAgentCenterReturnTo(value: string | null | undefined) {
  const normalized = String(value || "").trim();
  if (!normalized || !normalized.startsWith("/") || normalized.startsWith("//")) {
    return "";
  }
  return normalized;
}

function agentCenterReturnLabel(value: string | null | undefined, lang: "zh" | "en") {
  const normalized = String(value || "").trim();
  if (normalized === "supervised_evolution") {
    return lang === "zh" ? "返回监督进化" : "Back to supervised evolution";
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

function teamIndexesWithoutAgentIds(
  workspace: AgentConfigWorkspace | undefined,
  removedAgentIds: Set<string>,
): AgentTeamIndexGroup[] | undefined {
  const indexes = workspaceTeamIndexes(workspace);
  if (!indexes.length) {
    return undefined;
  }
  return indexes.map((group) => {
    const agentIds = group.agentIds.filter((id) => !removedAgentIds.has(id));
    return {
      ...group,
      agentIds,
      count: agentIds.length,
    };
  });
}

function draftSyncSourceFromAgent(
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

function archivedWorkspaceCache(
  workspace: AgentConfigWorkspace | undefined,
  archivedAgent: AgentConfigWorkspaceAgent,
): AgentConfigWorkspace | undefined {
  if (!workspace) {
    return workspace;
  }
  const agentId = archivedAgent.agentId;
  const cachedAgent = workspace.agents.find((agent) => agent.agentId === agentId);
  const wasActive = cachedAgent ? cachedAgent.status !== "archived" : false;
  const nextAgents = workspace.agents.map((agent) =>
    agent.agentId === agentId
      ? {
          ...agent,
          ...archivedAgent,
          status: "archived",
          runtimeStatus: {
            state: "archived",
            label: archivedAgent.runtimeStatus?.label || "Archived",
            reason: archivedAgent.runtimeStatus?.reason || "agent_archived",
            runId: archivedAgent.runtimeStatus?.runId || agent.runtimeStatus?.runId || "",
            runKind: archivedAgent.runtimeStatus?.runKind || agent.runtimeStatus?.runKind || "",
            sessionId: archivedAgent.runtimeStatus?.sessionId || agent.runtimeStatus?.sessionId || agent.directSessionId || "",
            summary: archivedAgent.runtimeStatus?.summary || "",
            updatedAt: archivedAgent.runtimeStatus?.updatedAt || archivedAgent.updatedAt || agent.updatedAt || "",
          },
        }
      : agent,
  );
  const nextGroups = workspace.groups.map((group) => {
    const agentIds = group.id === "archived"
      ? Array.from(new Set([...group.agentIds, agentId]))
      : group.agentIds.filter((id) => id !== agentId);
    return {
      ...group,
      agentIds,
      count: agentIds.length,
    };
  });
  const nextTeamIndexes = teamIndexesWithoutAgentIds(workspace, new Set([agentId]));
  return {
    ...workspace,
    agents: nextAgents,
    groups: nextGroups,
    ...(nextTeamIndexes ? { teamIndexes: nextTeamIndexes } : {}),
    summary: {
      ...workspace.summary,
      activeAgentCount: wasActive ? Math.max(0, workspace.summary.activeAgentCount - 1) : workspace.summary.activeAgentCount,
      archivedAgentCount: wasActive ? workspace.summary.archivedAgentCount + 1 : workspace.summary.archivedAgentCount,
    },
  };
}

function optimisticArchivedAgent(agent: AgentConfigWorkspaceAgent): AgentConfigWorkspaceAgent {
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

function purgedWorkspaceCache(
  workspace: AgentConfigWorkspace | undefined,
  purgedAgentId: string,
): AgentConfigWorkspace | undefined {
  if (!workspace) {
    return workspace;
  }
  const agentId = String(purgedAgentId || "").trim();
  if (!agentId) {
    return workspace;
  }
  const cachedAgent = workspace.agents.find((agent) => agent.agentId === agentId);
  const nextAgents = workspace.agents.filter((agent) => agent.agentId !== agentId);
  const nextGroups = workspace.groups.map((group) => {
    const agentIds = group.agentIds.filter((id) => id !== agentId);
    return {
      ...group,
      agentIds,
      count: agentIds.length,
    };
  });
  const nextTeamIndexes = teamIndexesWithoutAgentIds(workspace, new Set([agentId]));
  const wasActive = cachedAgent ? cachedAgent.status !== "archived" : false;
  const wasArchived = cachedAgent ? cachedAgent.status === "archived" : false;
  return {
    ...workspace,
    agents: nextAgents,
    groups: nextGroups,
    ...(nextTeamIndexes ? { teamIndexes: nextTeamIndexes } : {}),
    summary: {
      ...workspace.summary,
      activeAgentCount: wasActive ? Math.max(0, workspace.summary.activeAgentCount - 1) : workspace.summary.activeAgentCount,
      archivedAgentCount: wasArchived ? Math.max(0, workspace.summary.archivedAgentCount - 1) : workspace.summary.archivedAgentCount,
    },
  };
}

function bulkPurgeWorkspaceCache(
  workspace: AgentConfigWorkspace | undefined,
  bulkResponse: AgentBulkActionResponse,
): AgentConfigWorkspace | undefined {
  if (!workspace) {
    return workspace;
  }
  const purgedAgentIds = new Set(
    bulkResponse.success
      .map((item) => String(item.agentId || "").trim())
      .filter(Boolean),
  );
  if (!purgedAgentIds.size) {
    return workspace;
  }
  const removedAgents = workspace.agents.filter((agent) => purgedAgentIds.has(agent.agentId));
  const removedActiveCount = removedAgents.filter((agent) => agent.status !== "archived").length;
  const removedArchivedCount = removedAgents.filter((agent) => agent.status === "archived").length;
  const nextGroups = workspace.groups.map((group) => {
    const agentIds = group.agentIds.filter((id) => !purgedAgentIds.has(id));
    return {
      ...group,
      agentIds,
      count: agentIds.length,
    };
  });
  const nextTeamIndexes = teamIndexesWithoutAgentIds(workspace, purgedAgentIds);
  return {
    ...workspace,
    agents: workspace.agents.filter((agent) => !purgedAgentIds.has(agent.agentId)),
    groups: nextGroups,
    ...(nextTeamIndexes ? { teamIndexes: nextTeamIndexes } : {}),
    summary: {
      ...workspace.summary,
      activeAgentCount: Math.max(0, workspace.summary.activeAgentCount - removedActiveCount),
      archivedAgentCount: Math.max(0, workspace.summary.archivedAgentCount - removedArchivedCount),
    },
  };
}

function updatedAgentWorkspaceCache(
  workspace: AgentConfigWorkspace | undefined,
  updatedAgent: Partial<AgentConfigWorkspaceAgent> & Pick<AgentConfigWorkspaceAgent, "agentId">,
): AgentConfigWorkspace | undefined {
  if (!workspace) {
    return workspace;
  }
  const nextAgents = workspace.agents.map((agent) =>
    agent.agentId === updatedAgent.agentId
      ? {
          ...agent,
          ...updatedAgent,
          references: updatedAgent.references ?? agent.references,
          health: updatedAgent.health ?? agent.health,
          runtimeStatus: updatedAgent.runtimeStatus ?? agent.runtimeStatus,
          dialogueModel: updatedAgent.dialogueModel ?? agent.dialogueModel,
          llmBindingModels: updatedAgent.llmBindingModels ?? agent.llmBindingModels,
          promptTemplate: updatedAgent.promptTemplate ?? agent.promptTemplate,
        }
      : agent,
  );
  return {
    ...workspace,
    agents: nextAgents,
  };
}

function bulkUpdatedAgentWorkspaceCache(
  workspace: AgentConfigWorkspace | undefined,
  updatedAgents: Array<Partial<AgentConfigWorkspaceAgent> & Pick<AgentConfigWorkspaceAgent, "agentId">>,
): AgentConfigWorkspace | undefined {
  return updatedAgents.reduce(
    (current, updatedAgent) => updatedAgentWorkspaceCache(current, updatedAgent),
    workspace,
  );
}

function groupDisplayLabel(group: { id: string; label?: string } | undefined, copy: ReturnType<typeof agentsRouteCopy>) {
  if (!group) {
    return copy.activeAgents;
  }
  return copy.groupLabels[group.id] ?? group.label;
}

function groupSectionId(group: AgentFilterGroup) {
  const section = String(group.section || "").trim();
  return section === "boundary" ||
    section === "mode" ||
    section === "reference" ||
    section === "team_index" ||
    section === "source_scope"
    ? section
    : "status";
}

function groupDescription(group: { id: string; description?: string }, copy: ReturnType<typeof agentsRouteCopy>) {
  return copy.groupDescriptions[group.id] ?? group.description ?? "";
}

function groupAriaLabel(
  label: string,
  group: { id?: string; count: number; healthCount?: number },
  copy: ReturnType<typeof agentsRouteCopy>,
  lang: "zh" | "en",
) {
  if (!group.healthCount) {
    return lang === "zh" ? `${label}，${group.count} 个 Agent` : `${label}, ${group.count} Agents`;
  }
  const countLabel = group.id === "setup:inbox" ? copy.statusReminderShort : copy.healthIssueShort;
  return lang === "zh"
    ? `${label}，${group.count} 个 Agent，${countLabel} ${group.healthCount} 个`
    : `${label}, ${group.count} Agents, ${countLabel} ${group.healthCount}`;
}

function numericText(value: unknown, fallback: number) {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? String(Math.round(parsed)) : String(fallback);
}

function percentText(value: unknown, fallbackRatio: number) {
  const parsed = typeof value === "number" ? value : Number(value);
  const ratio = Number.isFinite(parsed) ? parsed : fallbackRatio;
  return String(Math.round(Math.max(0, Math.min(1, ratio)) * 100));
}

function percentToRatio(value: string, fallback: number) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.max(0, Math.min(1, parsed / 100)) : fallback;
}

function positiveIntegerFromText(value: string, fallback: number) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.max(0, Math.round(parsed)) : fallback;
}

function contextCompressionDraftFromAgent(agent: AgentConfigWorkspaceAgent | null | undefined): AgentContextCompressionPolicyDraft {
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

function contextCompressionPolicyFromDraft(draft: AgentContextCompressionPolicyDraft): AgentContextCompressionPolicy {
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

function contextCompressionDraftEqualsDraft(left: AgentContextCompressionPolicyDraft, right: AgentContextCompressionPolicyDraft) {
  return JSON.stringify(contextCompressionPolicyFromDraft(left)) === JSON.stringify(contextCompressionPolicyFromDraft(right));
}

function draftFromAgent(agent: AgentConfigWorkspaceAgent | null | undefined): AgentConfigDraft {
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

function draftEqualsAgent(draft: AgentConfigDraft, agent: AgentConfigWorkspaceAgent | null | undefined) {
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

function defaultPersonaProfile(): AgentPersonaProfile {
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

function normalizePersonaProfile(profile: Partial<AgentPersonaProfile> | null | undefined): AgentPersonaProfile {
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

function personaDraftFromAgent(agent: AgentConfigWorkspaceAgent | null | undefined): AgentPersonaDraft {
  const profile = normalizePersonaProfile(agent?.personaProfile);
  return {
    ...profile,
    expertise: profile.expertise.join(", "),
  };
}

function expertiseFromDraft(value: string) {
  return sortedIds(String(value || "").split(/[,，;；\n]+/).map((item) => item.trim()).filter(Boolean));
}

function personaProfileFromDraft(draft: AgentPersonaDraft): AgentPersonaProfile {
  return normalizePersonaProfile({
    ...draft,
    expertise: expertiseFromDraft(draft.expertise),
  });
}

function personaDraftEqualsAgent(draft: AgentPersonaDraft, agent: AgentConfigWorkspaceAgent | null | undefined) {
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

function personaProfileSummary(agent: AgentConfigWorkspaceAgent | null | undefined, lang: "zh" | "en") {
  const profile = normalizePersonaProfile(agent?.personaProfile);
  const parts = [profile.gender, profile.age, profile.personality].filter(Boolean);
  if (parts.length) {
    return parts.slice(0, 3).join(" / ");
  }
  return lang === "zh" ? "未设置人物档案" : "No persona profile";
}

function defaultTaskProfile(): AgentTaskProfile {
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

function normalizeTaskProfile(profile: Partial<AgentTaskProfile> | null | undefined): AgentTaskProfile {
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

function taskDraftFromAgent(agent: AgentConfigWorkspaceAgent | null | undefined): AgentTaskDraft {
  const profile = normalizeTaskProfile(agent?.taskProfile);
  return {
    ...profile,
    taskTypes: profile.taskTypes.join(", "),
  };
}

function taskProfileFromDraft(draft: AgentTaskDraft): AgentTaskProfile {
  return normalizeTaskProfile({
    ...draft,
    taskTypes: expertiseFromDraft(draft.taskTypes),
  });
}

function taskDraftEqualsAgent(draft: AgentTaskDraft, agent: AgentConfigWorkspaceAgent | null | undefined) {
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

function taskProfileSummary(agent: AgentConfigWorkspaceAgent | null | undefined, lang: "zh" | "en") {
  const profile = normalizeTaskProfile(agent?.taskProfile);
  const parts = [profile.mission, profile.preferredTasks, profile.successCriteria].filter(Boolean);
  if (parts.length) {
    return parts[0];
  }
  return lang === "zh" ? "未设置任务档案" : "No task profile";
}

function hasPersonaProfile(agent: AgentConfigWorkspaceAgent | null | undefined) {
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

function hasTaskProfile(agent: AgentConfigWorkspaceAgent | null | undefined) {
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

function hasToolPolicyConfiguration(agent: AgentConfigWorkspaceAgent | null | undefined) {
  const policy = agent?.toolPolicy;
  return Boolean(
    policy?.allowedTools?.length
      || policy?.preferredTools?.length
      || policy?.blockedTools?.length,
  );
}

function agentBoundaryType(agent: AgentConfigWorkspaceAgent | null | undefined) {
  return String(agent?.agentBoundary?.type || (agent?.status === "archived" ? "archived" : "")).trim();
}

function isWorkSessionAgent(agent: AgentConfigWorkspaceAgent | null | undefined) {
  return agentBoundaryType(agent) === "work_session";
}

function isWorkSessionCreateDraft(draft: AgentCreateDraft) {
  const primaryMode = String(draft.primaryMode || "").trim();
  return primaryMode === "" || primaryMode === "chat";
}

function normalizeToolPolicyDraftForAgent(
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

function requiresPersonaProfile(agent: AgentConfigWorkspaceAgent | null | undefined) {
  return agent?.agentBoundary?.requiresPersonaProfile === "true";
}

function requiresTaskProfile(agent: AgentConfigWorkspaceAgent | null | undefined) {
  return agent?.agentBoundary?.requiresTaskProfile === "true";
}

function requiresTeamMembership(agent: AgentConfigWorkspaceAgent | null | undefined) {
  return agent?.agentBoundary?.requiresTeamMembership === "true";
}

function hasModelAndPromptConfiguration(agent: AgentConfigWorkspaceAgent | null | undefined) {
  return Boolean(agent?.llmBindings?.dialogue?.modelId && agent.promptTemplateId);
}

function hasWorkspaceConfiguration(agent: AgentConfigWorkspaceAgent | null | undefined) {
  return Boolean(agent?.workspacePath || agent?.workspaceTerritory?.privateRoot);
}

function agentHasTeamReference(agent: AgentConfigWorkspaceAgent | null | undefined) {
  return Boolean(agent?.references?.some((reference) => reference.kind === "team"));
}

function agentHasRuntimeSignal(agent: AgentConfigWorkspaceAgent | null | undefined) {
  const runtimeState = String(agent?.runtimeStatus?.state || "").trim();
  return Boolean(runtimeState && runtimeState !== "idle") || (agent?.agentInboxPendingCount ?? 0) > 0;
}

function hasActionableHealthIssue(agent: AgentConfigWorkspaceAgent | null | undefined) {
  return Boolean(agent?.health?.some((issue) => issue.severity === "blocking" || issue.severity === "warning"));
}

function buildAgentManagementBrief(
  agent: AgentConfigWorkspaceAgent | null | undefined,
  copy: ReturnType<typeof agentsRouteCopy>,
  lang: "zh" | "en",
): AgentManagementBrief {
  const workSession = isWorkSessionAgent(agent);
  const items = workSession
    ? [
        { id: "model_prompt", label: copy.managementModelPrompt, complete: hasModelAndPromptConfiguration(agent), pane: "config" as const },
        { id: "tools", label: copy.managementTools, complete: hasToolPolicyConfiguration(agent), pane: "config" as const },
        { id: "workspace", label: copy.managementWorkspace, complete: hasWorkspaceConfiguration(agent), pane: "config" as const },
        { id: "runtime", label: copy.managementRuntime, complete: agentHasRuntimeSignal(agent), pane: "activity" as const },
      ]
    : [
        { id: "identity", label: copy.managementIdentity, complete: !requiresPersonaProfile(agent) || hasPersonaProfile(agent), pane: "config" as const },
        { id: "task", label: copy.managementTask, complete: !requiresTaskProfile(agent) || hasTaskProfile(agent), pane: "config" as const },
        { id: "tools", label: copy.managementTools, complete: hasToolPolicyConfiguration(agent), pane: "config" as const },
        { id: "membership", label: copy.managementMembership, complete: !requiresTeamMembership(agent) || agentHasTeamReference(agent), pane: "config" as const },
        { id: "runtime", label: copy.managementRuntime, complete: agentHasRuntimeSignal(agent), pane: "activity" as const },
      ];
  const actions: AgentManagementAction[] = [];
  if (workSession && !items[0].complete) {
    actions.push({ id: "model_prompt", label: copy.nextSetupModelPrompt, detail: copy.nextSetupModelPromptHint, pane: "config" });
  }
  if (!workSession && !items[0].complete) {
    actions.push({ id: "identity", label: copy.nextSetupIdentity, detail: copy.nextSetupIdentityHint, pane: "config" });
  }
  if (!workSession && !items[1].complete) {
    actions.push({ id: "task", label: copy.nextSetupTask, detail: copy.nextSetupTaskHint, pane: "config" });
  }
  if (!items.find((item) => item.id === "tools")?.complete) {
    actions.push({ id: "tools", label: copy.nextSetupTools, detail: copy.nextSetupToolsHint, pane: "config" });
  }
  if (workSession && !items.find((item) => item.id === "workspace")?.complete) {
    actions.push({ id: "workspace", label: copy.nextSetupWorkspace, detail: copy.nextSetupWorkspaceHint, pane: "config" });
  }
  if (!workSession && !items.find((item) => item.id === "membership")?.complete) {
    actions.push({
      id: "membership",
      label: copy.nextSetupMembership,
      detail: copy.nextSetupMembershipHint,
      pane: "config",
      route: agent?.agentId ? `/teams?agent=${encodeURIComponent(agent.agentId)}` : "/teams",
    });
  }
  if ((agent?.agentInboxPendingCount ?? 0) > 0) {
    actions.unshift({ id: "inbox", label: copy.nextHandleInbox, detail: copy.nextHandleInboxHint, pane: "activity" });
  }
  const completed = items.filter((item) => item.complete).length;
  const score = items.length ? Math.round((completed / items.length) * 100) : 0;
  return {
    score,
    completed,
    total: items.length,
    statusLabel: lang === "zh" ? `${score}% 完整` : `${score}% complete`,
    statusDetail: lang === "zh" ? `${completed}/${items.length} 项已就绪` : `${completed}/${items.length} ready`,
    items,
    actions: actions.slice(0, 3),
  };
}

function buildManagementFilterGroups(
  agents: AgentConfigWorkspaceAgent[],
  copy: ReturnType<typeof agentsRouteCopy>,
): AgentManagementFilterGroup[] {
  const activeAgents = agents.filter((agent) => agent.status !== "archived");
  const count = (predicate: (agent: AgentConfigWorkspaceAgent) => boolean) => activeAgents.filter(predicate).length;
  return [
    {
      id: "setup:persona",
      label: copy.managementFilterMissingPersona,
      count: count((agent) => requiresPersonaProfile(agent) && !hasPersonaProfile(agent)),
      description: copy.managementFilterMissingPersonaHint,
    },
    {
      id: "setup:task",
      label: copy.managementFilterMissingTask,
      count: count((agent) => requiresTaskProfile(agent) && !hasTaskProfile(agent)),
      description: copy.managementFilterMissingTaskHint,
    },
    {
      id: "setup:tools",
      label: copy.managementFilterMissingTools,
      count: count((agent) => !hasToolPolicyConfiguration(agent)),
      description: copy.managementFilterMissingToolsHint,
    },
    {
      id: "setup:membership",
      label: copy.managementFilterNoTeam,
      count: count((agent) => requiresTeamMembership(agent) && !agentHasTeamReference(agent)),
      description: copy.managementFilterNoTeamHint,
    },
    {
      id: "setup:inbox",
      label: copy.managementFilterPendingInbox,
      count: count((agent) => (agent.agentInboxPendingCount ?? 0) > 0),
      description: copy.managementFilterPendingInboxHint,
      healthCount: count((agent) => (agent.agentInboxPendingCount ?? 0) > 0),
    },
    {
      id: "setup:maintenance",
      label: copy.managementFilterMaintenance,
      count: count(hasActionableHealthIssue),
      description: copy.managementFilterMaintenanceHint,
      healthCount: count(hasActionableHealthIssue),
    },
  ];
}

function managementFilterMatches(agent: AgentConfigWorkspaceAgent, activeFilter: FilterId) {
  switch (activeFilter) {
    case "setup:persona":
      return requiresPersonaProfile(agent) && !hasPersonaProfile(agent);
    case "setup:task":
      return requiresTaskProfile(agent) && !hasTaskProfile(agent);
    case "setup:tools":
      return !hasToolPolicyConfiguration(agent);
    case "setup:membership":
      return requiresTeamMembership(agent) && !agentHasTeamReference(agent);
    case "setup:inbox":
      return (agent.agentInboxPendingCount ?? 0) > 0;
    case "setup:maintenance":
      return hasActionableHealthIssue(agent);
    default:
      return true;
  }
}

function buildAgentCapabilityPreview(
  draft: AgentToolPolicyDraft,
  tools: ToolRegistryItem[],
  copy: ReturnType<typeof agentsRouteCopy>,
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

function configDraftEqualsDraft(left: AgentConfigDraft, right: AgentConfigDraft) {
  return (
    left.displayName === right.displayName
    && sameAgentLlmBindings(left.llmBindings, right.llmBindings)
    && sameAgentReasoningEffortBySlot(left.reasoningEffortBySlot, right.reasoningEffortBySlot)
    && left.promptTemplateId === right.promptTemplateId
    && left.toolPolicyId === right.toolPolicyId
    && left.memoryPolicyId === right.memoryPolicyId
    && contextCompressionDraftEqualsDraft(left.contextCompressionPolicy, right.contextCompressionPolicy)
    && left.status === right.status
  );
}

function membershipDraftEqualsDraft(left: AgentModeMembershipDraft, right: AgentModeMembershipDraft) {
  return (Object.keys(right) as Array<keyof AgentModeMembershipDraft>).every((key) => left[key] === right[key]);
}

function personaDraftEqualsDraft(left: AgentPersonaDraft, right: AgentPersonaDraft) {
  const leftProfile = personaProfileFromDraft(left);
  const rightProfile = personaProfileFromDraft(right);
  return (
    leftProfile.gender === rightProfile.gender
    && leftProfile.age === rightProfile.age
    && leftProfile.pronouns === rightProfile.pronouns
    && leftProfile.personality === rightProfile.personality
    && leftProfile.communicationStyle === rightProfile.communicationStyle
    && leftProfile.background === rightProfile.background
    && sameStringSet(leftProfile.expertise, rightProfile.expertise)
    && leftProfile.collaborationPreference === rightProfile.collaborationPreference
    && leftProfile.identityNotes === rightProfile.identityNotes
  );
}

function taskDraftEqualsDraft(left: AgentTaskDraft, right: AgentTaskDraft) {
  const leftProfile = taskProfileFromDraft(left);
  const rightProfile = taskProfileFromDraft(right);
  return (
    leftProfile.mission === rightProfile.mission
    && sameStringSet(leftProfile.taskTypes, rightProfile.taskTypes)
    && leftProfile.responsibilities === rightProfile.responsibilities
    && leftProfile.preferredTasks === rightProfile.preferredTasks
    && leftProfile.avoidTasks === rightProfile.avoidTasks
    && leftProfile.successCriteria === rightProfile.successCriteria
    && leftProfile.deliverables === rightProfile.deliverables
    && leftProfile.constraints === rightProfile.constraints
    && leftProfile.handoffNotes === rightProfile.handoffNotes
  );
}

function createDraftFromWorkspace(workspace: AgentConfigWorkspace | undefined, bundles: ToolBundle[] = []): AgentCreateDraft {
  const firstModel = buildAgentModelChoices(workspace?.agentModelChoices ?? [])[0]?.modelId
    ?? workspace?.agentModelChoices?.[0]?.modelId
    ?? "";
  const firstPrompt = workspace?.promptTemplates?.find((item) => item.category === "chat") ?? workspace?.promptTemplates?.[0];
  return {
    displayName: "",
    llmBindings: firstModel ? { dialogue: { modelId: firstModel } } : {},
    primaryMode: "chat",
    roleKey: "",
    promptTemplateId: firstPrompt?.promptTemplateId || firstPrompt?.templateId || "prompt-chat-default",
    personaSummary: "",
    taskMission: "",
    selectedToolBundleIds: defaultCreateToolBundleIds(true, bundles),
    allowedTools: DEFAULT_SESSION_AGENT_ALLOWED_TOOLS.join(", "),
  };
}

function normalizeCreateDraftForWorkspace(draft: AgentCreateDraft, workspace: AgentConfigWorkspace | undefined, bundles: ToolBundle[] = []) {
  if (!workspace) {
    return draft;
  }
  const defaults = createDraftFromWorkspace(workspace, bundles);
  const modelIds = new Set(buildAgentModelChoices(workspace.agentModelChoices ?? []).map((choice) => choice.modelId));
  const promptIds = new Set((workspace.promptTemplates ?? []).map((template) => template.promptTemplateId || template.templateId || ""));
  const dialogueModelId = agentLlmSlotModelId(draft.llmBindings, FALLBACK_AGENT_LLM_SLOTS[0]);
  const defaultDialogueModelId = agentLlmSlotModelId(defaults.llmBindings, FALLBACK_AGENT_LLM_SLOTS[0]);
  const nextDialogueModelId = modelIds.size === 0 || modelIds.has(dialogueModelId) ? dialogueModelId : defaultDialogueModelId;
  const promptTemplateId = !draft.promptTemplateId || promptIds.size === 0 || promptIds.has(draft.promptTemplateId)
    ? draft.promptTemplateId || defaults.promptTemplateId
    : defaults.promptTemplateId;
  return {
    ...draft,
    llmBindings: updateAgentLlmSlotBinding(draft.llmBindings, FALLBACK_AGENT_LLM_SLOTS[0], nextDialogueModelId || defaultDialogueModelId),
    promptTemplateId,
  };
}

function commonBulkConfigValue(
  agents: AgentConfigWorkspaceAgent[],
  selector: (agent: AgentConfigWorkspaceAgent) => string,
) {
  if (!agents.length) {
    return "";
  }
  const first = selector(agents[0]);
  return agents.every((agent) => selector(agent) === first) ? first : "";
}

function bulkConfigValueMixed(
  agents: AgentConfigWorkspaceAgent[],
  selector: (agent: AgentConfigWorkspaceAgent) => string,
) {
  if (agents.length < 2) {
    return false;
  }
  const first = selector(agents[0]);
  return !agents.every((agent) => selector(agent) === first);
}

function bulkConfigDraftFromAgents(agents: AgentConfigWorkspaceAgent[]): AgentBulkConfigDraft {
  return {
    dialogueModelId: commonBulkConfigValue(agents, (agent) => agentLlmSlotModelId(agent.llmBindings, FALLBACK_AGENT_LLM_SLOTS[0])),
    promptTemplateId: commonBulkConfigValue(agents, (agent) => agent.promptTemplateId || ""),
    primaryMode: commonBulkConfigValue(agents, (agent) => agent.primaryMode || ""),
    roleKey: commonBulkConfigValue(agents, (agent) => agent.roleKey || ""),
  };
}

function bulkConfigApplyFields(apply: AgentBulkConfigApply) {
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

function bulkConfigPatchFromDraft(draft: AgentBulkConfigDraft, apply: AgentBulkConfigApply) {
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

function bulkConfigFieldReady(field: AgentBulkConfigField, draft: AgentBulkConfigDraft) {
  if (field === "roleKey") {
    return true;
  }
  return Boolean(draft[field].trim());
}

function bulkConfigReady(draft: AgentBulkConfigDraft, apply: AgentBulkConfigApply) {
  return (Object.keys(apply) as AgentBulkConfigField[]).some((field) => apply[field] && bulkConfigFieldReady(field, draft));
}

function createDraftReady(draft: AgentCreateDraft, bundles: ToolBundle[] = []) {
  const workSession = isWorkSessionCreateDraft(draft);
  const selectedPolicy = toolBundleSelectionToPolicy(draft.selectedToolBundleIds, bundles);
  const fallbackAllowedTools = bundles.length ? [] : expertiseFromDraft(draft.allowedTools);
  const configuredToolCount = selectedPolicy.allowedTools.length || fallbackAllowedTools.length;
  const hasToolPolicyChoice = selectedPolicy.selectedBundles.length > 0 || fallbackAllowedTools.length > 0;
  return Boolean(
    draft.displayName.trim()
    && agentLlmSlotModelId(draft.llmBindings, FALLBACK_AGENT_LLM_SLOTS[0])
    && draft.primaryMode.trim()
    && (workSession || draft.roleKey.trim())
    && draft.promptTemplateId.trim()
    && (workSession || draft.personaSummary.trim())
    && (workSession || draft.taskMission.trim())
    && (workSession ? hasToolPolicyChoice : configuredToolCount > 0)
  );
}

function slotForAgent(slots: Record<string, string> | undefined, agentId: string) {
  return Object.entries(slots ?? {}).find(([, value]) => value === agentId)?.[0] ?? "";
}

function membershipDraftFromWorkspace(
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

function membershipDraftEqualsWorkspace(
  draft: AgentModeMembershipDraft,
  workspace: AgentConfigWorkspace | undefined,
  agent: AgentConfigWorkspaceAgent | null | undefined,
) {
  const base = membershipDraftFromWorkspace(workspace, agent);
  return (Object.keys(base) as Array<keyof AgentModeMembershipDraft>).every((key) => draft[key] === base[key]);
}

function sortedIds(values: string[]) {
  return Array.from(new Set(values.map((item) => String(item || "").trim()).filter(Boolean))).sort();
}

function sameStringSet(left: string[], right: string[]) {
  const leftSorted = sortedIds(left);
  const rightSorted = sortedIds(right);
  return leftSorted.length === rightSorted.length && leftSorted.every((value, index) => value === rightSorted[index]);
}

function defaultToolPolicy(policyId = "default"): ToolPolicy {
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

function toolPolicyDraftFromAgent(agent: AgentConfigWorkspaceAgent | null | undefined): AgentToolPolicyDraft {
  return normalizeToolPolicyDraftForAgent({
    allowedTools: sortedIds(agent?.toolPolicy?.allowedTools ?? []),
    preferredTools: sortedIds(agent?.toolPolicy?.preferredTools ?? []),
    blockedTools: sortedIds(agent?.toolPolicy?.blockedTools ?? []),
    readScopes: sortedIds(agent?.toolPolicy?.readScopes ?? []),
    writeScopes: sortedIds(agent?.toolPolicy?.writeScopes ?? []),
  }, agent);
}

function toolGovernanceDraftFromAgent(agent: AgentConfigWorkspaceAgent | null | undefined): AgentToolGovernanceDraft {
  return {
    proposedByAgentId: agent?.agentId ?? "",
    reason: "",
    applyMode: "auto",
  };
}

function toolPolicyDraftEqualsAgent(draft: AgentToolPolicyDraft, agent: AgentConfigWorkspaceAgent | null | undefined) {
  const base = toolPolicyDraftFromAgent(agent);
  return (
    sameStringSet(draft.allowedTools, base.allowedTools)
    && sameStringSet(draft.preferredTools, base.preferredTools)
    && sameStringSet(draft.blockedTools, base.blockedTools)
    && sameStringSet(draft.readScopes, base.readScopes)
    && sameStringSet(draft.writeScopes, base.writeScopes)
  );
}

function toolPolicyDraftEqualsDraft(left: AgentToolPolicyDraft, right: AgentToolPolicyDraft) {
  return (
    sameStringSet(left.allowedTools, right.allowedTools)
    && sameStringSet(left.preferredTools, right.preferredTools)
    && sameStringSet(left.blockedTools, right.blockedTools)
    && sameStringSet(left.readScopes, right.readScopes)
    && sameStringSet(left.writeScopes, right.writeScopes)
  );
}

function toolPolicyDeltaFromDraft(draft: AgentToolPolicyDraft, agent: AgentConfigWorkspaceAgent | null | undefined) {
  const base = toolPolicyDraftFromAgent(agent);
  return {
    grantTools: draft.allowedTools.filter((tool) => !base.allowedTools.includes(tool)),
    revokeTools: base.allowedTools.filter((tool) => !draft.allowedTools.includes(tool)),
    blockTools: draft.blockedTools.filter((tool) => !base.blockedTools.includes(tool)),
    unblockTools: base.blockedTools.filter((tool) => !draft.blockedTools.includes(tool)),
  };
}

function toolPolicyDeltaCount(delta: ReturnType<typeof toolPolicyDeltaFromDraft>) {
  return delta.grantTools.length + delta.revokeTools.length + delta.blockTools.length + delta.unblockTools.length;
}

function toolBundleMeta(bundle: ToolBundle, lang: "zh" | "en") {
  const parts = [
    lang === "zh" ? `${bundle.toolCount} 个工具` : `${bundle.toolCount} tools`,
    lang === "zh" ? `${bundle.preferredToolCount} 个优先` : `${bundle.preferredToolCount} preferred`,
  ];
  if (bundle.highRiskToolCount > 0) {
    parts.push(lang === "zh" ? `${bundle.highRiskToolCount} 个高风险` : `${bundle.highRiskToolCount} high risk`);
  }
  if (bundle.explicitAllowToolCount > 0) {
    parts.push(lang === "zh" ? `${bundle.explicitAllowToolCount} 个需显式允许` : `${bundle.explicitAllowToolCount} explicit allow`);
  }
  return parts.join(" · ");
}

function defaultCreateToolBundleIds(workSession: boolean, bundles: ToolBundle[]) {
  const available = new Set(bundles.map((bundle) => bundle.bundleId));
  const preferred = workSession ? ["core"] : ["core", "research", "collaboration"];
  const selected = preferred.filter((bundleId) => available.has(bundleId));
  if (selected.length) {
    return selected;
  }
  return bundles[0]?.bundleId ? [bundles[0].bundleId] : [];
}

function toolBundleIdsForModeChange(draft: AgentCreateDraft, nextPrimaryMode: string, bundles: ToolBundle[]) {
  const currentDefaults = defaultCreateToolBundleIds(isWorkSessionCreateDraft(draft), bundles);
  const hasCustomSelection = draft.selectedToolBundleIds.length > 0 && !sameStringSet(draft.selectedToolBundleIds, currentDefaults);
  if (hasCustomSelection) {
    return draft.selectedToolBundleIds;
  }
  const nextWorkSession = !String(nextPrimaryMode || "").trim() || nextPrimaryMode === "chat";
  return defaultCreateToolBundleIds(nextWorkSession, bundles);
}

function toolBundleSelectionToPolicy(bundleIds: string[], bundles: ToolBundle[]) {
  const selectedIds = new Set(sortedIds(bundleIds));
  const selectedBundles = bundles.filter((bundle) => selectedIds.has(bundle.bundleId));
  const allowed = new Set<string>();
  const preferred = new Set<string>();
  for (const bundle of selectedBundles) {
    for (const tool of bundle.toolNames ?? []) {
      allowed.add(tool);
    }
    for (const tool of bundle.preferredToolNames ?? []) {
      if ((bundle.toolNames ?? []).includes(tool)) {
        preferred.add(tool);
      }
    }
  }
  return {
    selectedBundles,
    allowedTools: sortedIds(Array.from(allowed)),
    preferredTools: sortedIds(Array.from(preferred).filter((tool) => allowed.has(tool))),
  };
}

function createToolBundleSummary(
  bundleIds: string[],
  bundles: ToolBundle[],
  lang: "zh" | "en",
  requiredAllowedTools: string[] = [],
  requiredPreferredTools: string[] = [],
) {
  const policy = toolBundleSelectionToPolicy(bundleIds, bundles);
  const allowedTools = sortedIds([...requiredAllowedTools, ...policy.allowedTools]);
  const preferredTools = sortedIds([...requiredPreferredTools, ...policy.preferredTools].filter((tool) => allowedTools.includes(tool)));
  const highRiskCount = policy.selectedBundles.reduce((total, bundle) => total + Math.max(0, bundle.highRiskToolCount || 0), 0);
  const explicitAllowCount = policy.selectedBundles.reduce((total, bundle) => total + Math.max(0, bundle.explicitAllowToolCount || 0), 0);
  const bundleLabels = policy.selectedBundles.map((bundle) => bundle.label);
  const label = bundleLabels.length
    ? bundleLabels.join(" / ")
    : requiredAllowedTools.length ? (lang === "zh" ? "会话推荐默认" : "Recommended session default") : (lang === "zh" ? "未选择工具包" : "No package selected");
  return {
    ...policy,
    allowedTools,
    preferredTools,
    bundleLabels,
    highRiskCount,
    explicitAllowCount,
    label,
    meta: [
      lang === "zh" ? `${allowedTools.length} 个允许工具` : `${allowedTools.length} allowed tools`,
      lang === "zh" ? `${preferredTools.length} 个优先工具` : `${preferredTools.length} preferred tools`,
      highRiskCount ? (lang === "zh" ? `${highRiskCount} 个高风险` : `${highRiskCount} high risk`) : "",
      explicitAllowCount ? (lang === "zh" ? `${explicitAllowCount} 个需显式授权` : `${explicitAllowCount} explicit allow`) : "",
    ].filter(Boolean).join(" · "),
  };
}

function toolPolicyMode(draft: AgentToolPolicyDraft, toolName: string): ToolPolicyMode {
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

function governanceRiskLabel(value: string, lang: "zh" | "en") {
  const normalized = String(value || "").trim();
  const zh: Record<string, string> = {
    low: "低风险",
    medium: "中风险",
    high: "高风险",
  };
  const en: Record<string, string> = {
    low: "Low risk",
    medium: "Medium risk",
    high: "High risk",
  };
  return ((lang === "zh" ? zh : en)[normalized] ?? normalized) || "-";
}

function governanceStatusLabel(value: string, lang: "zh" | "en") {
  const normalized = String(value || "").trim();
  const zh: Record<string, string> = {
    pending_review: "待审批",
    applied: "已应用",
    rejected: "已拒绝",
  };
  const en: Record<string, string> = {
    pending_review: "Pending review",
    applied: "Applied",
    rejected: "Rejected",
  };
  return ((lang === "zh" ? zh : en)[normalized] ?? normalized) || "-";
}

function governanceDeltaSummary(request: AgentToolGovernanceRequest | undefined, lang: "zh" | "en") {
  const delta = request?.policyDelta;
  if (!delta) {
    return "-";
  }
  const parts = [
    `${lang === "zh" ? "授权" : "Grant"} ${delta.grantTools?.length ?? 0}`,
    `${lang === "zh" ? "撤销" : "Revoke"} ${delta.revokeTools?.length ?? 0}`,
    `${lang === "zh" ? "禁用" : "Block"} ${delta.blockTools?.length ?? 0}`,
    `${lang === "zh" ? "解除禁用" : "Unblock"} ${delta.unblockTools?.length ?? 0}`,
  ];
  return parts.join(" · ");
}

function toolPolicyModeLabel(mode: ToolPolicyMode, lang: "zh" | "en") {
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

function toolCategoryLabel(category: string, fallback: string | undefined, lang: "zh" | "en") {
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

function toolTierLabel(tier: string, lang: "zh" | "en") {
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

function fallbackToolBundleLabel(lang: "zh" | "en") {
  return lang === "zh" ? "未归入工具包" : "Unbundled tools";
}

function groupPolicyToolsByBundle(
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

function defaultMemoryPolicy(policyId = ""): MemoryPolicy {
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

function memoryPolicyDraftFromAgent(agent: AgentConfigWorkspaceAgent | null | undefined): AgentMemoryPolicyDraft {
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

function memoryPolicyDraftEqualsAgent(draft: AgentMemoryPolicyDraft, agent: AgentConfigWorkspaceAgent | null | undefined) {
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

function memoryPolicyDraftEqualsDraft(left: AgentMemoryPolicyDraft, right: AgentMemoryPolicyDraft) {
  return (
    sameStringSet(left.readSharedGroups, right.readSharedGroups)
    && sameStringSet(left.writeSharedGroups, right.writeSharedGroups)
    && sameStringSet(left.readKnowledgeBaseIds, right.readKnowledgeBaseIds)
    && sameStringSet(left.proposeKnowledgeBaseIds, right.proposeKnowledgeBaseIds)
    && sameStringSet(left.reviewKnowledgeBaseIds, right.reviewKnowledgeBaseIds)
    && sameStringSet(left.rateKnowledgeBaseIds, right.rateKnowledgeBaseIds)
  );
}

function sharedGroupCandidates(workspace: AgentConfigWorkspace | undefined, selectedAgent: AgentConfigWorkspaceAgent | null | undefined) {
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

function clampNumber(value: unknown, minimum: number, maximum: number, fallback: number) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return fallback;
  }
  return Math.max(minimum, Math.min(maximum, Math.trunc(parsed)));
}

function delegationPolicyDraftFromAgent(agent: AgentConfigWorkspaceAgent | null | undefined): AgentDelegationPolicyDraft {
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

function delegationPolicyDraftEqualsAgent(draft: AgentDelegationPolicyDraft, agent: AgentConfigWorkspaceAgent | null | undefined) {
  const base = delegationPolicyDraftFromAgent(agent);
  return (
    draft.allowSubagents === base.allowSubagents &&
    draft.maxConcurrent === base.maxConcurrent &&
    draft.maxDepth === base.maxDepth &&
    draft.allowWakeMessages === base.allowWakeMessages &&
    sameStringSet(draft.allowedContextModes, base.allowedContextModes)
  );
}

function supervisionPolicyDraftFromAgent(agent: AgentConfigWorkspaceAgent | null | undefined): AgentSupervisionPolicyDraft {
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

function supervisionPolicyDraftEqualsAgent(draft: AgentSupervisionPolicyDraft, agent: AgentConfigWorkspaceAgent | null | undefined) {
  const base = supervisionPolicyDraftFromAgent(agent);
  return (
    draft.supervisionEnabled === base.supervisionEnabled &&
    draft.requiresReview === base.requiresReview &&
    draft.reviewMode === base.reviewMode &&
    draft.evidenceLevel === base.evidenceLevel
  );
}

function delegationPolicyDraftEqualsDraft(left: AgentDelegationPolicyDraft, right: AgentDelegationPolicyDraft) {
  return (
    left.allowSubagents === right.allowSubagents &&
    left.maxConcurrent === right.maxConcurrent &&
    left.maxDepth === right.maxDepth &&
    left.allowWakeMessages === right.allowWakeMessages &&
    sameStringSet(left.allowedContextModes, right.allowedContextModes)
  );
}

function supervisionPolicyDraftEqualsDraft(left: AgentSupervisionPolicyDraft, right: AgentSupervisionPolicyDraft) {
  return (
    left.supervisionEnabled === right.supervisionEnabled &&
    left.requiresReview === right.requiresReview &&
    left.reviewMode === right.reviewMode &&
    left.evidenceLevel === right.evidenceLevel
  );
}

function metadataString(agent: AgentConfigWorkspaceAgent | null | undefined, key: string) {
  const value = agent?.metadata?.[key];
  if (typeof value === "string") {
    return value.trim();
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return "";
}

const metadataText = metadataString;

function metadataFlag(agent: AgentConfigWorkspaceAgent | null | undefined, key: string) {
  const value = agent?.metadata?.[key];
  if (typeof value === "boolean") {
    return value;
  }
  return ["1", "true", "yes"].includes(metadataString(agent, key).toLowerCase());
}

function agentArchiveProtected(agent: AgentConfigWorkspaceAgent | null | undefined) {
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

function agentConfigPanes(copy: ReturnType<typeof agentsRouteCopy>, agent: AgentConfigWorkspaceAgent | null): Array<{
  id: AgentConfigPaneId;
  label: string;
  count: number;
}> {
  const configCount = (agent?.health.length ?? 0)
    + (agent?.toolPolicy?.allowedTools?.length ?? 0)
    + (agent?.toolPolicy?.blockedTools?.length ?? 0)
    + (agent?.memoryPolicy?.readSharedGroups?.length ?? 0)
    + (agent?.memoryPolicy?.writeSharedGroups?.length ?? 0)
    + (agent?.memoryPolicy?.readKnowledgeBaseIds?.length ?? 0)
    + (agent?.memoryPolicy?.proposeKnowledgeBaseIds?.length ?? 0)
    + (agent?.memoryPolicy?.reviewKnowledgeBaseIds?.length ?? 0)
    + (agent ? uniqueModes(agent).length : 0)
    + (agent?.references.length ?? 0);
  return [
    { id: "overview", label: copy.overviewPane, count: agent ? uniqueModes(agent).length : 0 },
    { id: "config", label: copy.configTitle, count: configCount },
    { id: "activity", label: copy.activityPane, count: (agent?.agentInboxPendingCount ?? 0) + (agent?.groupContextEvents?.length ?? 0) },
  ];
}

function agentsRouteCopy(lang: "zh" | "en") {
  return lang === "zh"
    ? {
        eyebrow: "Agent Center",
        title: "Agent 中心",
        subtitle: "统一查看长期 Agent 的身份、模型、提示词、工具、记忆、使用位置和健康状态。",
        refresh: "刷新",
        loading: "正在整理 Agent 配置...",
        loadFailed: "Agent 配置加载失败",
        search: "搜索 Agent、模型、提示词、模式或引用",
        agentFilters: "Agent 筛选",
        allAgents: "全部 Agent",
        activeAgents: "可用 Agent",
        bulkSelected: "已选",
        bulkSelectVisible: "选择当前列表",
        bulkClear: "清空",
        bulkPromptLabel: "批量提示词",
        bulkPromptPlaceholder: "选择提示词",
        bulkApplyPrompt: "批量应用",
        bulkArchive: "批量归档",
        bulkPurge: "批量彻底删除",
        bulkWorking: "批量处理中...",
        bulkNoSelection: "请先选择 Agent。",
        bulkNoPrompt: "请先选择要应用的提示词模板。",
        bulkNoConfigFields: "请选择要批量应用的配置字段。",
        sessionAgentColumn: "会话入口 Agent",
        sessionAgentColumnHint: "直接承载项目开发、调试和审计对话的 Agent。",
        teamAgentColumnHint: "该团队当前引用的非会话 Agent。",
        nonSessionAgentColumn: "非会话 Agent",
        nonSessionAgentColumnHint: "未归入当前团队索引的知识库、系统或平台服务 Agent。",
        bulkEditTitle: "批量编辑",
        bulkEditSelected: "已选 Agent",
        bulkEditMixed: "混合值",
        bulkApplyField: "应用",
        bulkDialogueModel: "对话模型",
        bulkPrimaryMode: "身份模式",
        bulkRoleKey: "角色键",
        bulkConfigReset: "重置面板",
        bulkApplyConfig: "保存批量配置",
        bulkArchiveConfirm: "确认安全归档已选 Agent？受保护或已归档项会自动跳过。",
        bulkPurgeConfirm: "确认彻底删除已选的已归档 Agent？活跃或受保护项会自动跳过；该操作会删除 Agent 私有工作区，直连历史仅保留为已删除 Agent 历史。",
        bulkSkippedArchived: "已归档，跳过",
        bulkSkippedActive: "仍是活跃状态，请先安全归档",
        bulkSkippedProtected: "受保护，跳过",
        bulkArchiveResult: "批量归档完成",
        bulkPurgeResult: "批量彻底删除完成",
        bulkPromptResult: "批量提示词更新完成",
        bulkConfigResult: "批量配置更新完成",
        filterSections: {
          status: "状态",
          boundary: "Agent 身份",
          team_index: "团队索引",
          source_scope: "来源范围",
          mode: "运行模式",
          reference: "引用关系",
          management: "工作队列",
        },
        moreFilters: "更多筛选",
        groupLabels: {
          active: "可用 Agent",
          needs_review: "需要处理",
          archived: "已归档",
          work_session: "会话入口 Agent",
          team_role: "团队/科研角色 Agent",
          system_role: "系统进化 Agent",
          service_role: "平台服务 Agent",
          chat: "会话模式",
          research: "科研模式",
          supervised_evolution: "监督进化模式",
          self_evolution: "自进化模式",
          group_chat: "群聊引用",
          team: "团队引用",
        } as Record<string, string>,
        groupDescriptions: {
          active: "当前可被业务页面引用或调度的 Agent。",
          needs_review: "存在阻塞或警告健康项的可用 Agent。",
          archived: "只保留历史数据、不再进入可用池的 Agent。",
          work_session: "用于项目开发、调试、实现和审计的 Codex-like 会话入口。",
          team_role: "拥有人物/任务档案，并进入团队或科研组织结构的 Agent。",
          system_role: "由自进化、监督进化等系统流程固定管理的 Agent。",
          service_role: "负责知识、工具、记忆或平台治理的平台服务 Agent。",
          group_chat: "被一个或多个群聊引用的 Agent。",
          team: "被一个或多个团队画布引用的 Agent。",
        } as Record<string, string>,
        managementFilterMissingPersona: "未配置人物",
        managementFilterMissingPersonaHint: "缺少性别、年龄、沟通风格、背景或专长等人物档案。",
        managementFilterMissingTask: "未配置任务",
        managementFilterMissingTaskHint: "缺少使命、职责、适合任务、完成标准或交接说明。",
        managementFilterMissingTools: "工具使用待确认",
        managementFilterMissingToolsHint: "未显式配置可用、优先或禁用工具；该 Agent 当前不会获得隐藏默认工具。",
        managementFilterNoTeam: "无团队归属",
        managementFilterNoTeamHint: "尚未被任何团队画布引用，适合继续分配组织位置。",
        managementFilterPendingInbox: "有待处理消息",
        managementFilterPendingInboxHint: "Agent inbox 仍有待处理消息，需要进入运行页处理。",
        managementFilterMaintenance: "需处理问题",
        managementFilterMaintenanceHint: "存在阻塞或警告级问题，需要进入维护区处理。",
        createAgent: "新增 Agent",
        createAgentTitle: "新增 Agent",
        createAgentHint: "会话入口 Agent 用于项目开发和调试，按 Codex-like 配置创建；团队/科研 Agent 才需要人物摘要、任务使命和团队归属。",
        createAgentName: "功能名",
        createAgentNamePlaceholder: "例如：科研复核 Agent",
        createAgentRole: "角色键",
        createAgentRolePlaceholder: "必填，例如 research_reviewer",
        createAgentPersonaSummary: "人物摘要",
        createAgentPersonaPlaceholder: "例如：冷静、细致，负责把结论拆成可验证证据。",
        createAgentTaskMission: "任务使命",
        createAgentTaskMissionPlaceholder: "例如：复核科研结论，指出证据缺口并给出下一步建议。",
        createAgentAllowedTools: "允许工具",
        createAgentAllowedToolsPlaceholder: "例如：agent_message_tool, web_search_tool",
        createAgentToolBundles: "工具包",
        createAgentToolBundlesHint: "直接选择适合这个 Agent 的能力包；创建后仍可在工具能力里细调单个工具。",
        createAgentToolBundlePreview: "创建后工具能力",
        createAgentToolBundleEmpty: "还没有选择工具包。",
        cancelCreate: "取消",
        creatingAgent: "创建中...",
        resetAgent: "重置调试状态",
        resettingAgent: "重置中...",
        resetAgentTitle: "调试重置",
        resetAgentHint: "默认清理该 Agent 的运行痕迹，并重建一个干净的直连会话；不会删除/归档 Agent，也不会移出团队、群聊或模式绑定。",
        resetAgentConfirm: "确认重置 {name}？默认会清理运行痕迹并重建直连会话，团队、群聊和模式绑定会保留；勾选的高级项会恢复为空档案或默认策略。",
        resetAgentSuccess: "已重置 Agent 调试状态",
        resetClearRuntimeState: "清理运行痕迹",
        resetClearRuntimeStateHint: "删除该 Agent 私有工作区的 inbox、outbox、events、tmp、logs、runs、scratch、artifacts；保留 memory。",
        resetDirectSession: "重建直连会话",
        resetDirectSessionHint: "删除旧用户直聊会话和消息，创建新的空 directSessionId，并切到新会话；不影响群聊历史。",
        resetPersonaProfile: "重置人物档案",
        resetPersonaProfileHint: "清空性别、年龄、称谓、性格、背景、专长、沟通风格等身份描述。",
        resetTaskProfile: "重置任务档案",
        resetTaskProfileHint: "清空使命、职责、适合/不适合任务、完成标准、交付物和交接说明。",
        resetToolPolicy: "重置工具能力",
        resetToolPolicyHint: "恢复为默认工具设置，移除该 Agent 私有工具允许、优先、禁用和保存位置调整。",
        resetMemoryPolicy: "重置记忆设置",
        resetMemoryPolicyHint: "恢复该 Agent 私有记忆配置；不删除 memory 目录里的记忆内容。",
        resetRuntimePolicy: "重置运行策略",
        resetRuntimePolicyHint: "恢复协作助手委派、并发深度、唤醒和监督审批策略为默认值。",
        archiveAgent: "安全归档",
        archivingAgent: "归档中...",
        archiveAgentTitle: "安全删减",
        archiveAgentHint: "归档会从默认模式、群聊成员和可选池中移除该 Agent，但保留会话、记忆、日志和工作区。",
        archiveConfirm: "确认归档 {name}？这会隐藏该 Agent 并清理模式/群聊引用，但不会物理删除数据。",
        purgeAgent: "彻底删除",
        purgingAgent: "删除中...",
        purgeAgentTitle: "彻底删除",
        purgeAgentHint: "会从 AgentDirectory 删除记录，并移除该 Agent 的私有工作区、记忆、inbox 和事件文件；直连历史会保留为已删除 Agent 的历史记录。",
        purgeConfirm: "彻底删除 {name}？这个操作不可恢复，会删除该 Agent 的私有工作区和历史文件。",
        protectedAgent: "受保护 Agent 不能归档",
        archiveProtection: "归档保护",
        archiveProtectionTitle: "核心保护",
        archiveProtectionHint: "这是科研团队核心 Agent，当前状态仍是活跃；系统只是在这里禁止归档操作，不代表它已经归档。",
        archivedAgents: "已归档",
        teams: "团队",
        healthIssues: "需处理问题",
        healthIssueShort: "问题",
        statusReminders: "状态提醒",
        statusReminderShort: "提醒",
        workspaceHealthStatus: "工作区健康状态",
        chatRooms: "群聊",
        inbox: "待处理消息",
        runningAgents: "运行中",
        blockedAgents: "阻塞/失败",
        model: "模型槽位",
        llmSlots: "Agent 模型槽位",
        llmSlotsHint: "按 Agent 自己配置对话、心智模型、摘要、子 Agent 和视觉等 LLM 槽位；设置页只维护模型库资产。",
        requiredSlot: "必填",
        optionalSlot: "可选",
        inheritDialogueModel: "未单独指定",
        reasoningEffort: "思考强度",
        reasoningEffortDefault: "默认",
        reasoningEffortLow: "低",
        reasoningEffortMedium: "中",
        reasoningEffortHigh: "高",
        prompt: "提示词",
        tools: "工具能力",
        memory: "记忆设置",
        contextCompressionPolicy: "上下文压缩",
        contextCompressionInherit: "继承全局",
        contextCompressionCustom: "Agent 自定义",
        contextCompressionEnabled: "启用压缩",
        contextCompressionMaxTokenLimit: "压缩阈值",
        contextCompressionMaxCount: "每会话上限",
        contextCompressionThresholds: "触发阈值 %",
        contextCompressionSummaryChars: "摘要长度",
        contextCompressionKeepAi: "保留 AI 消息",
        contextCompressionPreserveErrors: "保留错误",
        contextCompressionExtractDecisions: "提取决策",
        contextCompressionEffective: "压缩触发阈值",
        contextCompressionWindow: "模型窗口",
        contextCompressionSourceGlobal: "继承全局策略",
        contextCompressionSourceCustom: "当前 Agent 自定义策略",
        territory: "工作空间",
        privateTerritory: "私人工作区",
        sharedTerritory: "共享资料区",
        writeBoundary: "默认保存位置",
        territoryLegacy: "历史会话路径",
        context: "上下文",
        run: "运行",
        communication: "通信",
        delegation: "协作助手",
        modeMembership: "使用位置",
        references: "引用位置",
        sessions: "会话 / 群聊 / 工作区",
        logs: "运行记录与日志",
        noAgents: "没有匹配当前筛选的 Agent。",
        selectAgent: "选择一个 Agent 查看统一配置卡片。",
        readOnly: "只读总览",
        policyPending: "协作策略待配置",
        noIssues: "当前没有需处理问题或提醒。",
        routeHint: "这张卡片是 Agent 的唯一配置点；业务页面只引用这里的 Agent。",
        returnBannerTitle: "返回跳转前页面",
        returnBannerHint: "你是从其他页面进入 Agent 管理中心的；配置完成后可直接回到原页面继续。",
        managementBriefTitle: "管理完整度",
        managementBriefHint: "按当前 Agent 身份检查必要配置；会话入口 Agent 不要求人物档案和团队归属。",
        managementIdentity: "人物",
        managementTask: "任务",
        managementModelPrompt: "模型/指令",
        managementWorkspace: "工作区",
        managementTools: "工具",
        managementMembership: "归属",
        managementRuntime: "运行",
        nextActionsTitle: "下一步建议",
        nextAllReady: "关键配置已齐，可以直接在团队或会话中使用。",
        nextSetupModelPrompt: "配置模型与项目指令",
        nextSetupModelPromptHint: "会话入口 Agent 需要先确定 LLM 和提示词/项目指令入口。",
        nextSetupIdentity: "补齐人物档案",
        nextSetupIdentityHint: "让顾问和用户知道这个 Agent 的性格、背景、专长与协作方式。",
        nextSetupTask: "补齐任务档案",
        nextSetupTaskHint: "明确它适合承担什么任务、产出什么交付物、何时需要交接。",
        nextSetupTools: "配置工具能力包",
        nextSetupToolsHint: "选择核心/科研/协作等工具包，并检查高风险工具授权。",
        nextSetupWorkspace: "检查工作区边界",
        nextSetupWorkspaceHint: "确认项目根、私人工作区和共享写入权限符合开发任务需要。",
        nextSetupMembership: "绑定团队归属",
        nextSetupMembershipHint: "把它放进团队画布，形成可观察的组织结构。",
        nextHandleInbox: "处理待办消息",
        nextHandleInboxHint: "运行态里有其他 Agent 或群聊留下的消息，先处理再继续配置。",
        capabilityPreviewTitle: "实际能力预览",
        capabilityPreviewHint: "这里按当前草稿估算 Agent 真正能用、优先用、被禁用和需要注意的工具边界。",
        effectiveAllowedTools: "实际允许",
        highRiskAllowedTools: "高风险允许",
        explicitAllowedTools: "显式授权",
        writeBoundaryPreview: "保存位置",
        maintenanceTitle: "维护与危险操作",
        maintenanceHint: "调试重置、归档和彻底删除集中在这里；普通身份、任务、工具配置不和删除动作混在一起。",
        healthReason: "原因",
        healthNextStep: "下一步",
        toolPolicyPickerHint: "选择工具能力模板；具体允许、优先、禁用哪些工具，请到“策略”页调整。",
        memoryPolicyPickerHint: "选择记忆范围模板；具体可查看/可保存的共享组，请到“策略”页调整。",
        editAvatar: "编辑头像",
        avatarEditorTitle: "Agent 头像",
        avatarEditorHint: "头像写入 AgentDirectory，Chat、团队和群聊引用会同步使用。",
        uploadAvatar: "上传新头像",
        uploadingAvatar: "上传中...",
        resetDefaultAvatar: "使用默认头像",
        resettingAvatar: "恢复中...",
        avatarLibrary: "头像库",
        avatarLibraryLoading: "正在读取头像库...",
        avatarLibraryEmpty: "workspace/avatars 暂无可用头像。",
        avatarUpdateSuccess: "已更新 Agent 头像",
        personaTitle: "人物档案",
        personaHint: "人物档案写入 AgentDirectory，并进入 Agent 运行上下文；顾问 Agent 可按说明自行设计团队人选。",
        savePersona: "保存人物",
        savingPersona: "保存人物中...",
        personaUpdateSuccess: "已保存 Agent 人物档案",
        taskTitle: "任务档案",
        taskHint: "任务档案写入 AgentDirectory，并进入 Agent 运行上下文；它只描述适配任务和职责边界，不自动推荐或调度。",
        saveTask: "保存任务",
        savingTask: "保存任务中...",
        taskUpdateSuccess: "已保存 Agent 任务档案",
        mission: "任务使命",
        taskTypes: "任务类型",
        taskTypesPlaceholder: "用逗号分隔，例如 文献审查, 实验设计, 代码评审",
        responsibilities: "职责范围",
        preferredTasks: "适合任务",
        avoidTasks: "不适合任务",
        successCriteria: "完成标准",
        deliverables: "交付物",
        constraints: "约束条件",
        handoffNotes: "交接说明",
        gender: "性别",
        age: "年龄",
        pronouns: "称谓",
        personality: "性格",
        communicationStyle: "沟通风格",
        background: "背景",
        expertise: "专长",
        collaborationPreference: "协作偏好",
        identityNotes: "人物说明",
        expertisePlaceholder: "用逗号分隔，例如 规划, 统计, 评审",
        overviewPane: "总览",
        policiesPane: "策略",
        membershipPane: "归属",
        activityPane: "运行",
        configTitle: "配置",
        saveConfig: "保存配置",
        resetConfig: "重置",
        savingConfig: "保存中...",
        status: "状态",
        membershipTitle: "使用位置",
        saveMembership: "保存归属",
        savingMembership: "保存归属中...",
        chatRoomMembership: "群聊成员",
        noChatRooms: "还没有可配置的群聊。",
        toolPolicyTitle: "工具能力",
        saveToolPolicy: "保存工具",
        savingToolPolicy: "保存工具中...",
        toolBundlesTitle: "按工具包配置",
        toolBundlesHint: "先选适合这个 Agent 的工具包，再在下方微调单个工具；会话 Agent 默认选基础包，也可以手动关闭。",
        applyBundle: "叠加",
        replaceWithBundle: "重置为此包",
        preferredTools: "优先",
        toolGovernanceTitle: "顾问权限治理",
        toolGovernanceHint: "把当前工具草稿作为受控治理请求提交；低风险可自动应用，高风险会进入待审批。",
        toolGovernanceSubmit: "提交治理请求",
        toolGovernanceSubmitting: "提交中...",
        toolGovernanceReason: "变更理由",
        toolGovernanceReasonPlaceholder: "说明为什么这个 Agent 需要这些工具能力",
        toolGovernanceApplyAuto: "低风险自动应用",
        toolGovernanceApplyReview: "全部走审批",
        toolGovernancePending: "待审批请求",
        toolGovernanceHistory: "最近治理记录",
        toolGovernanceApprove: "批准",
        toolGovernanceReject: "拒绝",
        toolGovernanceNoDelta: "先调整工具配置草稿，再提交治理请求。",
        toolGovernanceEmpty: "还没有工具治理记录。",
        toolGovernanceSuccess: "工具治理请求已记录",
        toolGovernanceResolved: "工具治理请求已处理",
        toolSearch: "筛选工具",
        noTools: "当前没有可配置的工具。",
        toolCategoryCount: "工具包",
        toolHighRisk: "高风险",
        toolTags: "能力标签",
        allowedTools: "允许",
        blockedTools: "禁用",
        inheritedTools: "未允许",
        workspaceWriteScopes: "保存位置",
        privateWriteScope: "私人工作区",
        sharedWriteScope: "共享空间",
        sharedWriteHint: "开启后该 Agent 可以把工具产物写入 workspace/shared。",
        memoryPolicyTitle: "记忆设置",
        saveMemoryPolicy: "保存记忆",
        savingMemoryPolicy: "保存记忆中...",
        readSharedGroups: "可查看共享组",
        writeSharedGroups: "可保存共享组",
        readKnowledgeBaseIds: "可查看知识库",
        proposeKnowledgeBaseIds: "可提交知识库",
        reviewKnowledgeBaseIds: "可审核知识库",
        rateKnowledgeBaseIds: "可评级知识库",
        knowledgeBasePlaceholder: "输入知识库 ID，例如 kb-research",
        noKnowledgeBaseIds: "未限定知识库，默认按团队成员和角色判定。",
        addSharedGroup: "添加",
        sharedGroupPlaceholder: "输入共享组，例如 project",
        noSharedGroups: "未配置共享组。",
        delegationPolicyTitle: "委托策略",
        supervisionPolicyTitle: "监督策略",
        saveRuntimePolicy: "保存运行策略",
        savingRuntimePolicy: "保存运行策略中...",
        allowSubagents: "允许协作助手",
        maxConcurrent: "最大并发",
        allowWakeMessages: "允许唤醒消息",
        openSession: "打开会话",
        openLogs: "查看日志",
        focusMessage: "查看消息",
        allowedContextModes: "上下文模式",
        supervisionEnabled: "启用监督",
        requiresReview: "需要复核",
        reviewMode: "复核模式",
        evidenceLevel: "证据等级",
        chatDefault: "会话默认",
        chatAvailable: "会话可选",
        researchPool: "科研池",
        supervisedSlot: "监督槽位",
        selfEvolutionSlot: "自进化槽位",
        noSlot: "不占用槽位",
        runHistoryTitle: "运行历史",
        runtimeStatus: "运行态",
        runtimeFocus: "当前运行焦点",
        runtimeReason: "状态来源",
        runtimeLatestRun: "最近运行",
        runtimeUpdated: "更新时间",
        runtimeNextStep: "建议下一步",
        runtimeEvidence: "日志证据",
        runHistoryLoading: "正在读取运行历史...",
        noRunHistory: "还没有运行或协作助手记录。",
        inboxTitle: "Inbox 待办",
        inboxLoading: "正在读取待办消息...",
        inboxEmpty: "当前没有待处理消息。",
        consumeMessage: "标记已处理",
        consumeAllMessages: "全部标记已处理",
        consumingMessage: "处理中...",
        handleInboxNow: "处理 Inbox",
        wakeStatus: "唤醒状态",
        activityTimeline: "活动时间线",
        activityTimelineEmpty: "还没有可汇总的运行、消息或上下文事件。",
        subAgentRuns: "协作助手运行",
        parentRuns: "主运行",
        supervisedRole: "监督角色",
        maxDepth: "最大深度",
      }
    : {
        eyebrow: "Agent Center",
        title: "Agent Center",
        subtitle: "Read all persistent Agents, their models, prompts, policies, mode membership, and health in one place.",
        refresh: "Refresh",
        loading: "Loading Agent config...",
        loadFailed: "Agent config failed to load",
        search: "Search agents, models, prompts, modes, or references",
        agentFilters: "Agent filters",
        allAgents: "All Agents",
        activeAgents: "Available Agents",
        bulkSelected: "Selected",
        bulkSelectVisible: "Select visible",
        bulkClear: "Clear",
        bulkPromptLabel: "Bulk prompt",
        bulkPromptPlaceholder: "Choose prompt",
        bulkApplyPrompt: "Apply",
        bulkArchive: "Bulk archive",
        bulkPurge: "Bulk delete",
        bulkWorking: "Working...",
        bulkNoSelection: "Select Agents first.",
        bulkNoPrompt: "Choose a prompt template first.",
        bulkNoConfigFields: "Select at least one config field to apply.",
        sessionAgentColumn: "Session entry Agents",
        sessionAgentColumnHint: "Agents that directly carry project development, debugging, and audit conversations.",
        teamAgentColumnHint: "Non-session Agents referenced by this team.",
        nonSessionAgentColumn: "Non-session Agents",
        nonSessionAgentColumnHint: "Knowledge, system, or platform-service Agents not grouped by the current team indexes.",
        bulkEditTitle: "Bulk edit",
        bulkEditSelected: "Selected Agents",
        bulkEditMixed: "Mixed value",
        bulkApplyField: "Apply",
        bulkDialogueModel: "Dialogue model",
        bulkPrimaryMode: "Identity mode",
        bulkRoleKey: "Role key",
        bulkConfigReset: "Reset panel",
        bulkApplyConfig: "Save bulk config",
        bulkArchiveConfirm: "Archive the selected Agents? Protected or already archived items will be skipped.",
        bulkPurgeConfirm: "Permanently delete the selected archived Agents? Active or protected Agents will be skipped; private workspaces are removed and direct-session history is kept as deleted-Agent history.",
        bulkSkippedArchived: "Already archived; skipped",
        bulkSkippedActive: "Still active; archive safely first",
        bulkSkippedProtected: "Protected; skipped",
        bulkArchiveResult: "Bulk archive finished",
        bulkPurgeResult: "Bulk delete finished",
        bulkPromptResult: "Bulk prompt update finished",
        bulkConfigResult: "Bulk config update finished",
        filterSections: {
          status: "Status",
          boundary: "Agent identity",
          team_index: "Team indexes",
          source_scope: "Source scope",
          mode: "Runtime mode",
          reference: "References",
          management: "Work queue",
        },
        moreFilters: "More filters",
        groupLabels: {
          active: "Available Agents",
          needs_review: "Needs Review",
          archived: "Archived",
          work_session: "Session entry Agents",
          team_role: "Team / research role Agents",
          system_role: "System evolution Agents",
          service_role: "Platform service Agents",
          chat: "Chat mode",
          research: "Research mode",
          supervised_evolution: "Supervised evolution mode",
          self_evolution: "Self-evolution mode",
          group_chat: "Group chat references",
          team: "Team references",
        } as Record<string, string>,
        groupDescriptions: {
          active: "Agents currently available for business pages and routing.",
          needs_review: "Available Agents with blocking or warning health issues.",
          archived: "Historical records that no longer enter the available pool.",
          work_session: "Codex-like session entry Agents for project development, debugging, implementation, and audit work.",
          team_role: "Agents with persona and task profiles that belong to team, research, or business organization structures.",
          system_role: "Agents owned by fixed system flows such as self-evolution or supervised evolution.",
          service_role: "Platform service Agents for knowledge, tools, memory, or governance upkeep.",
          group_chat: "Agents referenced by one or more group chats.",
          team: "Agents referenced by one or more team canvases.",
        } as Record<string, string>,
        managementFilterMissingPersona: "Missing persona",
        managementFilterMissingPersonaHint: "Missing gender, age, communication style, background, expertise, or identity notes.",
        managementFilterMissingTask: "Missing task profile",
        managementFilterMissingTaskHint: "Missing mission, responsibilities, task fit, success criteria, deliverables, or handoff notes.",
        managementFilterMissingTools: "Tool permissions need review",
        managementFilterMissingToolsHint: "No explicit allow, prefer, or block tools are configured. This Agent will not receive hidden default tools.",
        managementFilterNoTeam: "No team",
        managementFilterNoTeamHint: "Not referenced by any team canvas yet.",
        managementFilterPendingInbox: "Pending messages",
        managementFilterPendingInboxHint: "Agent inbox has pending messages to handle in Activity.",
        managementFilterMaintenance: "Issues to review",
        managementFilterMaintenanceHint: "Has blocking or warning issues that should be handled in Maintenance.",
        createAgent: "New Agent",
        createAgentTitle: "Create persistent Agent",
        createAgentHint: "Session entry Agents are created like Codex-style project executors. Team and research Agents still need persona, task mission, and organization placement.",
        createAgentName: "Functional name",
        createAgentNamePlaceholder: "e.g. Research review Agent",
        createAgentRole: "Role key",
        createAgentRolePlaceholder: "Required, e.g. research_reviewer",
        createAgentPersonaSummary: "Persona summary",
        createAgentPersonaPlaceholder: "e.g. Calm, detail-oriented, and evidence-first.",
        createAgentTaskMission: "Task mission",
        createAgentTaskMissionPlaceholder: "e.g. Review research conclusions and identify evidence gaps.",
        createAgentAllowedTools: "Allowed tools",
        createAgentAllowedToolsPlaceholder: "e.g. agent_message_tool, web_search_tool",
        createAgentToolBundles: "Tool packages",
        createAgentToolBundlesHint: "Choose capability packages for this Agent. You can still tune individual tools after creation.",
        createAgentToolBundlePreview: "Tool permissions after creation",
        createAgentToolBundleEmpty: "No tool package selected.",
        cancelCreate: "Cancel",
        creatingAgent: "Creating...",
        resetAgent: "Reset debug state",
        resettingAgent: "Resetting...",
        resetAgentTitle: "Debug reset",
        resetAgentHint: "By default this clears runtime traces and rebuilds a clean direct session. It does not delete/archive the Agent or remove team, room, or mode bindings.",
        resetAgentConfirm: "Reset {name}? Runtime traces are cleared and the direct session is rebuilt while team, room, and mode bindings are preserved. Checked advanced items return to empty profiles or default policies.",
        resetAgentSuccess: "Agent debug state reset",
        resetClearRuntimeState: "Clear runtime traces",
        resetClearRuntimeStateHint: "Deletes inbox, outbox, events, tmp, logs, runs, scratch, and artifacts in the Agent private workspace; keeps memory.",
        resetDirectSession: "Rebuild direct session",
        resetDirectSessionHint: "Deletes the old direct chat and messages, creates a clean directSessionId, and switches to it; group history is untouched.",
        resetPersonaProfile: "Reset persona profile",
        resetPersonaProfileHint: "Clears gender, age, pronouns, personality, background, expertise, and communication style.",
        resetTaskProfile: "Reset task profile",
        resetTaskProfileHint: "Clears mission, responsibilities, preferred/avoided tasks, success criteria, deliverables, and handoff notes.",
        resetToolPolicy: "Reset tool policy",
        resetToolPolicyHint: "Restores the default tool policy and removes this Agent's private allow/prefer/block/write-scope changes.",
        resetMemoryPolicy: "Reset memory policy",
        resetMemoryPolicyHint: "Restores the Agent private memory policy config; does not delete files under the memory directory.",
        resetRuntimePolicy: "Reset runtime policy",
        resetRuntimePolicyHint: "Restores delegation, concurrency/depth, wake, and supervision-review settings to defaults.",
        archiveAgent: "Safe archive",
        archivingAgent: "Archiving...",
        archiveAgentTitle: "Safe removal",
        archiveAgentHint: "Archiving removes this Agent from defaults, rooms, and pools while keeping sessions, memory, logs, and workspace data.",
        archiveConfirm: "Archive {name}? This hides the Agent and cleans mode/room references, but does not physically delete data.",
        purgeAgent: "Permanently delete",
        purgingAgent: "Deleting...",
        purgeAgentTitle: "Permanent deletion",
        purgeAgentHint: "Removes the AgentDirectory record plus its private workspace, memory, inbox, and event files; direct-session history is kept as deleted-Agent history.",
        purgeConfirm: "Permanently delete {name}? This cannot be undone and will delete the Agent private workspace and history files.",
        protectedAgent: "Protected Agents cannot be archived",
        archiveProtection: "Archive protected",
        archiveProtectionTitle: "Core protection",
        archiveProtectionHint: "This is a core research Agent and is still active. This panel only blocks archive actions; it does not mean the Agent is archived.",
        archivedAgents: "Archived",
        teams: "Teams",
        healthIssues: "Issues to review",
        healthIssueShort: "Issues",
        statusReminders: "Status reminders",
        statusReminderShort: "Reminders",
        workspaceHealthStatus: "Workspace health status",
        chatRooms: "Group Rooms",
        inbox: "Pending inbox",
        runningAgents: "Running",
        blockedAgents: "Blocked/failed",
        model: "Model slot",
        llmSlots: "Agent model slots",
        llmSlotsHint: "Configure dialogue, mental model, summary, subagent, and vision LLM slots per Agent. Settings only manages model library assets.",
        requiredSlot: "Required",
        optionalSlot: "Optional",
        inheritDialogueModel: "Not separately assigned",
        reasoningEffort: "Reasoning effort",
        reasoningEffortDefault: "Default",
        reasoningEffortLow: "Low",
        reasoningEffortMedium: "Medium",
        reasoningEffortHigh: "High",
        prompt: "Prompt",
        tools: "Tool policy",
        memory: "Memory policy",
        contextCompressionPolicy: "Context compression",
        contextCompressionInherit: "Inherit global",
        contextCompressionCustom: "Agent custom",
        contextCompressionEnabled: "Enable compression",
        contextCompressionMaxTokenLimit: "Compression limit",
        contextCompressionMaxCount: "Max per session",
        contextCompressionThresholds: "Trigger thresholds %",
        contextCompressionSummaryChars: "Summary chars",
        contextCompressionKeepAi: "Keep AI messages",
        contextCompressionPreserveErrors: "Preserve errors",
        contextCompressionExtractDecisions: "Extract decisions",
        contextCompressionEffective: "Compression trigger",
        contextCompressionWindow: "Model window",
        contextCompressionSourceGlobal: "Inherited global policy",
        contextCompressionSourceCustom: "This Agent uses a custom policy",
        territory: "Workspace territory",
        privateTerritory: "Private write root",
        sharedTerritory: "Shared read area",
        writeBoundary: "Default write boundary",
        territoryLegacy: "Legacy session path",
        context: "Context",
        run: "Run",
        communication: "Communication",
        delegation: "Subagents",
        modeMembership: "Mode membership",
        references: "References",
        sessions: "Sessions / rooms / workspace",
        logs: "Runs and logs",
        noAgents: "No Agent matched the current filter.",
        selectAgent: "Select an Agent to inspect its unified config card.",
        readOnly: "Read-only",
        policyPending: "Policy registry pending",
        noIssues: "No issues or reminders.",
        routeHint: "This card is the single Agent config point. Product pages should only reference Agents from here.",
        returnBannerTitle: "Return to previous page",
        returnBannerHint: "You arrived from another page. Return there after finishing this Agent configuration.",
        managementBriefTitle: "Management readiness",
        managementBriefHint: "Checks only the fields required by the current Agent identity. Session entry Agents do not require persona profiles or team membership.",
        managementIdentity: "Persona",
        managementTask: "Task",
        managementModelPrompt: "Model / instructions",
        managementWorkspace: "Workspace",
        managementTools: "Tools",
        managementMembership: "Membership",
        managementRuntime: "Runtime",
        nextActionsTitle: "Next actions",
        nextAllReady: "Core configuration is ready for teams or chat.",
        nextSetupModelPrompt: "Configure model and project instructions",
        nextSetupModelPromptHint: "Session entry Agents need a model slot and prompt/project instruction entry before use.",
        nextSetupIdentity: "Complete persona",
        nextSetupIdentityHint: "Give users and advisors a clear identity, background, expertise, and collaboration style.",
        nextSetupTask: "Complete task profile",
        nextSetupTaskHint: "Clarify what this Agent should take, deliver, avoid, and hand off.",
        nextSetupTools: "Configure tool package",
        nextSetupToolsHint: "Pick core/research/collaboration packages and review high-risk grants.",
        nextSetupWorkspace: "Check workspace boundary",
        nextSetupWorkspaceHint: "Confirm the project root, private workspace, and shared write grants fit the development task.",
        nextSetupMembership: "Bind team membership",
        nextSetupMembershipHint: "Place this Agent on a team canvas so the organization remains observable.",
        nextHandleInbox: "Handle pending messages",
        nextHandleInboxHint: "Other Agents or rooms left pending messages; process them before further setup.",
        capabilityPreviewTitle: "Effective capability preview",
        capabilityPreviewHint: "Estimated from the current draft: usable, preferred, blocked, and risky tool boundaries.",
        effectiveAllowedTools: "Effective allowed",
        highRiskAllowedTools: "High-risk allowed",
        explicitAllowedTools: "Explicit grants",
        writeBoundaryPreview: "Write boundary",
        maintenanceTitle: "Maintenance and dangerous actions",
        maintenanceHint: "Debug reset, archive, and purge live here so normal identity/task/tool editing stays separate from destructive actions.",
        healthReason: "Reason",
        healthNextStep: "Next step",
        toolPolicyPickerHint: "Choose the tool-permission template. Use Policies for allowed, preferred, or blocked tools.",
        memoryPolicyPickerHint: "Choose the memory-boundary template. Use Policies for readable and writable shared groups.",
        editAvatar: "Edit avatar",
        avatarEditorTitle: "Agent avatar",
        avatarEditorHint: "Avatar state is stored in AgentDirectory and reused by chat, teams, and rooms.",
        uploadAvatar: "Upload avatar",
        uploadingAvatar: "Uploading...",
        resetDefaultAvatar: "Use default avatar",
        resettingAvatar: "Resetting...",
        avatarLibrary: "Avatar library",
        avatarLibraryLoading: "Loading avatar library...",
        avatarLibraryEmpty: "No avatars are available in workspace/avatars.",
        avatarUpdateSuccess: "Agent avatar updated",
        personaTitle: "Persona profile",
        personaHint: "Persona state is stored in AgentDirectory and injected into runtime context. Advisor Agents can use it as design material.",
        savePersona: "Save persona",
        savingPersona: "Saving persona...",
        personaUpdateSuccess: "Agent persona profile saved",
        taskTitle: "Task profile",
        taskHint: "Task state is stored in AgentDirectory and injected into runtime context. It describes task fit and scope without automatic recommendation or scheduling.",
        saveTask: "Save task",
        savingTask: "Saving task...",
        taskUpdateSuccess: "Agent task profile saved",
        mission: "Mission",
        taskTypes: "Task types",
        taskTypesPlaceholder: "Comma-separated, e.g. literature review, experiment design, code review",
        responsibilities: "Responsibilities",
        preferredTasks: "Preferred tasks",
        avoidTasks: "Avoid tasks",
        successCriteria: "Success criteria",
        deliverables: "Deliverables",
        constraints: "Constraints",
        handoffNotes: "Handoff notes",
        gender: "Gender",
        age: "Age",
        pronouns: "Pronouns",
        personality: "Personality",
        communicationStyle: "Communication style",
        background: "Background",
        expertise: "Expertise",
        collaborationPreference: "Collaboration preference",
        identityNotes: "Identity notes",
        expertisePlaceholder: "Comma-separated, e.g. planning, statistics, review",
        overviewPane: "Overview",
        policiesPane: "Policies",
        membershipPane: "Membership",
        activityPane: "Activity",
        configTitle: "Config",
        saveConfig: "Save config",
        resetConfig: "Reset",
        savingConfig: "Saving...",
        status: "Status",
        membershipTitle: "Mode membership",
        saveMembership: "Save membership",
        savingMembership: "Saving membership...",
        chatRoomMembership: "Group room membership",
        noChatRooms: "No group rooms available.",
        toolPolicyTitle: "Tool permissions",
        saveToolPolicy: "Save permissions",
        savingToolPolicy: "Saving permissions...",
        toolBundlesTitle: "Configure by tool package",
        toolBundlesHint: "Pick packages for this Agent first, then tune individual tools below. Session Agents start with the core package, and you can turn tools off.",
        applyBundle: "Merge",
        replaceWithBundle: "Reset to package",
        preferredTools: "Preferred",
        toolGovernanceTitle: "Advisor governance",
        toolGovernanceHint: "Submit the current tool draft as a governed change. Low-risk changes may auto-apply; high-risk changes wait for review.",
        toolGovernanceSubmit: "Submit governance request",
        toolGovernanceSubmitting: "Submitting...",
        toolGovernanceReason: "Change reason",
        toolGovernanceReasonPlaceholder: "Explain why this Agent needs these tool permissions",
        toolGovernanceApplyAuto: "Auto-apply low risk",
        toolGovernanceApplyReview: "Review everything",
        toolGovernancePending: "Pending requests",
        toolGovernanceHistory: "Recent governance records",
        toolGovernanceApprove: "Approve",
        toolGovernanceReject: "Reject",
        toolGovernanceNoDelta: "Adjust the tool permission draft before submitting a governance request.",
        toolGovernanceEmpty: "No tool governance records yet.",
        toolGovernanceSuccess: "Tool governance request recorded",
        toolGovernanceResolved: "Tool governance request resolved",
        toolSearch: "Filter tools",
        noTools: "No configurable tools are available.",
        toolCategoryCount: "Tool packages",
        toolHighRisk: "High risk",
        toolTags: "Capability tags",
        allowedTools: "Allowed",
        blockedTools: "Blocked",
        inheritedTools: "Not allowed",
        workspaceWriteScopes: "Workspace writes",
        privateWriteScope: "Private territory",
        sharedWriteScope: "Shared workspace",
        sharedWriteHint: "When enabled, this Agent can write tool artifacts into workspace/shared.",
        memoryPolicyTitle: "Memory policy",
        saveMemoryPolicy: "Save memory",
        savingMemoryPolicy: "Saving memory...",
        readSharedGroups: "Readable shared groups",
        writeSharedGroups: "Writable shared groups",
        readKnowledgeBaseIds: "Readable knowledge bases",
        proposeKnowledgeBaseIds: "Proposal knowledge bases",
        reviewKnowledgeBaseIds: "Review knowledge bases",
        rateKnowledgeBaseIds: "Rating knowledge bases",
        knowledgeBasePlaceholder: "Enter knowledge base ID, e.g. kb-research",
        noKnowledgeBaseIds: "No knowledge base limit; team membership and roles apply.",
        addSharedGroup: "Add",
        sharedGroupPlaceholder: "Enter a shared group, e.g. project",
        noSharedGroups: "No shared groups configured.",
        delegationPolicyTitle: "Delegation policy",
        supervisionPolicyTitle: "Supervision policy",
        saveRuntimePolicy: "Save runtime policy",
        savingRuntimePolicy: "Saving runtime policy...",
        allowSubagents: "Allow sub-agents",
        maxConcurrent: "Max concurrent",
        allowWakeMessages: "Allow wake messages",
        openSession: "Open session",
        openLogs: "View logs",
        focusMessage: "View message",
        allowedContextModes: "Context modes",
        supervisionEnabled: "Enable supervision",
        requiresReview: "Require review",
        reviewMode: "Review mode",
        evidenceLevel: "Evidence level",
        chatDefault: "Chat default",
        chatAvailable: "Chat available",
        researchPool: "Research pool",
        supervisedSlot: "Supervised slot",
        selfEvolutionSlot: "Self-evolution slot",
        noSlot: "No slot",
        runHistoryTitle: "Run history",
        runtimeStatus: "Runtime status",
        runtimeFocus: "Current runtime focus",
        runtimeReason: "Status source",
        runtimeLatestRun: "Latest run",
        runtimeUpdated: "Updated",
        runtimeNextStep: "Suggested next step",
        runtimeEvidence: "Log evidence",
        runHistoryLoading: "Loading run history...",
        noRunHistory: "No run or sub-agent history yet.",
        inboxTitle: "Inbox pending",
        inboxLoading: "Loading pending messages...",
        inboxEmpty: "No pending messages.",
        consumeMessage: "Mark consumed",
        consumeAllMessages: "Mark all consumed",
        consumingMessage: "Consuming...",
        handleInboxNow: "Handle inbox",
        wakeStatus: "Wake status",
        activityTimeline: "Activity timeline",
        activityTimelineEmpty: "No run, message, or context event to summarize yet.",
        subAgentRuns: "Sub-agent runs",
        parentRuns: "Parent runs",
        supervisedRole: "Supervised role",
        maxDepth: "Max depth",
      };
}

function agentBulkActionSummary(action: string, success: number, skipped: number, failed: number, notes: string[], lang: "zh" | "en") {
  const parts = lang === "zh"
    ? [`成功 ${success}`, `跳过 ${skipped}`, `失败 ${failed}`]
    : [`success ${success}`, `skipped ${skipped}`, `failed ${failed}`];
  const preview = notes.slice(0, 3).join("；");
  return preview ? `${action}: ${parts.join(" / ")}。${preview}` : `${action}: ${parts.join(" / ")}`;
}

function agentBulkActionItemNote(
  item: AgentBulkActionItem,
  agentsById: Map<string, AgentConfigWorkspaceAgent>,
  fallback: string,
) {
  const agentId = String(item.agentId || "").trim();
  const label = agentLabel(agentsById.get(agentId)) || agentId || "-";
  const message = String(item.message || item.reason || fallback || "").trim();
  return message ? `${label}: ${message}` : label;
}

export function AgentsRoute() {
  const { lang } = useShellI18n();
  const queryClient = useQueryClient();
  const chatWorkspaceCache = useMemo(() => createChatWorkspaceCache(queryClient), [queryClient]);
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const pageVisible = usePageVisibility();
  const copy = useMemo(() => agentsRouteCopy(lang), [lang]);
  const numberFormatter = useMemo(() => new Intl.NumberFormat(lang === "zh" ? "zh-CN" : "en-US"), [lang]);
  const requestedAgentId = useMemo(() => String(searchParams.get("agent") || "").trim(), [searchParams]);
  const requestedPane = useMemo(() => normalizeAgentConfigPane(searchParams.get("pane")), [searchParams]);
  const returnToPath = useMemo(() => safeAgentCenterReturnTo(searchParams.get("returnTo")), [searchParams]);
  const returnToLabel = useMemo(() => agentCenterReturnLabel(searchParams.get("returnLabel"), lang), [lang, searchParams]);
  const [activeFilter, setActiveFilter] = useState<FilterId>("active");
  const [searchText, setSearchText] = useState("");
  const [selectedAgentId, setSelectedAgentId] = useState("");
  const [activePane, setActivePane] = useState<AgentConfigPaneId>("overview");
  const [createOpen, setCreateOpen] = useState(false);
  const [createDraft, setCreateDraft] = useState<AgentCreateDraft>(() => createDraftFromWorkspace(undefined, []));
  const [configDraft, setConfigDraft] = useState<AgentConfigDraft>(() => draftFromAgent(null));
  const [membershipDraft, setMembershipDraft] = useState<AgentModeMembershipDraft>(() => membershipDraftFromWorkspace(undefined, null));
  const [personaDraft, setPersonaDraft] = useState<AgentPersonaDraft>(() => personaDraftFromAgent(null));
  const [taskDraft, setTaskDraft] = useState<AgentTaskDraft>(() => taskDraftFromAgent(null));
  const [toolPolicyDraft, setToolPolicyDraft] = useState<AgentToolPolicyDraft>(() => toolPolicyDraftFromAgent(null));
  const [toolGovernanceDraft, setToolGovernanceDraft] = useState<AgentToolGovernanceDraft>(() => toolGovernanceDraftFromAgent(null));
  const [memoryPolicyDraft, setMemoryPolicyDraft] = useState<AgentMemoryPolicyDraft>(() => memoryPolicyDraftFromAgent(null));
  const [delegationPolicyDraft, setDelegationPolicyDraft] = useState<AgentDelegationPolicyDraft>(() => delegationPolicyDraftFromAgent(null));
  const [supervisionPolicyDraft, setSupervisionPolicyDraft] = useState<AgentSupervisionPolicyDraft>(() => supervisionPolicyDraftFromAgent(null));
  const [resetOptions, setResetOptions] = useState<AgentResetOptions>(DEFAULT_AGENT_RESET_OPTIONS);
  const [resettingAgentIds, setResettingAgentIds] = useState<Set<string>>(() => new Set());
  const [toolSearchText, setToolSearchText] = useState("");
  const [focusedMessageId, setFocusedMessageId] = useState("");
  const [avatarEditorOpen, setAvatarEditorOpen] = useState(false);
  const [notice, setNotice] = useState<{ tone: "success" | "error"; text: string } | null>(null);
  const [selectedBulkAgentIds, setSelectedBulkAgentIds] = useState<Set<string>>(() => new Set());
  const [bulkSelectionAnchorAgentId, setBulkSelectionAnchorAgentId] = useState("");
  const [bulkPromptTemplateId, setBulkPromptTemplateId] = useState("");
  const [bulkConfigDraft, setBulkConfigDraft] = useState<AgentBulkConfigDraft>(DEFAULT_BULK_CONFIG_DRAFT);
  const [bulkConfigApply, setBulkConfigApply] = useState<AgentBulkConfigApply>(DEFAULT_BULK_CONFIG_APPLY);
  const [bulkAgentPending, setBulkAgentPending] = useState(false);
  const draftSyncSourceRef = useRef<AgentDraftSyncSource | null>(null);
  const appliedRouteTargetRef = useRef("");

  const fullWorkspaceNeeded = Boolean(createOpen || activePane === "config" || activePane === "activity" || requestedAgentId);
  const workspaceQuery = useQuery({
    queryKey: queryKeys.agentConfigWorkspace(),
    queryFn: () => fetchJson<AgentConfigWorkspaceWithTeamIndexes>("/api/agents/config-workspace?includeRuntime=false"),
    enabled: fullWorkspaceNeeded,
    staleTime: 10_000,
  });
  const agentSummaryQuery = useQuery({
    queryKey: queryKeys.agentSummary(true),
    queryFn: () => fetchJson<AgentConfigWorkspaceAgent[]>("/api/agents?includeArchived=true&detail=summary"),
    staleTime: 10_000,
  });

  const toolsWorkspaceNeeded = createOpen || activePane === "config";
  const toolsQuery = useQuery({
    queryKey: queryKeys.tools(),
    queryFn: () => fetchJson<ToolRegistryPayload>("/api/tools"),
    enabled: toolsWorkspaceNeeded,
    refetchInterval: toolsWorkspaceNeeded ? resolvePollingInterval(pageVisible, 15_000) : false,
    refetchIntervalInBackground: false,
  });
  const toolBundles = toolsQuery.data?.toolBundles ?? EMPTY_TOOL_BUNDLES;

  const avatarOptionsQuery = useQuery({
    queryKey: ["agent-avatar-options"],
    queryFn: () => fetchJson<AgentAvatarOptionsPayload>("/api/agents/avatar-options"),
    enabled: avatarEditorOpen,
    staleTime: 30_000,
  });

  const lightweightWorkspace = useMemo(
    () => agentSummaryQuery.data ? buildLightweightAgentWorkspace(agentSummaryQuery.data, agentSummaryQuery.dataUpdatedAt) : undefined,
    [agentSummaryQuery.data, agentSummaryQuery.dataUpdatedAt],
  );
  const workspace = workspaceQuery.data ?? lightweightWorkspace;
  const tools = toolsQuery.data?.tools ?? EMPTY_TOOL_REGISTRY_ITEMS;
  const agentModelChoices = useMemo(
    () => buildAgentModelChoices(workspace?.agentModelChoices ?? []),
    [workspace?.agentModelChoices],
  );
  const llmSlots = useMemo(() => agentLlmSlots(workspace), [workspace?.agentLlmSlots]);
  const groups = workspace?.groups ?? EMPTY_AGENT_CONFIG_GROUPS;
  const teamIndexGroups = useMemo(() => workspaceTeamIndexes(workspace), [workspace]);
  const managementFilterGroups = useMemo(
    () => buildManagementFilterGroups(workspace?.agents ?? [], copy),
    [copy, workspace?.agents],
  );
  const groupedFilters = useMemo(() => {
    const sectionOrder = ["status", "boundary", "team_index"] as const;
    const indexedGroups = [...groups, ...teamIndexGroups];
    const defaultSections = sectionOrder
      .map((section) => ({
        id: section,
        label: copy.filterSections[section],
        groups: indexedGroups.filter((group) => groupSectionId(group) === section),
      }))
      .filter((section) => section.groups.length > 0);
    const managementSection = {
      id: "management",
      label: copy.filterSections.management,
      groups: managementFilterGroups.filter((group) => group.count > 0),
    };
    return [
      managementSection,
      ...defaultSections,
    ].filter((section) => section.groups.length > 0);
  }, [copy, groups, managementFilterGroups, teamIndexGroups]);
  const advancedGroupedFilters = useMemo(() => {
    const sectionOrder = ["source_scope", "mode", "reference"] as const;
    const indexedGroups = [...groups, ...teamIndexGroups];
    return sectionOrder
      .map((section) => ({
        id: section,
        label: copy.filterSections[section],
        groups: indexedGroups.filter((group) => groupSectionId(group) === section),
      }))
      .filter((section) => section.groups.length > 0);
  }, [copy, groups, teamIndexGroups]);
  const advancedFilterCount = advancedGroupedFilters.reduce((total, section) => total + section.groups.length, 0);
  const activeGroup = groups.find((group) => group.id === activeFilter);
  const activeTeamIndexGroup = teamIndexGroups.find((group) => group.id === activeFilter);
  const activeManagementGroup = managementFilterGroups.find((group) => group.id === activeFilter);
  const activeGroupLabel = activeManagementGroup?.label ?? activeTeamIndexGroup?.label ?? groupDisplayLabel(activeGroup, copy);
  const visibleAgents = useMemo(
    () => filterAgents(workspace, activeFilter, searchText),
    [activeFilter, searchText, workspace],
  );
  const visibleAgentColumns = useMemo(
    () => buildVisibleAgentColumns(visibleAgents, copy, teamIndexGroups),
    [copy, teamIndexGroups, visibleAgents],
  );
  const selectedBulkAgents = useMemo(
    () => visibleAgents.filter((agent) => selectedBulkAgentIds.has(agent.agentId)),
    [selectedBulkAgentIds, visibleAgents],
  );
  const selectedBulkAgentKey = selectedBulkAgents.map((agent) => agent.agentId).join("|");
  const bulkConfigMixed = useMemo(() => {
    return {
      dialogueModelId: bulkConfigValueMixed(selectedBulkAgents, (agent) => agentLlmSlotModelId(agent.llmBindings, FALLBACK_AGENT_LLM_SLOTS[0])),
      promptTemplateId: bulkConfigValueMixed(selectedBulkAgents, (agent) => agent.promptTemplateId || ""),
      primaryMode: bulkConfigValueMixed(selectedBulkAgents, (agent) => agent.primaryMode || ""),
      roleKey: bulkConfigValueMixed(selectedBulkAgents, (agent) => agent.roleKey || ""),
    };
  }, [selectedBulkAgentKey]);
  const bulkConfigCanSave = selectedBulkAgents.length > 1 && bulkConfigReady(bulkConfigDraft, bulkConfigApply) && !bulkAgentPending;
  const allVisibleAgentsSelected = visibleAgents.length > 0 && selectedBulkAgents.length === visibleAgents.length;
  const visiblePolicyTools = useMemo(() => {
    const query = normalizeText(toolSearchText);
    return tools.filter((tool) => {
      if (!tool.llmVisible && !tool.runtimeActive) {
        return false;
      }
      if (!query) {
        return true;
      }
      return normalizeText([
        tool.name,
        tool.description,
        tool.source,
        tool.status,
        tool.category,
        tool.categoryLabel,
        tool.permissionTier,
        ...(tool.bundleIds ?? []),
        ...(tool.capabilityTags ?? []),
        ...(tool.riskTags ?? []),
      ].join(" ")).includes(query);
    });
  }, [toolSearchText, tools]);
  const visiblePolicyToolGroups = useMemo(
    () => groupPolicyToolsByBundle(visiblePolicyTools, toolBundles, toolPolicyDraft, lang),
    [lang, toolBundles, toolPolicyDraft, visiblePolicyTools],
  );
  const selectedAgent = selectedAgentFromList(visibleAgents, selectedAgentId, workspace?.agents ?? [], activeFilter);
  const selectedAgentToolConfigRoute = useMemo(
    () => selectedAgent?.agentId
      ? agentCenterToolsRoute({
          agentId: selectedAgent.agentId,
          returnLabel: "agents",
          returnTo: `/agents?agent=${encodeURIComponent(selectedAgent.agentId)}&pane=config`,
        })
      : "/agents/tools",
    [selectedAgent?.agentId],
  );
  const managementBrief = useMemo(() => buildAgentManagementBrief(selectedAgent, copy, lang), [copy, lang, selectedAgent]);
  const capabilityPreview = useMemo(
    () => buildAgentCapabilityPreview(toolPolicyDraft, visiblePolicyTools, copy),
    [copy, toolPolicyDraft, visiblePolicyTools],
  );
  const memoryGroupOptions = useMemo(() => sharedGroupCandidates(workspace, selectedAgent), [selectedAgent?.agentId, workspace?.generatedAt]);
  const panes = useMemo(() => agentConfigPanes(copy, selectedAgent), [copy, selectedAgent]);
  const agentRunsQuery = useQuery({
    queryKey: queryKeys.agentRuns(selectedAgent?.agentId ?? ""),
    queryFn: () => fetchJson<AgentRunHistory>(`/api/agents/${encodeURIComponent(selectedAgent?.agentId ?? "")}/runs?limit=12`),
    enabled: Boolean(selectedAgent?.agentId && activePane === "activity"),
    refetchInterval: resolvePollingInterval(pageVisible, 12_000),
    refetchIntervalInBackground: false,
  });
  const agentMessagesQuery = useQuery({
    queryKey: queryKeys.agentMessages(selectedAgent?.agentId ?? "", "pending"),
    queryFn: () => fetchJson<AgentInboxMessage[]>(`/api/agents/${encodeURIComponent(selectedAgent?.agentId ?? "")}/messages?status=pending&limit=8`),
    enabled: Boolean(selectedAgent?.agentId && activePane === "activity"),
    refetchInterval: resolvePollingInterval(pageVisible, 12_000),
    refetchIntervalInBackground: false,
  });
  const selectedAgentInboxPendingCount = selectedAgent?.agentInboxPendingCount ?? agentMessagesQuery.data?.length ?? 0;
  const agentRuntimeEvidenceQuery = useQuery({
    queryKey: queryKeys.agentRuntimeEvidence(selectedAgent?.agentId ?? ""),
    queryFn: () => fetchJson<AgentRuntimeEvidence>(
      `/api/agents/${encodeURIComponent(selectedAgent?.agentId ?? "")}/runtime-evidence?sessionId=${encodeURIComponent(selectedAgent?.directSessionId ?? "")}&limit=5`,
    ),
    enabled: Boolean(selectedAgent?.agentId && activePane === "activity"),
    refetchInterval: resolvePollingInterval(pageVisible, 20_000),
    refetchIntervalInBackground: false,
  });
  const activityTimeline = useMemo(
    () => selectedAgent ? buildActivityTimeline(selectedAgent, agentRunsQuery.data, agentMessagesQuery.data, copy, lang, agentRuntimeEvidenceQuery.data) : [],
    [agentMessagesQuery.data, agentRunsQuery.data, agentRuntimeEvidenceQuery.data, copy, lang, selectedAgent],
  );
  const runtimeFocusEvidence = useMemo(
    () => findRuntimeFocusEvidence(selectedAgent, agentRuntimeEvidenceQuery.data),
    [agentRuntimeEvidenceQuery.data, selectedAgent],
  );
  const summary = workspace?.summary;
  const healthStatus = workspace?.health.status ?? "ok";
  const healthStatusLabel = workspaceHealthStatusLabel(healthStatus, lang);
  const healthStatusDescription = workspaceHealthStatusDescription(healthStatus, summary, lang);
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.agentSummary(true) });
    void chatWorkspaceCache.afterAgentWorkspaceChanged();
  };

  useEffect(() => {
    const routeTargetKey = requestedAgentId ? `${requestedAgentId}:${requestedPane}` : "";
    if (!routeTargetKey) {
      appliedRouteTargetRef.current = "";
      return;
    }
    if (!workspace || appliedRouteTargetRef.current === routeTargetKey) {
      return;
    }
    const targetAgent = workspace.agents.find((agent) => agent.agentId === requestedAgentId);
    if (!targetAgent) {
      setNotice({
        tone: "error",
        text: lang === "zh" ? "目标 Agent 不存在或已被移除。" : "The requested Agent does not exist or was removed.",
      });
      appliedRouteTargetRef.current = routeTargetKey;
      return;
    }
    setSelectedAgentId(targetAgent.agentId);
    setActivePane(requestedPane);
    setActiveFilter(targetAgent.status === "archived" ? "archived" : "active");
    setSearchText("");
    setCreateOpen(false);
    setSelectedBulkAgentIds(new Set());
    setBulkSelectionAnchorAgentId(targetAgent.agentId);
    appliedRouteTargetRef.current = routeTargetKey;
  }, [lang, requestedAgentId, requestedPane, workspace]);

  useEffect(() => {
    setBulkConfigDraft(bulkConfigDraftFromAgents(selectedBulkAgents));
    setBulkConfigApply(DEFAULT_BULK_CONFIG_APPLY);
  }, [selectedBulkAgentKey]);

  useEffect(() => {
    const nextSource = draftSyncSourceFromAgent(workspace, selectedAgent);
    const previousSource = draftSyncSourceRef.current;
    const agentChanged = previousSource?.agentId !== nextSource.agentId;

    if (!previousSource || agentChanged) {
      setConfigDraft(nextSource.config);
      setMembershipDraft(nextSource.membership);
      setPersonaDraft(nextSource.persona);
      setTaskDraft(nextSource.task);
      setToolPolicyDraft(nextSource.toolPolicy);
      setToolGovernanceDraft(toolGovernanceDraftFromAgent(selectedAgent));
      setMemoryPolicyDraft(nextSource.memoryPolicy);
      setDelegationPolicyDraft(nextSource.delegationPolicy);
      setSupervisionPolicyDraft(nextSource.supervisionPolicy);
      setToolSearchText("");
      setFocusedMessageId("");
      setAvatarEditorOpen(false);
      setNotice(null);
      draftSyncSourceRef.current = nextSource;
      return;
    }

    setConfigDraft((current) => configDraftEqualsDraft(current, previousSource.config) ? nextSource.config : current);
    setMembershipDraft((current) => membershipDraftEqualsDraft(current, previousSource.membership) ? nextSource.membership : current);
    setPersonaDraft((current) => personaDraftEqualsDraft(current, previousSource.persona) ? nextSource.persona : current);
    setTaskDraft((current) => taskDraftEqualsDraft(current, previousSource.task) ? nextSource.task : current);
    setToolPolicyDraft((current) => toolPolicyDraftEqualsDraft(current, previousSource.toolPolicy) ? nextSource.toolPolicy : current);
    setMemoryPolicyDraft((current) => memoryPolicyDraftEqualsDraft(current, previousSource.memoryPolicy) ? nextSource.memoryPolicy : current);
    setDelegationPolicyDraft((current) =>
      delegationPolicyDraftEqualsDraft(current, previousSource.delegationPolicy) ? nextSource.delegationPolicy : current,
    );
    setSupervisionPolicyDraft((current) =>
      supervisionPolicyDraftEqualsDraft(current, previousSource.supervisionPolicy) ? nextSource.supervisionPolicy : current,
    );
    draftSyncSourceRef.current = nextSource;
  }, [selectedAgent, workspace]);

  useEffect(() => {
    if (requestedAgentId && selectedAgent?.agentId === requestedAgentId) {
      setResetOptions(DEFAULT_AGENT_RESET_OPTIONS);
      return;
    }
    setActivePane("overview");
    setResetOptions(DEFAULT_AGENT_RESET_OPTIONS);
  }, [requestedAgentId, selectedAgent?.agentId]);

  useEffect(() => {
    setCreateDraft((current) => {
      if (agentLlmSlotModelId(current.llmBindings, FALLBACK_AGENT_LLM_SLOTS[0]) || current.promptTemplateId) {
        const normalized = normalizeCreateDraftForWorkspace(current, workspace, toolBundles);
        if (normalized.selectedToolBundleIds.length || !toolBundles.length) {
          return normalized;
        }
        return {
          ...normalized,
          selectedToolBundleIds: defaultCreateToolBundleIds(isWorkSessionCreateDraft(normalized), toolBundles),
        };
      }
      return createDraftFromWorkspace(workspace, toolBundles);
    });
  }, [toolBundles, workspace]);

  useEffect(() => {
    setSelectedBulkAgentIds((current) => {
      const visibleIds = new Set(visibleAgents.map((agent) => agent.agentId));
      const next = new Set(Array.from(current).filter((agentId) => visibleIds.has(agentId)));
      return next.size === current.size ? current : next;
    });
  }, [visibleAgents]);

  const configDirty = !draftEqualsAgent(configDraft, selectedAgent);
  const membershipDirty = !membershipDraftEqualsWorkspace(membershipDraft, workspace, selectedAgent);
  const personaDirty = !personaDraftEqualsAgent(personaDraft, selectedAgent);
  const taskDirty = !taskDraftEqualsAgent(taskDraft, selectedAgent);
  const toolPolicyDirty = !toolPolicyDraftEqualsAgent(toolPolicyDraft, selectedAgent);
  const memoryPolicyDirty = !memoryPolicyDraftEqualsAgent(memoryPolicyDraft, selectedAgent);
  const runtimePolicyDirty = !delegationPolicyDraftEqualsAgent(delegationPolicyDraft, selectedAgent)
    || !supervisionPolicyDraftEqualsAgent(supervisionPolicyDraft, selectedAgent);
  const toolGovernanceDelta = toolPolicyDeltaFromDraft(toolPolicyDraft, selectedAgent);
  const toolGovernanceDeltaTotal = toolPolicyDeltaCount(toolGovernanceDelta);
  const canSubmitToolGovernance = Boolean(selectedAgent?.agentId && toolGovernanceDeltaTotal > 0);
  const canSaveConfig = Boolean(selectedAgent?.agentId && configDraft.displayName.trim() && configDirty);
  const canSaveMembership = Boolean(selectedAgent?.agentId && membershipDirty);
  const canSavePersona = Boolean(selectedAgent?.agentId && personaDirty);
  const canSaveTask = Boolean(selectedAgent?.agentId && taskDirty);
  const canSaveToolPolicy = Boolean(selectedAgent?.agentId && toolPolicyDirty);
  const canSaveMemoryPolicy = Boolean(selectedAgent?.agentId && memoryPolicyDirty);
  const canSaveRuntimePolicy = Boolean(selectedAgent?.agentId && runtimePolicyDirty);
  const createToolBundleSummaryValue = useMemo(
    () => createToolBundleSummary(
      createDraft.selectedToolBundleIds,
      toolBundles,
      lang,
    ),
    [createDraft, lang, toolBundles],
  );
  const canCreateAgent = createDraftReady(createDraft, toolBundles);
  const createDraftIsWorkSession = isWorkSessionCreateDraft(createDraft);
  const selectedAgentRequiresPersona = requiresPersonaProfile(selectedAgent);
  const selectedAgentRequiresTask = requiresTaskProfile(selectedAgent);
  const selectedAgentRequiresTeamMembership = requiresTeamMembership(selectedAgent);
  const selectedAgentProtected = agentArchiveProtected(selectedAgent);
  const selectedAgentResetPending = Boolean(selectedAgent?.agentId && resettingAgentIds.has(selectedAgent.agentId));
  const canResetAgent = Boolean(selectedAgent?.agentId && selectedAgent.status !== "archived");
  const canArchiveAgent = Boolean(selectedAgent?.agentId && selectedAgent.status !== "archived" && !selectedAgentProtected);
  const canPurgeAgent = Boolean(selectedAgent?.agentId && selectedAgent.status === "archived" && !selectedAgentProtected);
  const contextCompressionCustom = configDraft.contextCompressionPolicy.mode === "custom";
  const contextCompressionEffectivePolicy = selectedAgent?.contextCompressionEffectivePolicy;
  const contextCompressionEffectiveLimit = contextCompressionEffectivePolicy?.compressionTriggerTokenLimit
    ?? contextCompressionEffectivePolicy?.effectiveTokenLimit
    ?? contextCompressionEffectivePolicy?.maxTokenLimit
    ?? Number(configDraft.contextCompressionPolicy.maxTokenLimit || DEFAULT_AGENT_CONTEXT_COMPRESSION_DRAFT.maxTokenLimit);
  const contextCompressionWindowLimit = contextCompressionEffectivePolicy?.modelContextWindowLimit
    ?? contextCompressionEffectivePolicy?.contextWindowLimit
    ?? 0;
  const contextCompressionPolicySource = contextCompressionCustom
    ? copy.contextCompressionSourceCustom
    : copy.contextCompressionSourceGlobal;
  const contextCompressionPolicyLine = `${contextCompressionPolicySource} · ${copy.contextCompressionEffective}: ${numberFormatter.format(
    Math.max(0, Number(contextCompressionEffectiveLimit) || 0),
  )} · ${copy.contextCompressionWindow}: ${numberFormatter.format(Math.max(0, Number(contextCompressionWindowLimit) || 0))}`;
  const toolPolicySource = selectedAgent?.toolPolicySource;
  const toolPolicySourceLine = toolPolicySource
    ? `${toolPolicySource.label} · ${toolPolicySource.allowedToolCount} ${copy.tools}${toolPolicySource.mutatingToolCount ? ` · ${toolPolicySource.mutatingToolCount} ${lang === "zh" ? "个可写/命令工具" : "mutating tools"}` : ""}`
    : copy.toolPolicyPickerHint;

  const createAgentMutation = useMutation({
    mutationFn: (draft: AgentCreateDraft) => {
      const workSession = isWorkSessionCreateDraft(draft);
      const roleKey = workSession ? "" : draft.roleKey.trim();
      const selectedToolPolicy = toolBundleSelectionToPolicy(draft.selectedToolBundleIds, toolBundles);
      const fallbackAllowedTools = toolBundles.length ? [] : expertiseFromDraft(draft.allowedTools);
      const selectedAllowedTools = selectedToolPolicy.allowedTools.length ? selectedToolPolicy.allowedTools : fallbackAllowedTools;
      const allowedTools = sortedIds(selectedAllowedTools);
      const selectedPreferredTools = selectedToolPolicy.preferredTools.length
        ? selectedToolPolicy.preferredTools
        : fallbackAllowedTools.includes("agent_message_tool") ? ["agent_message_tool"] : [];
      const preferredTools = sortedIds(selectedPreferredTools.filter((tool) => allowedTools.includes(tool)));
      const personaProfile = workSession
        ? {}
        : {
            personality: draft.personaSummary.trim(),
            communicationStyle: "按角色边界回应；先给结论，再说明依据和需要交接的事项。",
            background: `由 Agent 中心创建，用于 ${draft.displayName.trim()}。`,
            collaborationPreference: "优先保持短反馈和清晰交接；超出任务使命时主动说明边界。",
            identityNotes: "创建时已完成最小建档；可在人物档案中继续细化。",
            expertise: roleKey ? [roleKey] : [],
          };
      const taskProfile = workSession
        ? {}
        : {
            mission: draft.taskMission.trim(),
            taskTypes: roleKey ? [roleKey] : [draft.primaryMode],
            responsibilities: `围绕 ${draft.displayName.trim()} 执行任务；遵守角色键 ${roleKey} 的职责边界。`,
            preferredTasks: draft.taskMission.trim(),
            avoidTasks: "不要承担未授权工具调用、未绑定团队职位或超出任务使命的长期职责。",
            successCriteria: "用户能清楚理解该 Agent 的职责、边界、下一步和交付结果。",
            deliverables: "结论、依据、待确认事项和必要的交接说明。",
            constraints: "只使用已授权工具；需要更多权限时走工具治理或用户确认。",
            handoffNotes: "由 Agent 中心创建，后续可在人物档案和任务档案中继续细化。",
          };
      return fetchJson<AgentConfigWorkspaceAgent>("/api/agents", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          displayName: draft.displayName.trim(),
          llmBindings: normalizeAgentLlmBindings(draft.llmBindings),
          primaryMode: draft.primaryMode,
          roleKey,
          promptTemplateId: draft.promptTemplateId,
          personaProfile,
          taskProfile,
          toolPolicy: {
            allowedTools,
            preferredTools,
            readScopes: ["private"],
            writeScopes: ["private"],
            networkAccess: "controlled",
            mutationAccess: "controlled",
          },
          metadata: {
            creationChannel: "agent_center",
            onboardingStatus: "complete",
            onboardingMissing: [],
            creationToolBundleIds: sortedIds(draft.selectedToolBundleIds),
          },
        }),
      });
    },
    onSuccess: (agent) => {
      setSelectedAgentId(agent.agentId);
      setActivePane("config");
      setCreateOpen(false);
      setCreateDraft(createDraftFromWorkspace(workspace, toolBundles));
      setNotice({
        tone: "success",
        text: lang === "zh" ? `已新增 ${agentLabel(agent)}` : `Created ${agentLabel(agent)}`,
      });
      void chatWorkspaceCache.afterAgentWorkspaceChanged();
    },
    onError: (error) => {
      setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    },
  });

  const updateAgentMutation = useMutation({
    mutationFn: (payload: { agentId: string; agent: AgentConfigWorkspaceAgent; draft: AgentConfigDraft; modelChoices: AgentModelChoice[] }) =>
      fetchJson<AgentConfigWorkspaceAgent>(`/api/agents/${encodeURIComponent(payload.agentId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          displayName: payload.draft.displayName,
          llmBindings: normalizeAgentLlmBindings(payload.draft.llmBindings),
          promptTemplateId: payload.draft.promptTemplateId,
          toolPolicyId: payload.draft.toolPolicyId,
          memoryPolicyId: payload.draft.memoryPolicyId,
          contextCompressionPolicy: contextCompressionPolicyFromDraft(payload.draft.contextCompressionPolicy),
          metadata: agentMetadataWithReasoningEffort(payload.draft, payload.modelChoices),
          status: payload.draft.status,
        }),
      }),
    onSuccess: (agent) => {
      queryClient.setQueryData<AgentConfigWorkspace | undefined>(
        queryKeys.agentConfigWorkspace(),
        (current) => updatedAgentWorkspaceCache(current, agent),
      );
      setNotice({
        tone: "success",
        text: lang === "zh" ? `已保存 ${agentLabel(agent)} 的 Agent 配置` : `Saved config for ${agentLabel(agent)}`,
      });
      void chatWorkspaceCache.afterAgentWorkspaceChanged();
    },
    onError: (error) => {
      setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    },
  });

  const updatePersonaMutation = useMutation({
    mutationFn: (payload: { agentId: string; draft: AgentPersonaDraft }) =>
      fetchJson<AgentConfigWorkspaceAgent>(`/api/agents/${encodeURIComponent(payload.agentId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          personaProfile: personaProfileFromDraft(payload.draft),
        }),
      }),
    onSuccess: (agent) => {
      queryClient.setQueryData<AgentConfigWorkspace | undefined>(
        queryKeys.agentConfigWorkspace(),
        (current) => updatedAgentWorkspaceCache(current, agent),
      );
      setPersonaDraft(personaDraftFromAgent(agent));
      draftSyncSourceRef.current = draftSyncSourceFromAgent(workspace, agent);
      setNotice({ tone: "success", text: copy.personaUpdateSuccess });
      void chatWorkspaceCache.afterAgentWorkspaceChanged();
    },
    onError: (error) => {
      setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    },
  });

  const updateTaskMutation = useMutation({
    mutationFn: (payload: { agentId: string; draft: AgentTaskDraft }) =>
      fetchJson<AgentConfigWorkspaceAgent>(`/api/agents/${encodeURIComponent(payload.agentId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          taskProfile: taskProfileFromDraft(payload.draft),
        }),
      }),
    onSuccess: (agent) => {
      queryClient.setQueryData<AgentConfigWorkspace | undefined>(
        queryKeys.agentConfigWorkspace(),
        (current) => updatedAgentWorkspaceCache(current, agent),
      );
      setTaskDraft(taskDraftFromAgent(agent));
      draftSyncSourceRef.current = draftSyncSourceFromAgent(workspace, agent);
      setNotice({ tone: "success", text: copy.taskUpdateSuccess });
      void chatWorkspaceCache.afterAgentWorkspaceChanged();
    },
    onError: (error) => {
      setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    },
  });

  const archiveAgentMutation = useMutation({
    mutationFn: (payload: { agentId: string }) =>
      fetchJson<AgentConfigWorkspaceAgent>(`/api/agents/${encodeURIComponent(payload.agentId)}`, {
        method: "DELETE",
      }),
    onMutate: async (payload) => {
      await queryClient.cancelQueries({ queryKey: queryKeys.agentConfigWorkspace() });
      const previousWorkspace = queryClient.getQueryData<AgentConfigWorkspace>(queryKeys.agentConfigWorkspace());
      const previousSelectedAgentId = selectedAgentId;
      const previousActivePane = activePane;
      const optimisticAgent = previousWorkspace?.agents.find((agent) => agent.agentId === payload.agentId) ?? selectedAgent;
      if (optimisticAgent) {
        queryClient.setQueryData<AgentConfigWorkspace | undefined>(
          queryKeys.agentConfigWorkspace(),
          (current) => archivedWorkspaceCache(current, optimisticArchivedAgent(optimisticAgent)),
        );
      }
      setSelectedAgentId("");
      setActivePane("overview");
      return { previousWorkspace, previousSelectedAgentId, previousActivePane };
    },
    onSuccess: (agent) => {
      queryClient.setQueryData<AgentConfigWorkspace | undefined>(
        queryKeys.agentConfigWorkspace(),
        (current) => archivedWorkspaceCache(current, agent),
      );
      setSelectedAgentId("");
      setActivePane("overview");
      setNotice({
        tone: "success",
        text: lang === "zh" ? `已安全归档 ${agentLabel(agent)}` : `Archived ${agentLabel(agent)}`,
      });
      void chatWorkspaceCache.afterAgentArchived();
    },
    onError: (error, _variables, context) => {
      if (context?.previousWorkspace) {
        queryClient.setQueryData(queryKeys.agentConfigWorkspace(), context.previousWorkspace);
      }
      setSelectedAgentId(context?.previousSelectedAgentId ?? "");
      setActivePane(context?.previousActivePane ?? "overview");
      setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
      void chatWorkspaceCache.afterAgentArchived();
    },
  });

  const purgeAgentMutation = useMutation({
    mutationFn: (payload: { agentId: string }) =>
      fetchJson<{ agentId: string; status: string; deleted: boolean; purgeSummary?: { dataRetention?: string } }>(
        `/api/agents/${encodeURIComponent(payload.agentId)}/purge`,
        { method: "DELETE" },
      ),
    onMutate: async (payload) => {
      await queryClient.cancelQueries({ queryKey: queryKeys.agentConfigWorkspace() });
      const previousWorkspace = queryClient.getQueryData<AgentConfigWorkspace>(queryKeys.agentConfigWorkspace());
      const previousSelectedAgentId = selectedAgentId;
      const previousActivePane = activePane;
      queryClient.setQueryData<AgentConfigWorkspace | undefined>(
        queryKeys.agentConfigWorkspace(),
        (current) => purgedWorkspaceCache(current, payload.agentId),
      );
      setSelectedAgentId("");
      setActivePane("overview");
      return { previousWorkspace, previousSelectedAgentId, previousActivePane };
    },
    onSuccess: (result) => {
      queryClient.setQueryData<AgentConfigWorkspace | undefined>(
        queryKeys.agentConfigWorkspace(),
        (current) => purgedWorkspaceCache(current, result.agentId),
      );
      setSelectedAgentId("");
      setActivePane("overview");
      setNotice({
        tone: "success",
        text: lang === "zh" ? "已彻底删除归档 Agent" : "Permanently deleted archived Agent",
      });
      void chatWorkspaceCache.afterAgentArchived();
    },
    onError: (error, _variables, context) => {
      if (context?.previousWorkspace) {
        queryClient.setQueryData(queryKeys.agentConfigWorkspace(), context.previousWorkspace);
      }
      setSelectedAgentId(context?.previousSelectedAgentId ?? "");
      setActivePane(context?.previousActivePane ?? "overview");
      setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
      void chatWorkspaceCache.afterAgentArchived();
    },
  });

  const resetAgentMutation = useMutation({
    mutationFn: (payload: { agentId: string; options: AgentResetOptions }) =>
      fetchJson<{ agent: AgentConfigWorkspaceAgent; resetSummary: Record<string, unknown> }>(
        `/api/agents/${encodeURIComponent(payload.agentId)}/reset`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload.options),
        },
      ),
    onMutate: (payload) => {
      setResettingAgentIds((current) => {
        const next = new Set(current);
        next.add(payload.agentId);
        return next;
      });
    },
    onSuccess: (result) => {
      const agent = result.agent;
      setNotice({ tone: "success", text: copy.resetAgentSuccess });
      setResetOptions(DEFAULT_AGENT_RESET_OPTIONS);
      void chatWorkspaceCache.afterAgentWorkspaceChanged();
      void queryClient.invalidateQueries({ queryKey: queryKeys.agentRuns(agent.agentId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.agentMessages(agent.agentId, "pending") });
      void queryClient.invalidateQueries({ queryKey: queryKeys.agentRuntimeEvidence(agent.agentId) });
    },
    onError: (error) => {
      setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    },
    onSettled: (_result, _error, payload) => {
      setResettingAgentIds((current) => {
        const next = new Set(current);
        next.delete(payload.agentId);
        return next;
      });
    },
  });

  const updateAvatarMutation = useMutation({
    mutationFn: (payload: { agentId: string; avatarImagePath?: string; resetToDefault?: boolean }) =>
      fetchJson<AgentConfigWorkspaceAgent>(`/api/agents/${encodeURIComponent(payload.agentId)}/avatar`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          avatarImagePath: payload.avatarImagePath ?? "",
          resetToDefault: Boolean(payload.resetToDefault),
        }),
      }),
    onSuccess: (agent) => {
      queryClient.setQueryData<AgentConfigWorkspace | undefined>(
        queryKeys.agentConfigWorkspace(),
        (current) => updatedAgentWorkspaceCache(current, agent),
      );
      setNotice({ tone: "success", text: copy.avatarUpdateSuccess });
      void chatWorkspaceCache.afterAgentWorkspaceChanged();
    },
    onError: (error) => {
      setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    },
  });

  const uploadAvatarMutation = useMutation({
    mutationFn: async (payload: { agentId: string; file: File }) =>
      fetchJson<AgentAvatarUploadResponse>(`/api/agents/${encodeURIComponent(payload.agentId)}/avatar-image`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          filename: payload.file.name,
          contentType: payload.file.type || "image/png",
          dataBase64: encodeArrayBufferBase64(await payload.file.arrayBuffer()),
        }),
      }),
    onSuccess: (result) => {
      queryClient.setQueryData<AgentConfigWorkspace | undefined>(
        queryKeys.agentConfigWorkspace(),
        (current) => updatedAgentWorkspaceCache(current, result.agent),
      );
      setNotice({ tone: "success", text: copy.avatarUpdateSuccess });
      void queryClient.invalidateQueries({ queryKey: ["agent-avatar-options"] });
      void chatWorkspaceCache.afterAgentWorkspaceChanged();
    },
    onError: (error) => {
      setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    },
  });

  const updateMembershipMutation = useMutation({
    mutationFn: (payload: { agentId: string; draft: AgentModeMembershipDraft }) =>
      fetchJson<AgentModeBindings>(`/api/agents/${encodeURIComponent(payload.agentId)}/mode-membership`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload.draft),
      }),
    onSuccess: (payload, variables) => {
      queryClient.setQueryData<AgentConfigWorkspace | undefined>(
        queryKeys.agentConfigWorkspace(),
        (current) => current
          ? {
              ...current,
              modeBindings: payload.modes ?? current.modeBindings,
            }
          : current,
      );
      setMembershipDraft(variables.draft);
      setNotice({
        tone: "success",
        text: lang === "zh" ? "已保存 Agent 使用位置" : "Saved Agent mode membership",
      });
      void chatWorkspaceCache.afterAgentWorkspaceChanged();
    },
    onError: (error) => {
      setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    },
  });

  const updateToolPolicyMutation = useMutation({
    mutationFn: (payload: { agentId: string; draft: AgentToolPolicyDraft; basePolicy: ToolPolicy | undefined }) =>
      fetchJson<AgentConfigWorkspaceAgent>(`/api/agents/${encodeURIComponent(payload.agentId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          toolPolicy: {
            ...defaultToolPolicy(payload.basePolicy?.policyId || "default"),
            ...(payload.basePolicy ?? {}),
            allowedTools: sortedIds(payload.draft.allowedTools),
            preferredTools: sortedIds(payload.draft.preferredTools),
            blockedTools: sortedIds(payload.draft.blockedTools),
            readScopes: sortedIds(payload.draft.readScopes),
            writeScopes: sortedIds(payload.draft.writeScopes),
          },
        }),
      }),
    onSuccess: (agent) => {
      queryClient.setQueryData<AgentConfigWorkspace | undefined>(
        queryKeys.agentConfigWorkspace(),
        (current) => updatedAgentWorkspaceCache(current, agent),
      );
      setNotice({
        tone: "success",
        text: lang === "zh" ? `已保存 ${agentLabel(agent)} 的工具能力` : `Saved tool permissions for ${agentLabel(agent)}`,
      });
      void chatWorkspaceCache.afterAgentWorkspaceChanged();
    },
    onError: (error) => {
      setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    },
  });

  const createToolGovernanceMutation = useMutation({
    mutationFn: (payload: {
      agentId: string;
      draft: AgentToolGovernanceDraft;
      delta: ReturnType<typeof toolPolicyDeltaFromDraft>;
    }) =>
      fetchJson<AgentToolGovernanceRequest>(`/api/agents/${encodeURIComponent(payload.agentId)}/tool-governance-requests`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          proposedByAgentId: payload.draft.proposedByAgentId,
          grantTools: sortedIds(payload.delta.grantTools),
          revokeTools: sortedIds(payload.delta.revokeTools),
          blockTools: sortedIds(payload.delta.blockTools),
          unblockTools: sortedIds(payload.delta.unblockTools),
          reason: payload.draft.reason,
          applyMode: payload.draft.applyMode,
        }),
      }),
    onSuccess: (request) => {
      setNotice({
        tone: "success",
        text: `${copy.toolGovernanceSuccess}: ${governanceStatusLabel(request.status, lang)}`,
      });
      setToolGovernanceDraft(toolGovernanceDraftFromAgent(selectedAgent));
      void chatWorkspaceCache.afterAgentWorkspaceChanged();
    },
    onError: (error) => {
      setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    },
  });

  const resolveToolGovernanceMutation = useMutation({
    mutationFn: (payload: { agentId: string; requestId: string; decision: "approve" | "reject" }) =>
      fetchJson<AgentToolGovernanceRequest>(
        `/api/agents/${encodeURIComponent(payload.agentId)}/tool-governance-requests/${encodeURIComponent(payload.requestId)}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            decision: payload.decision,
            resolvedBy: "user",
            resolutionNote: payload.decision,
          }),
        },
      ),
    onSuccess: () => {
      setNotice({ tone: "success", text: copy.toolGovernanceResolved });
      void chatWorkspaceCache.afterAgentWorkspaceChanged();
    },
    onError: (error) => {
      setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    },
  });

  const updateMemoryPolicyMutation = useMutation({
    mutationFn: (payload: { agentId: string; draft: AgentMemoryPolicyDraft; basePolicy: MemoryPolicy | undefined }) =>
      fetchJson<AgentConfigWorkspaceAgent>(`/api/agents/${encodeURIComponent(payload.agentId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          memoryPolicy: {
            ...defaultMemoryPolicy(payload.basePolicy?.policyId || ""),
            ...(payload.basePolicy ?? {}),
            readSharedGroups: sortedIds(payload.draft.readSharedGroups),
            writeSharedGroups: sortedIds(payload.draft.writeSharedGroups),
            readKnowledgeBaseIds: sortedIds(payload.draft.readKnowledgeBaseIds),
            proposeKnowledgeBaseIds: sortedIds(payload.draft.proposeKnowledgeBaseIds),
            reviewKnowledgeBaseIds: sortedIds(payload.draft.reviewKnowledgeBaseIds),
            rateKnowledgeBaseIds: sortedIds(payload.draft.rateKnowledgeBaseIds),
          },
        }),
      }),
    onSuccess: (agent) => {
      queryClient.setQueryData<AgentConfigWorkspace | undefined>(
        queryKeys.agentConfigWorkspace(),
        (current) => updatedAgentWorkspaceCache(current, agent),
      );
      setNotice({
        tone: "success",
        text: lang === "zh" ? `已保存 ${agentLabel(agent)} 的记忆设置` : `Saved memory policy for ${agentLabel(agent)}`,
      });
      void chatWorkspaceCache.afterAgentWorkspaceChanged();
    },
    onError: (error) => {
      setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    },
  });

  const updateRuntimePolicyMutation = useMutation({
    mutationFn: (payload: {
      agentId: string;
      delegationPolicy: AgentDelegationPolicyDraft;
      supervisionPolicy: AgentSupervisionPolicyDraft;
    }) =>
      fetchJson<AgentConfigWorkspaceAgent>(`/api/agents/${encodeURIComponent(payload.agentId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          delegationPolicy: {
            allowSubagents: payload.delegationPolicy.allowSubagents,
            maxConcurrent: payload.delegationPolicy.maxConcurrent,
            maxDepth: payload.delegationPolicy.maxDepth,
            allowWakeMessages: payload.delegationPolicy.allowWakeMessages,
            allowedContextModes: sortedIds(payload.delegationPolicy.allowedContextModes),
          },
          supervisionPolicy: {
            supervisionEnabled: payload.supervisionPolicy.supervisionEnabled,
            requiresReview: payload.supervisionPolicy.requiresReview,
            reviewMode: payload.supervisionPolicy.reviewMode,
            evidenceLevel: payload.supervisionPolicy.evidenceLevel,
          },
        }),
      }),
    onSuccess: (agent) => {
      queryClient.setQueryData<AgentConfigWorkspace | undefined>(
        queryKeys.agentConfigWorkspace(),
        (current) => updatedAgentWorkspaceCache(current, agent),
      );
      setNotice({
        tone: "success",
        text: lang === "zh" ? `已保存 ${agentLabel(agent)} 的运行策略` : `Saved runtime policy for ${agentLabel(agent)}`,
      });
      void chatWorkspaceCache.afterAgentWorkspaceChanged();
      void queryClient.invalidateQueries({ queryKey: queryKeys.agentRuns(agent.agentId) });
    },
    onError: (error) => {
      setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    },
  });

  const consumeMessageMutation = useMutation({
    mutationFn: (payload: { agentId: string; messageId: string; sessionId: string }) =>
      fetchJson<AgentInboxMessage>(
        `/api/agents/${encodeURIComponent(payload.agentId)}/messages/${encodeURIComponent(payload.messageId)}/consume`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            consumedBySessionId: payload.sessionId,
            consumedByTurnId: "agent-center",
          }),
        },
      ),
    onSuccess: (_message, variables) => {
      setNotice({
        tone: "success",
        text: lang === "zh" ? "已标记消息为已处理" : "Marked message as consumed",
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.agentMessages(variables.agentId, "pending") });
      void chatWorkspaceCache.afterAgentWorkspaceChanged();
    },
    onError: (error) => {
      setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    },
  });

  const consumeAllMessagesMutation = useMutation({
    mutationFn: (payload: { agentId: string; sessionId: string }) =>
      fetchJson<{ agentId: string; consumed: boolean; consumedCount: number; remainingPendingCount: number }>(
        `/api/agents/${encodeURIComponent(payload.agentId)}/messages/consume-all`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            consumedBySessionId: payload.sessionId,
            consumedByTurnId: "agent-center",
          }),
        },
      ),
    onSuccess: (result, variables) => {
      setNotice({
        tone: "success",
        text: lang === "zh" ? `已处理 ${result.consumedCount} 条 Inbox 消息` : `Consumed ${result.consumedCount} inbox messages`,
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.agentMessages(result.agentId || variables.agentId, "pending") });
      void chatWorkspaceCache.afterAgentWorkspaceChanged();
    },
    onError: (error) => {
      setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    },
  });

  const selectedAgentAvatarUpdatePending = updateAvatarMutation.isPending && updateAvatarMutation.variables?.agentId === selectedAgent?.agentId;
  const selectedAgentAvatarUploadPending = uploadAvatarMutation.isPending && uploadAvatarMutation.variables?.agentId === selectedAgent?.agentId;
  const selectedAgentConsumeAllPending = consumeAllMessagesMutation.isPending && consumeAllMessagesMutation.variables?.agentId === selectedAgent?.agentId;
  const selectedAgentConfigPending = updateAgentMutation.isPending && updateAgentMutation.variables?.agentId === selectedAgent?.agentId;
  const selectedAgentPersonaPending = updatePersonaMutation.isPending && updatePersonaMutation.variables?.agentId === selectedAgent?.agentId;
  const selectedAgentTaskPending = updateTaskMutation.isPending && updateTaskMutation.variables?.agentId === selectedAgent?.agentId;
  const selectedAgentMembershipPending = updateMembershipMutation.isPending && updateMembershipMutation.variables?.agentId === selectedAgent?.agentId;
  const selectedAgentToolPolicyPending = updateToolPolicyMutation.isPending && updateToolPolicyMutation.variables?.agentId === selectedAgent?.agentId;
  const selectedAgentMemoryPolicyPending = updateMemoryPolicyMutation.isPending && updateMemoryPolicyMutation.variables?.agentId === selectedAgent?.agentId;
  const selectedAgentRuntimePolicyPending = updateRuntimePolicyMutation.isPending && updateRuntimePolicyMutation.variables?.agentId === selectedAgent?.agentId;
  const selectedAgentArchivePending = archiveAgentMutation.isPending && archiveAgentMutation.variables?.agentId === selectedAgent?.agentId;
  const selectedAgentPurgePending = purgeAgentMutation.isPending && purgeAgentMutation.variables?.agentId === selectedAgent?.agentId;
  const selectedAgentToolGovernanceCreatePending =
    createToolGovernanceMutation.isPending && createToolGovernanceMutation.variables?.agentId === selectedAgent?.agentId;

  const updateDraft = (patch: Partial<AgentConfigDraft>) => {
    setConfigDraft((current) => ({ ...current, ...patch }));
  };

  const updateContextCompressionDraft = (patch: Partial<AgentContextCompressionPolicyDraft>) => {
    setConfigDraft((current) => ({
      ...current,
      contextCompressionPolicy: { ...current.contextCompressionPolicy, ...patch },
    }));
  };

  const updateCreateDraft = (patch: Partial<AgentCreateDraft>) => {
    setCreateDraft((current) => ({ ...current, ...patch }));
  };

  const updateMembershipDraft = (patch: Partial<AgentModeMembershipDraft>) => {
    setMembershipDraft((current) => ({ ...current, ...patch }));
  };

  const updatePersonaDraft = (patch: Partial<AgentPersonaDraft>) => {
    setPersonaDraft((current) => ({ ...current, ...patch }));
  };

  const updateTaskDraft = (patch: Partial<AgentTaskDraft>) => {
    setTaskDraft((current) => ({ ...current, ...patch }));
  };

  const updateToolPolicyMode = (toolName: string, mode: Exclude<ToolPolicyMode, "excluded">) => {
    setToolPolicyDraft((current) => {
      const allowed = new Set(current.allowedTools);
      const preferred = new Set(current.preferredTools);
      const blocked = new Set(current.blockedTools);
      allowed.delete(toolName);
      preferred.delete(toolName);
      blocked.delete(toolName);
      if (mode === "allowed") {
        allowed.add(toolName);
      }
      if (mode === "blocked") {
        blocked.add(toolName);
      }
      return normalizeToolPolicyDraftForAgent({
        ...current,
        allowedTools: sortedIds(Array.from(allowed)),
        preferredTools: sortedIds(Array.from(preferred)),
        blockedTools: sortedIds(Array.from(blocked)),
      }, selectedAgent);
    });
  };

  const applyToolBundle = (bundle: ToolBundle, mode: ToolBundleApplyMode) => {
    setToolPolicyDraft((current) => {
      const bundleTools = sortedIds(bundle.toolNames ?? []);
      const bundlePreferred = sortedIds((bundle.preferredToolNames ?? []).filter((tool) => bundleTools.includes(tool)));
      if (mode === "replace") {
        return normalizeToolPolicyDraftForAgent({
          ...current,
          allowedTools: bundleTools,
          preferredTools: bundlePreferred,
          blockedTools: [],
        }, selectedAgent);
      }
      const allowed = new Set(current.allowedTools);
      const preferred = new Set(current.preferredTools);
      const blocked = new Set(current.blockedTools);
      for (const tool of bundleTools) {
        if (!blocked.has(tool)) {
          allowed.add(tool);
        }
      }
      for (const tool of bundlePreferred) {
        if (!blocked.has(tool)) {
          preferred.add(tool);
        }
      }
      return normalizeToolPolicyDraftForAgent({
        ...current,
        allowedTools: sortedIds(Array.from(allowed)),
        preferredTools: sortedIds(Array.from(preferred).filter((tool) => allowed.has(tool))),
        blockedTools: sortedIds(Array.from(blocked)),
      }, selectedAgent);
    });
  };

  const updateToolGovernanceDraft = (patch: Partial<AgentToolGovernanceDraft>) => {
    setToolGovernanceDraft((current) => ({ ...current, ...patch }));
  };

  const toggleToolPolicyScope = (field: "readScopes" | "writeScopes", scope: string, selected: boolean) => {
    setToolPolicyDraft((current) => {
      const scopes = new Set(current[field]);
      if (selected) {
        scopes.add(scope);
      } else {
        scopes.delete(scope);
      }
      return { ...current, [field]: sortedIds(Array.from(scopes)) };
    });
  };

  const updateMemoryDraftField = (patch: Partial<AgentMemoryPolicyDraft>) => {
    setMemoryPolicyDraft((current) => ({ ...current, ...patch }));
  };

  const addMemoryGroup = (field: "readSharedGroups" | "writeSharedGroups", value: string) => {
    const normalized = String(value || "").trim();
    if (!normalized) {
      return;
    }
    setMemoryPolicyDraft((current) => ({
      ...current,
      [field]: sortedIds([...current[field], normalized]),
      newReadGroup: field === "readSharedGroups" ? "" : current.newReadGroup,
      newWriteGroup: field === "writeSharedGroups" ? "" : current.newWriteGroup,
    }));
  };

  const removeMemoryGroup = (field: "readSharedGroups" | "writeSharedGroups", value: string) => {
    setMemoryPolicyDraft((current) => ({
      ...current,
      [field]: current[field].filter((group) => group !== value),
    }));
  };

  const addKnowledgeBaseId = (
    field: "readKnowledgeBaseIds" | "proposeKnowledgeBaseIds" | "reviewKnowledgeBaseIds" | "rateKnowledgeBaseIds",
    value: string,
  ) => {
    const normalized = String(value || "").trim();
    if (!normalized) {
      return;
    }
    setMemoryPolicyDraft((current) => ({
      ...current,
      [field]: sortedIds([...current[field], normalized]),
      newReadKnowledgeBaseId: field === "readKnowledgeBaseIds" ? "" : current.newReadKnowledgeBaseId,
      newProposeKnowledgeBaseId: field === "proposeKnowledgeBaseIds" ? "" : current.newProposeKnowledgeBaseId,
      newReviewKnowledgeBaseId: field === "reviewKnowledgeBaseIds" ? "" : current.newReviewKnowledgeBaseId,
      newRateKnowledgeBaseId: field === "rateKnowledgeBaseIds" ? "" : current.newRateKnowledgeBaseId,
    }));
  };

  const removeKnowledgeBaseId = (
    field: "readKnowledgeBaseIds" | "proposeKnowledgeBaseIds" | "reviewKnowledgeBaseIds" | "rateKnowledgeBaseIds",
    value: string,
  ) => {
    setMemoryPolicyDraft((current) => ({
      ...current,
      [field]: current[field].filter((knowledgeBaseId) => knowledgeBaseId !== value),
    }));
  };

  const updateDelegationPolicyDraft = (patch: Partial<AgentDelegationPolicyDraft>) => {
    setDelegationPolicyDraft((current) => ({ ...current, ...patch }));
  };

  const toggleDelegationContextMode = (mode: "isolated" | "fork", selected: boolean) => {
    setDelegationPolicyDraft((current) => {
      const modes = new Set(current.allowedContextModes);
      if (selected) {
        modes.add(mode);
      } else {
        modes.delete(mode);
      }
      const nextModes = sortedIds(Array.from(modes)).filter((item) => item === "isolated" || item === "fork");
      return { ...current, allowedContextModes: nextModes.length ? nextModes : ["isolated"] };
    });
  };

  const updateSupervisionPolicyDraft = (patch: Partial<AgentSupervisionPolicyDraft>) => {
    setSupervisionPolicyDraft((current) => {
      const next = { ...current, ...patch };
      if (patch.reviewMode === "required") {
        next.requiresReview = true;
      }
      if (patch.reviewMode === "disabled") {
        next.requiresReview = false;
      }
      return next;
    });
  };

  const saveAgentConfig = () => {
    if (!selectedAgent || !canSaveConfig || selectedAgentConfigPending) {
      return;
    }
    updateAgentMutation.mutate({
      agentId: selectedAgent.agentId,
      agent: selectedAgent,
      draft: configDraft,
      modelChoices: workspace?.agentModelChoices ?? [],
    });
  };

  const saveModeMembership = () => {
    if (!selectedAgent || !canSaveMembership || selectedAgentMembershipPending) {
      return;
    }
    updateMembershipMutation.mutate({ agentId: selectedAgent.agentId, draft: membershipDraft });
  };

  const savePersonaProfile = () => {
    if (!selectedAgent || !canSavePersona || selectedAgentPersonaPending) {
      return;
    }
    updatePersonaMutation.mutate({ agentId: selectedAgent.agentId, draft: personaDraft });
  };

  const saveTaskProfile = () => {
    if (!selectedAgent || !canSaveTask || selectedAgentTaskPending) {
      return;
    }
    updateTaskMutation.mutate({ agentId: selectedAgent.agentId, draft: taskDraft });
  };

  const saveToolPolicy = () => {
    if (!selectedAgent || !canSaveToolPolicy || selectedAgentToolPolicyPending) {
      return;
    }
    const saveDraft = normalizeToolPolicyDraftForAgent(toolPolicyDraft, selectedAgent);
    updateToolPolicyMutation.mutate({
      agentId: selectedAgent.agentId,
      draft: saveDraft,
      basePolicy: selectedAgent.toolPolicy,
    });
  };

  const submitToolGovernanceRequest = () => {
    if (!selectedAgent || !canSubmitToolGovernance || selectedAgentToolGovernanceCreatePending) {
      setNotice({ tone: "error", text: copy.toolGovernanceNoDelta });
      return;
    }
    createToolGovernanceMutation.mutate({
      agentId: selectedAgent.agentId,
      draft: toolGovernanceDraft,
      delta: toolGovernanceDelta,
    });
  };

  const resolveToolGovernanceRequest = (request: AgentToolGovernanceRequest, decision: "approve" | "reject") => {
    const requestPending =
      resolveToolGovernanceMutation.isPending
      && resolveToolGovernanceMutation.variables?.agentId === request.targetAgentId
      && resolveToolGovernanceMutation.variables?.requestId === request.requestId;
    if (!request.targetAgentId || !request.requestId || requestPending) {
      return;
    }
    resolveToolGovernanceMutation.mutate({
      agentId: request.targetAgentId,
      requestId: request.requestId,
      decision,
    });
  };

  const saveMemoryPolicy = () => {
    if (!selectedAgent || !canSaveMemoryPolicy || selectedAgentMemoryPolicyPending) {
      return;
    }
    updateMemoryPolicyMutation.mutate({
      agentId: selectedAgent.agentId,
      draft: memoryPolicyDraft,
      basePolicy: selectedAgent.memoryPolicy,
    });
  };

  const saveRuntimePolicy = () => {
    if (!selectedAgent || !canSaveRuntimePolicy || selectedAgentRuntimePolicyPending) {
      return;
    }
    updateRuntimePolicyMutation.mutate({
      agentId: selectedAgent.agentId,
      delegationPolicy: delegationPolicyDraft,
      supervisionPolicy: supervisionPolicyDraft,
    });
  };

  const createAgent = () => {
    if (!canCreateAgent || createAgentMutation.isPending) {
      return;
    }
    createAgentMutation.mutate(createDraft);
  };

  const toggleBulkAgent = (agentId: string, selected: boolean, extendRange = false) => {
    setSelectedBulkAgentIds((current) => {
      const next = new Set(current);
      if (extendRange && bulkSelectionAnchorAgentId) {
        const anchorIndex = visibleAgents.findIndex((agent) => agent.agentId === bulkSelectionAnchorAgentId);
        const targetIndex = visibleAgents.findIndex((agent) => agent.agentId === agentId);
        if (anchorIndex >= 0 && targetIndex >= 0) {
          const [start, end] = anchorIndex <= targetIndex ? [anchorIndex, targetIndex] : [targetIndex, anchorIndex];
          visibleAgents.slice(start, end + 1).forEach((agent) => {
            if (selected) {
              next.add(agent.agentId);
            } else {
              next.delete(agent.agentId);
            }
          });
          return next;
        }
      }
      if (selected) {
        next.add(agentId);
      } else {
        next.delete(agentId);
      }
      return next;
    });
    setBulkSelectionAnchorAgentId(agentId);
  };

  const handleAgentRowSelect = (agent: AgentConfigWorkspaceAgent, event: MouseEvent<HTMLButtonElement>) => {
    if (event.ctrlKey || event.metaKey || event.shiftKey) {
      event.preventDefault();
      toggleBulkAgent(agent.agentId, event.shiftKey ? true : !selectedBulkAgentIds.has(agent.agentId), event.shiftKey);
      return;
    }
    setSelectedAgentId(agent.agentId);
    setBulkSelectionAnchorAgentId(agent.agentId);
  };

  const selectVisibleBulkAgents = () => {
    setSelectedBulkAgentIds(new Set(visibleAgents.map((agent) => agent.agentId)));
    setBulkSelectionAnchorAgentId(visibleAgents[0]?.agentId ?? "");
  };

  const clearBulkAgents = () => {
    setSelectedBulkAgentIds(new Set());
    setBulkSelectionAnchorAgentId("");
  };

  const updateBulkConfigDraft = (patch: Partial<AgentBulkConfigDraft>) => {
    setBulkConfigDraft((current) => ({ ...current, ...patch }));
  };

  const toggleBulkConfigApply = (field: AgentBulkConfigField, selected: boolean) => {
    setBulkConfigApply((current) => ({ ...current, [field]: selected }));
  };

  const bulkApplyAgentConfig = async () => {
    if (bulkAgentPending) {
      return;
    }
    if (selectedBulkAgents.length < 2) {
      setNotice({ tone: "error", text: copy.bulkNoSelection });
      return;
    }
    if (!bulkConfigReady(bulkConfigDraft, bulkConfigApply)) {
      setNotice({ tone: "error", text: copy.bulkNoConfigFields });
      return;
    }

    setBulkAgentPending(true);
    let success = 0;
    let skipped = 0;
    let failed = 0;
    const notes: string[] = [];
    const agentsById = new Map(selectedBulkAgents.map((agent) => [agent.agentId, agent]));

    try {
      const response = await fetchJson<AgentBulkConfigResponse>("/api/agents/bulk-config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          agentIds: selectedBulkAgents.map((agent) => agent.agentId),
          applyFields: bulkConfigApplyFields(bulkConfigApply),
          patch: bulkConfigPatchFromDraft(bulkConfigDraft, bulkConfigApply),
        }),
      });
      queryClient.setQueryData<AgentConfigWorkspace | undefined>(
        queryKeys.agentConfigWorkspace(),
        (current) => bulkUpdatedAgentWorkspaceCache(current, response.success),
      );
      success = response.summary.successCount;
      skipped = response.summary.skippedCount;
      failed = response.summary.failedCount;
      response.skipped.forEach((item) => notes.push(agentBulkActionItemNote(item, agentsById, copy.bulkSkippedProtected)));
      response.failed.forEach((item) => notes.push(agentBulkActionItemNote(item, agentsById, "")));
    } catch (error) {
      failed = selectedBulkAgents.length;
      notes.push(error instanceof Error ? error.message : String(error));
    }

    setBulkAgentPending(false);
    setNotice({
      tone: failed > 0 ? "error" : "success",
      text: agentBulkActionSummary(copy.bulkConfigResult, success, skipped, failed, notes, lang),
    });
    void chatWorkspaceCache.afterAgentWorkspaceChanged();
  };

  const bulkApplyPromptTemplate = async () => {
    if (bulkAgentPending) {
      return;
    }
    if (!selectedBulkAgents.length) {
      setNotice({ tone: "error", text: copy.bulkNoSelection });
      return;
    }
    if (!bulkPromptTemplateId) {
      setNotice({ tone: "error", text: copy.bulkNoPrompt });
      return;
    }

    setBulkAgentPending(true);
    let success = 0;
    let skipped = 0;
    let failed = 0;
    const notes: string[] = [];
    const agentsById = new Map(selectedBulkAgents.map((agent) => [agent.agentId, agent]));

    try {
      const response = await fetchJson<AgentBulkPromptTemplateResponse>("/api/agents/bulk-prompt-template", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ agentIds: selectedBulkAgents.map((agent) => agent.agentId), promptTemplateId: bulkPromptTemplateId }),
      });
      queryClient.setQueryData<AgentConfigWorkspace | undefined>(
        queryKeys.agentConfigWorkspace(),
        (current) => bulkUpdatedAgentWorkspaceCache(current, response.success),
      );
      success = response.summary.successCount;
      skipped = response.summary.skippedCount;
      failed = response.summary.failedCount;
      response.skipped.forEach((item) => notes.push(agentBulkActionItemNote(item, agentsById, copy.bulkSkippedArchived)));
      response.failed.forEach((item) => notes.push(agentBulkActionItemNote(item, agentsById, copy.bulkSkippedActive)));
    } catch (error) {
      failed = selectedBulkAgents.length;
      notes.push(error instanceof Error ? error.message : String(error));
    }

    setBulkAgentPending(false);
    setNotice({
      tone: failed > 0 ? "error" : "success",
      text: agentBulkActionSummary(copy.bulkPromptResult, success, skipped, failed, notes, lang),
    });
    clearBulkAgents();
    void chatWorkspaceCache.afterAgentWorkspaceChanged();
  };

  const bulkArchiveAgents = async () => {
    if (bulkAgentPending) {
      return;
    }
    if (!selectedBulkAgents.length) {
      setNotice({ tone: "error", text: copy.bulkNoSelection });
      return;
    }
    const confirmed = window.confirm(copy.bulkArchiveConfirm);
    if (!confirmed) {
      return;
    }

    setBulkAgentPending(true);
    const notes: string[] = [];
    const archivedAgents = selectedBulkAgents.filter((agent) => agent.status === "archived");
    const protectedAgents = selectedBulkAgents.filter((agent) => agent.status !== "archived" && agentArchiveProtected(agent));
    const archiveAgents = selectedBulkAgents.filter((agent) => agent.status !== "archived" && !agentArchiveProtected(agent));
    archivedAgents.forEach((agent) => notes.push(`${agentLabel(agent)}: ${copy.bulkSkippedArchived}`));
    protectedAgents.forEach((agent) => notes.push(`${agentLabel(agent)}: ${copy.bulkSkippedProtected}`));
    const agentsById = new Map(selectedBulkAgents.map((agent) => [agent.agentId, agent]));
    let success = 0;
    let skipped = archivedAgents.length + protectedAgents.length;
    let failed = 0;
    let archivedSelectedAgent = false;

    try {
      if (archiveAgents.length) {
        const response = await fetchJson<AgentBulkActionResponse>("/api/agents/bulk-archive", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ agentIds: archiveAgents.map((agent) => agent.agentId) }),
        });
        response.success.forEach((item) => {
          const archivedAgent = item as AgentConfigWorkspaceAgent;
          if (archivedAgent.agentId === selectedAgent?.agentId) {
            archivedSelectedAgent = true;
          }
          if (archivedAgent.agentId) {
            queryClient.setQueryData<AgentConfigWorkspace | undefined>(
              queryKeys.agentConfigWorkspace(),
              (current) => archivedWorkspaceCache(current, archivedAgent),
            );
          }
        });
        response.skipped.forEach((item) => notes.push(agentBulkActionItemNote(item, agentsById, copy.bulkSkippedArchived)));
        response.failed.forEach((item) => notes.push(agentBulkActionItemNote(item, agentsById, "")));
        success += response.summary.successCount;
        skipped += response.summary.skippedCount;
        failed += response.summary.failedCount;
      }
    } catch (error) {
      failed += archiveAgents.length;
      notes.push(error instanceof Error ? error.message : String(error));
    }

    if (archivedSelectedAgent && success > 0) {
      setSelectedAgentId("");
      setActivePane("overview");
    }
    setBulkAgentPending(false);
    setNotice({
      tone: failed > 0 ? "error" : "success",
      text: agentBulkActionSummary(copy.bulkArchiveResult, success, skipped, failed, notes, lang),
    });
    clearBulkAgents();
    void chatWorkspaceCache.afterAgentArchived();
  };

  const bulkPurgeAgents = async () => {
    if (bulkAgentPending) {
      return;
    }
    if (!selectedBulkAgents.length) {
      setNotice({ tone: "error", text: copy.bulkNoSelection });
      return;
    }
    const confirmed = window.confirm(copy.bulkPurgeConfirm);
    if (!confirmed) {
      return;
    }

    setBulkAgentPending(true);
    const notes: string[] = [];
    const protectedAgents = selectedBulkAgents.filter((agent) => agentArchiveProtected(agent));
    const activeAgents = selectedBulkAgents.filter((agent) => !agentArchiveProtected(agent) && agent.status !== "archived");
    const purgeAgents = selectedBulkAgents.filter((agent) => !agentArchiveProtected(agent) && agent.status === "archived");
    protectedAgents.forEach((agent) => notes.push(`${agentLabel(agent)}: ${copy.bulkSkippedProtected}`));
    activeAgents.forEach((agent) => notes.push(`${agentLabel(agent)}: ${copy.bulkSkippedActive}`));
    const agentsById = new Map(selectedBulkAgents.map((agent) => [agent.agentId, agent]));
    let success = 0;
    let skipped = protectedAgents.length + activeAgents.length;
    let failed = 0;
    let purgedSelectedAgent = false;

    try {
      if (purgeAgents.length) {
        const response = await fetchJson<AgentBulkActionResponse>("/api/agents/bulk-purge", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ agentIds: purgeAgents.map((agent) => agent.agentId) }),
        });
        queryClient.setQueryData<AgentConfigWorkspace | undefined>(
          queryKeys.agentConfigWorkspace(),
          (current) => bulkPurgeWorkspaceCache(current, response),
        );
        purgedSelectedAgent = response.success.some((item) => item.agentId === selectedAgent?.agentId);
        response.skipped.forEach((item) => notes.push(agentBulkActionItemNote(item, agentsById, copy.bulkSkippedActive)));
        response.failed.forEach((item) => notes.push(agentBulkActionItemNote(item, agentsById, "")));
        success += response.summary.successCount;
        skipped += response.summary.skippedCount;
        failed += response.summary.failedCount;
      }
    } catch (error) {
      failed += purgeAgents.length;
      notes.push(error instanceof Error ? error.message : String(error));
    }

    if (purgedSelectedAgent && success > 0) {
      setSelectedAgentId("");
      setActivePane("overview");
    }
    setBulkAgentPending(false);
    setNotice({
      tone: failed > 0 ? "error" : "success",
      text: agentBulkActionSummary(copy.bulkPurgeResult, success, skipped, failed, notes, lang),
    });
    clearBulkAgents();
    void chatWorkspaceCache.afterAgentArchived();
  };

  const archiveSelectedAgent = () => {
    if (!selectedAgent || !canArchiveAgent || selectedAgentArchivePending) {
      return;
    }
    const confirmed = window.confirm(copy.archiveConfirm.replace("{name}", agentLabel(selectedAgent)));
    if (!confirmed) {
      return;
    }
    archiveAgentMutation.mutate({ agentId: selectedAgent.agentId });
  };

  const purgeSelectedAgent = () => {
    if (!selectedAgent || !canPurgeAgent || selectedAgentPurgePending) {
      return;
    }
    const confirmed = window.confirm(copy.purgeConfirm.replace("{name}", agentLabel(selectedAgent)));
    if (!confirmed) {
      return;
    }
    purgeAgentMutation.mutate({ agentId: selectedAgent.agentId });
  };

  const updateResetOption = (key: keyof AgentResetOptions, value: boolean) => {
    setResetOptions((current) => ({ ...current, [key]: value }));
  };

  const resetSelectedAgent = () => {
    if (!selectedAgent || !canResetAgent || resettingAgentIds.has(selectedAgent.agentId)) {
      return;
    }
    const confirmed = window.confirm(copy.resetAgentConfirm.replace("{name}", agentLabel(selectedAgent)));
    if (!confirmed) {
      return;
    }
    resetAgentMutation.mutate({ agentId: selectedAgent.agentId, options: resetOptions });
  };

  const resetSelectedAgentAvatar = () => {
    if (!selectedAgent?.agentId || selectedAgentAvatarUpdatePending) {
      return;
    }
    updateAvatarMutation.mutate({ agentId: selectedAgent.agentId, resetToDefault: true });
  };

  const selectAgentAvatar = (avatarImagePath: string) => {
    if (!selectedAgent?.agentId || selectedAgentAvatarUpdatePending) {
      return;
    }
    updateAvatarMutation.mutate({ agentId: selectedAgent.agentId, avatarImagePath });
  };

  const uploadSelectedAgentAvatar = (file: File | undefined) => {
    if (!selectedAgent?.agentId || !file || selectedAgentAvatarUploadPending) {
      return;
    }
    uploadAvatarMutation.mutate({ agentId: selectedAgent.agentId, file });
  };

  const consumeInboxMessage = (message: AgentInboxMessage) => {
    if (!selectedAgent?.agentId) {
      return;
    }
    const messageId = String(message.messageId || message.eventId || "").trim();
    const messagePending =
      consumeMessageMutation.isPending
      && consumeMessageMutation.variables?.agentId === selectedAgent.agentId
      && consumeMessageMutation.variables?.messageId === messageId;
    if (!messageId || messagePending) {
      return;
    }
    consumeMessageMutation.mutate({
      agentId: selectedAgent.agentId,
      messageId,
      sessionId: selectedAgent.directSessionId || message.targetSessionId || "",
    });
  };

  const consumeAllInboxMessages = () => {
    if (!selectedAgent?.agentId || selectedAgentConsumeAllPending) {
      return;
    }
    consumeAllMessagesMutation.mutate({
      agentId: selectedAgent.agentId,
      sessionId: selectedAgent.directSessionId || "",
    });
  };

  const openAgentSession = (sessionId: string) => {
    const normalized = String(sessionId || selectedAgent?.directSessionId || "").trim();
    if (!normalized) {
      return;
    }
    void navigate(`/chat?session=${encodeURIComponent(normalized)}`);
  };

  const openAgentLogs = (evidence: AgentRuntimeEvidenceMatch | null | undefined) => {
    if (evidence?.runtimeSceneId) {
      const rawRef = evidence.rawRefs?.[0]?.path || "";
      const params = new URLSearchParams({ root: "runtime_scenes", scene: evidence.runtimeSceneId });
      if (rawRef) {
        params.set("path", rawRef);
      }
      void navigate(`/logs?${params.toString()}`);
      return;
    }
    void navigate("/logs");
  };

  const focusInboxMessage = (messageId: string) => {
    const normalized = String(messageId || "").trim();
    if (normalized) {
      setFocusedMessageId(normalized);
    }
  };

  const renderAgentRow = (agent: AgentConfigWorkspaceAgent) => {
    const active = selectedAgent?.agentId === agent.agentId;
    const tone = issueTone(agent.health);
    const display = agentDisplayInfo(agent, lang);
    const modelDisplay = agentDialogueModelDisplay(agent, lang);
    const bulkSelected = selectedBulkAgentIds.has(agent.agentId);
    const rowClassName = [
      styles.agentRow,
      active ? styles.agentRowActive : "",
      bulkSelected ? styles.agentRowBulkSelected : "",
    ].filter(Boolean).join(" ");
    return (
      <div key={agent.agentId} className={styles.agentRowShell}>
        <label className={styles.rowSelect} title={`${copy.bulkSelected}: ${display.name}`}>
          <input
            type="checkbox"
            checked={bulkSelected}
            aria-label={`${copy.bulkSelected}: ${display.name}`}
            onChange={(event) => toggleBulkAgent(
              agent.agentId,
              event.target.checked,
              Boolean((event.nativeEvent as globalThis.MouseEvent).shiftKey),
            )}
          />
          {bulkSelected ? <CheckSquare size={15} /> : <Square size={15} />}
        </label>
        <button
          type="button"
          className={rowClassName}
          onClick={(event) => handleAgentRowSelect(agent, event)}
        >
          <span className={styles.agentIdentity}>
            {renderAgentAvatar(
              styles.agentAvatar,
              agent.avatarImageUrl,
              avatarInitials(agent.agentCode, display.name),
            )}
            <span className={styles.agentIdentityCopy}>
              <strong>{display.name}</strong>
              <em className={`${styles.agentRoleTag} ${styles[`agentRoleTag_${display.tone}`]}`}>
                {display.functionLabel}
              </em>
            </span>
          </span>
          <span title={modelDisplay.detail}>{modelDisplay.label}</span>
          <span>{promptTemplateDisplayName(agent.promptTemplate, agent.promptTemplateId, lang)}</span>
          <span className={`${styles.runtimePill} ${styles[`runtime_${runtimeStatusTone(agent)}`]}`}>
            {runtimeStatusLabel(agent, lang)}
          </span>
          <span className={styles.modeList}>
            {uniqueModes(agent).slice(0, 3).map((mode) => (
              <em key={`${agent.agentId}:${mode}`}>{modeLabel(mode, lang)}</em>
            ))}
          </span>
          <span className={styles.healthCell}>
            <span className={`${styles.issuePill} ${styles[`issue_${tone}`]}`}>
              {issueLabel(agent.health, lang)}
            </span>
            <small>{issueSummary(agent.health, lang)}</small>
          </span>
        </button>
      </div>
    );
  };

  return (
    <section className={styles.route}>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>{copy.eyebrow}</p>
          <h1 className={styles.title}>{copy.title}</h1>
          <p className={styles.subtitle}>{copy.subtitle}</p>
        </div>
        <span
          className={`${styles.healthPill} ${styles[`health_${healthStatus}`]}`}
          title={healthStatusDescription}
          aria-label={`${copy.workspaceHealthStatus}: ${healthStatusLabel}. ${healthStatusDescription}`}
        >
          {healthStatusLabel}
        </span>
        <button type="button" className={styles.refreshButton} onClick={refresh}>
          <RefreshCw size={16} />
          {copy.refresh}
        </button>
      </header>

      <div className={styles.controlStrip}>
        <AgentManagementNav active="agents" className={styles.managementNav} />

        <div className={styles.summaryGrid}>
          <section className={styles.summaryCard}>
            <span>{copy.allAgents}</span>
            <strong>{summary?.agentCount ?? 0}</strong>
          </section>
          <section className={styles.summaryCard}>
            <span>{copy.activeAgents}</span>
            <strong>{summary?.activeAgentCount ?? 0}</strong>
          </section>
          <section className={styles.summaryCard}>
            <span>{copy.archivedAgents}</span>
            <strong>{summary?.archivedAgentCount ?? 0}</strong>
          </section>
          <section className={styles.summaryCard}>
            <span>{copy.teams}</span>
            <strong>{summary?.teamCount ?? 0}</strong>
          </section>
          <section className={styles.summaryCard}>
            <span>{copy.healthIssues}</span>
            <strong>{summary?.healthIssueCount ?? 0}</strong>
          </section>
          <section className={styles.summaryCard}>
            <span>{copy.chatRooms}</span>
            <strong>{summary?.chatRoomCount ?? 0}</strong>
          </section>
          <section className={styles.summaryCard}>
            <span>{copy.inbox}</span>
            <strong>{summary?.inboxPendingCount ?? 0}</strong>
          </section>
          <section className={styles.summaryCard}>
            <span>{copy.runningAgents}</span>
            <strong>{summary?.runningAgentCount ?? 0}</strong>
          </section>
          <section className={styles.summaryCard}>
            <span>{copy.blockedAgents}</span>
            <strong>{summary?.blockedAgentCount ?? 0}</strong>
          </section>
        </div>
      </div>

      <div className={createOpen ? `${styles.workspace} ${styles.workspaceCreating}` : styles.workspace}>
        <aside className={styles.filterPanel}>
          <label className={styles.searchBox}>
            <Search size={15} />
            <input value={searchText} placeholder={copy.search} onChange={(event) => setSearchText(event.target.value)} />
          </label>
          <nav className={styles.groupList} aria-label={copy.agentFilters}>
            {groupedFilters.map((section) => (
              <section key={section.id} className={styles.groupSection}>
                <p className={styles.groupSectionTitle}>{section.label}</p>
                <div className={styles.groupSectionItems}>
                  {section.groups.map((group) => {
                    const active = activeFilter === group.id;
                    const description = groupDescription(group, copy);
                    const displayLabel = groupDisplayLabel(group, copy);
                    return (
                      <button
                        key={group.id}
                        type="button"
                        className={active ? `${styles.groupButton} ${styles.groupButtonActive}` : styles.groupButton}
                        onClick={() => {
                          setActiveFilter(group.id);
                          setSelectedAgentId("");
                        }}
                        aria-label={groupAriaLabel(displayLabel, group, copy, lang)}
                        title={description}
                      >
                        <span>
                          {section.id === "management" ? <CheckCircle2 size={15} /> : section.id === "boundary" ? <UserRound size={15} /> : section.id === "team_index" ? <Users size={15} /> : group.id === "needs_review" ? <AlertTriangle size={15} /> : <Bot size={15} />}
                          {displayLabel}
                        </span>
                        <strong>{group.count}</strong>
                        {group.healthCount ? (
                          <em>{group.id === "setup:inbox" ? copy.statusReminderShort : copy.healthIssueShort} {group.healthCount}</em>
                        ) : null}
                      </button>
                    );
                  })}
                </div>
              </section>
            ))}
            {advancedGroupedFilters.length ? (
              <details className={styles.advancedFilterSection}>
                <summary className={styles.advancedFilterSummary}>
                  <span>{copy.moreFilters}</span>
                  <strong>{advancedFilterCount}</strong>
                </summary>
                <div className={styles.advancedFilterBody}>
                  {advancedGroupedFilters.map((section) => (
                    <section key={section.id} className={styles.groupSection}>
                      <p className={styles.groupSectionTitle}>{section.label}</p>
                      <div className={styles.groupSectionItems}>
                        {section.groups.map((group) => {
                          const active = activeFilter === group.id;
                          const description = groupDescription(group, copy);
                          const displayLabel = groupDisplayLabel(group, copy);
                          return (
                            <button
                              key={group.id}
                              type="button"
                              className={active ? `${styles.groupButton} ${styles.groupButtonActive}` : styles.groupButton}
                              onClick={() => {
                                setActiveFilter(group.id);
                                setSelectedAgentId("");
                              }}
                              aria-label={groupAriaLabel(displayLabel, group, copy, lang)}
                              title={description}
                            >
                              <span>
                                {section.id === "source_scope" ? <Database size={15} /> : section.id === "reference" ? <Users size={15} /> : <Layers3 size={15} />}
                                {displayLabel}
                              </span>
                              <strong>{group.count}</strong>
                              {group.healthCount ? (
                                <em>{group.id === "setup:inbox" ? copy.statusReminderShort : copy.healthIssueShort} {group.healthCount}</em>
                              ) : null}
                            </button>
                          );
                        })}
                      </div>
                    </section>
                  ))}
                </div>
              </details>
            ) : null}
          </nav>
          <section className={styles.storagePanel}>
            <p className={styles.panelEyebrow}>{copy.readOnly}</p>
            <code>{workspace?.storage.agentRegistryPath ?? "workspace/agents/agents.json"}</code>
            <code>{workspace?.storage.modeBindingPath ?? "workspace/agent_config/mode_bindings.json"}</code>
          </section>
        </aside>

        <main className={createOpen ? `${styles.agentPanel} ${styles.agentPanelCreating}` : styles.agentPanel}>
          <div className={styles.panelHeader}>
            <div>
              <p className={styles.panelEyebrow}>{copy.agentFilters}</p>
              <h2>{activeGroupLabel}</h2>
            </div>
            <div className={styles.panelHeaderActions}>
              <button
                type="button"
                className={styles.secondaryButton}
                onClick={() => setCreateOpen((value) => !value)}
              >
                <Plus size={15} />
                {copy.createAgent}
              </button>
              <span className={styles.countPill}>{visibleAgents.length}</span>
            </div>
          </div>
          {createOpen ? (
            <section className={styles.createAgentPanel} title={copy.createAgentHint}>
              <div className={styles.panelHeader}>
                <div>
                  <p className={styles.panelEyebrow}>{copy.createAgentTitle}</p>
                  <h3>{copy.createAgent}</h3>
                </div>
                <Bot size={16} />
              </div>
              <div className={styles.createAgentGrid}>
                <label className={styles.field}>
                  <span>{copy.createAgentName}</span>
                  <input
                    value={createDraft.displayName}
                    placeholder={copy.createAgentNamePlaceholder}
                    onChange={(event) => updateCreateDraft({ displayName: event.target.value })}
                  />
                </label>
                <label className={styles.field}>
                  <span>{copy.model}</span>
                  <select
                    value={agentLlmSlotModelId(createDraft.llmBindings, FALLBACK_AGENT_LLM_SLOTS[0])}
                    onChange={(event) => updateCreateDraft({
                      llmBindings: updateAgentLlmSlotBinding(createDraft.llmBindings, FALLBACK_AGENT_LLM_SLOTS[0], event.target.value),
                    })}
                  >
                    {agentModelChoices.map((model) => (
                      <option key={model.key} value={model.modelId} title={model.modelLabel || model.modelId}>
                        {model.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label className={styles.field}>
                  <span>{copy.modeMembership}</span>
                  <select
                    value={createDraft.primaryMode}
                    onChange={(event) => {
                      const primaryMode = event.target.value;
                      updateCreateDraft({
                        primaryMode,
                        selectedToolBundleIds: toolBundleIdsForModeChange(createDraft, primaryMode, toolBundles),
                      });
                    }}
                  >
                    {AGENT_PRIMARY_MODE_OPTIONS.map((mode) => (
                      <option key={mode} value={mode}>
                        {modeLabel(mode, lang)}
                      </option>
                    ))}
                  </select>
                </label>
                {!createDraftIsWorkSession ? (
                  <label className={styles.field}>
                    <span>{copy.createAgentRole}</span>
                    <input
                      value={createDraft.roleKey}
                      placeholder={copy.createAgentRolePlaceholder}
                      onChange={(event) => updateCreateDraft({ roleKey: event.target.value })}
                    />
                  </label>
                ) : null}
                <label className={styles.field}>
                  <span>{copy.prompt}</span>
                  <select value={createDraft.promptTemplateId} onChange={(event) => updateCreateDraft({ promptTemplateId: event.target.value })}>
                    <option value="">-</option>
                    {workspace?.promptTemplates.map((template) => (
                      <option key={template.promptTemplateId || template.templateId} value={template.promptTemplateId || template.templateId || ""}>
                        {promptTemplateOptionLabel(template, lang)}
                      </option>
                    ))}
                  </select>
                </label>
                {!createDraftIsWorkSession ? (
                  <>
                    <label className={styles.fieldWide}>
                      <span>{copy.createAgentPersonaSummary}</span>
                      <textarea
                        value={createDraft.personaSummary}
                        placeholder={copy.createAgentPersonaPlaceholder}
                        onChange={(event) => updateCreateDraft({ personaSummary: event.target.value })}
                      />
                    </label>
                    <label className={styles.fieldWide}>
                      <span>{copy.createAgentTaskMission}</span>
                      <textarea
                        value={createDraft.taskMission}
                        placeholder={copy.createAgentTaskMissionPlaceholder}
                        onChange={(event) => updateCreateDraft({ taskMission: event.target.value })}
                      />
                    </label>
                  </>
                ) : null}
                <section className={styles.fieldWide} title={copy.createAgentToolBundlesHint}>
                  <span>{copy.createAgentToolBundles}</span>
                  {toolBundles.length ? (
                    <div className={styles.createToolBundleGrid}>
                      {toolBundles.map((bundle) => {
                        const selected = createDraft.selectedToolBundleIds.includes(bundle.bundleId);
                        return (
                          <label
                            key={bundle.bundleId}
                            className={selected ? styles.createToolBundleSelected : styles.createToolBundleOption}
                            title={[bundle.label, toolBundleMeta(bundle, lang), bundle.description].filter(Boolean).join("\n")}
                          >
                            <input
                              type="checkbox"
                              checked={selected}
                              onChange={(event) => {
                                const next = new Set(createDraft.selectedToolBundleIds);
                                if (event.target.checked) {
                                  next.add(bundle.bundleId);
                                } else {
                                  next.delete(bundle.bundleId);
                                }
                                updateCreateDraft({ selectedToolBundleIds: sortedIds(Array.from(next)) });
                              }}
                            />
                            <span>
                              <strong>{bundle.label}</strong>
                              <small>{toolBundleMeta(bundle, lang)}</small>
                            </span>
                          </label>
                        );
                      })}
                    </div>
                  ) : (
                    <input
                      value={createDraft.allowedTools}
                      placeholder={copy.createAgentAllowedToolsPlaceholder}
                      onChange={(event) => updateCreateDraft({ allowedTools: event.target.value })}
                    />
                  )}
                </section>
                <section className={`${styles.fieldWide} ${styles.createToolBundlePreview}`}>
                  <span>{copy.createAgentToolBundlePreview}</span>
                  <strong>{createToolBundleSummaryValue.label}</strong>
                  <small>{createToolBundleSummaryValue.meta || copy.createAgentToolBundleEmpty}</small>
                </section>
              </div>
              {notice ? (
                <p className={notice.tone === "error" ? styles.errorText : styles.successText}>{notice.text}</p>
              ) : null}
              <div className={styles.editorActions}>
                <button
                  type="button"
                  className={styles.secondaryButton}
                  disabled={createAgentMutation.isPending}
                  onClick={() => {
                    setCreateOpen(false);
                    setCreateDraft(createDraftFromWorkspace(workspace, toolBundles));
                  }}
                >
                  {copy.cancelCreate}
                </button>
                <button
                  type="button"
                  className={styles.primaryButton}
                  disabled={!canCreateAgent || createAgentMutation.isPending}
                  onClick={createAgent}
                >
                  <Plus size={15} />
                  {createAgentMutation.isPending ? copy.creatingAgent : copy.createAgent}
                </button>
              </div>
            </section>
          ) : null}
          {!createOpen ? (
            <section className={styles.bulkActionBar} aria-label={copy.bulkSelected}>
              <div className={styles.bulkSummary}>
                <CheckSquare size={15} />
                <strong>{copy.bulkSelected}</strong>
                <span>{selectedBulkAgents.length} / {visibleAgents.length}</span>
              </div>
              <button
                type="button"
                className={styles.secondaryButton}
                disabled={!visibleAgents.length || bulkAgentPending}
                onClick={allVisibleAgentsSelected ? clearBulkAgents : selectVisibleBulkAgents}
              >
                {allVisibleAgentsSelected ? <Square size={14} /> : <CheckSquare size={14} />}
                <span>{allVisibleAgentsSelected ? copy.bulkClear : copy.bulkSelectVisible}</span>
              </button>
              <button type="button" className={styles.secondaryButton} disabled={!selectedBulkAgents.length || bulkAgentPending} onClick={clearBulkAgents}>
                <Square size={14} />
                <span>{copy.bulkClear}</span>
              </button>
              <label className={styles.bulkPromptPicker}>
                <span>{copy.bulkPromptLabel}</span>
                <select
                  value={bulkPromptTemplateId}
                  disabled={bulkAgentPending}
                  onChange={(event) => setBulkPromptTemplateId(event.target.value)}
                >
                  <option value="">{copy.bulkPromptPlaceholder}</option>
                  {workspace?.promptTemplates.map((template) => (
                    <option key={template.promptTemplateId || template.templateId} value={template.promptTemplateId || template.templateId || ""}>
                      {promptTemplateOptionLabel(template, lang)}
                    </option>
                  ))}
                </select>
              </label>
              <button
                type="button"
                className={styles.primaryButton}
                disabled={!selectedBulkAgents.length || !bulkPromptTemplateId || bulkAgentPending}
                onClick={bulkApplyPromptTemplate}
              >
                <CheckCircle2 size={14} />
                <span>{bulkAgentPending ? copy.bulkWorking : copy.bulkApplyPrompt}</span>
              </button>
              <button type="button" className={styles.secondaryButton} disabled={!selectedBulkAgents.length || bulkAgentPending} onClick={bulkArchiveAgents}>
                <Archive size={14} />
                <span>{bulkAgentPending ? copy.bulkWorking : copy.bulkArchive}</span>
              </button>
              <button type="button" className={styles.dangerButton} disabled={!selectedBulkAgents.length || bulkAgentPending} onClick={bulkPurgeAgents}>
                <Trash2 size={14} />
                <span>{bulkAgentPending ? copy.bulkWorking : copy.bulkPurge}</span>
              </button>
            </section>
          ) : null}
          {workspaceQuery.isError ? (
            <section className={styles.emptyState}>
              <AlertTriangle size={22} />
              <strong>{copy.loadFailed}</strong>
              <p>{workspaceQuery.error instanceof Error ? workspaceQuery.error.message : String(workspaceQuery.error)}</p>
            </section>
          ) : workspaceQuery.isPending && !workspace ? (
            <section className={styles.emptyState}>
              <RefreshCw size={22} />
              <strong>{copy.loading}</strong>
            </section>
          ) : visibleAgents.length === 0 ? (
            <section className={styles.emptyState}>
              <Bot size={22} />
              <strong>{copy.noAgents}</strong>
            </section>
          ) : (
            <div className={styles.agentColumnGrid}>
              {visibleAgentColumns.map((column) => (
                <section key={column.id} className={styles.agentColumn} aria-label={column.label}>
                  <div className={styles.agentColumnHeader}>
                    <div>
                      <strong>{column.label}</strong>
                      <span>{column.description}</span>
                    </div>
                    <em>{column.agents.length}</em>
                  </div>
                  <div className={styles.agentTable}>
                    <div className={styles.agentTableHead}>
                      <span>Agent</span>
                      <span>{copy.model}</span>
                      <span>{copy.prompt}</span>
                      <span>{copy.runtimeStatus}</span>
                      <span>{copy.modeMembership}</span>
                      <span>{copy.statusReminders}</span>
                    </div>
                    {column.agents.map(renderAgentRow)}
                  </div>
                </section>
              ))}
            </div>
          )}
        </main>

        <aside className={styles.detailPanel}>
          {returnToPath ? (
            <section className={styles.returnBanner} aria-label={copy.returnBannerTitle} title={copy.returnBannerHint}>
              <div className={styles.returnBannerCopy}>
                <strong>{copy.returnBannerTitle}</strong>
              </div>
              <button
                type="button"
                className={styles.returnBannerButton}
                onClick={() => navigate(returnToPath)}
                title={returnToLabel}
              >
                <ArrowLeft size={16} />
                <span>{returnToLabel}</span>
              </button>
            </section>
          ) : null}
          {selectedBulkAgents.length > 1 ? (
            <section className={styles.configEditor}>
              <div className={styles.panelHeader}>
                <div>
                  <p className={styles.panelEyebrow}>{copy.bulkEditTitle}</p>
                  <h3>{copy.bulkEditSelected}: {selectedBulkAgents.length}</h3>
                </div>
                <CheckSquare size={17} />
              </div>
              <div className={styles.bulkSelectionList}>
                {selectedBulkAgents.slice(0, 8).map((agent) => (
                  <span key={`bulk-selected:${agent.agentId}`}>
                    {agentLabel(agent)}
                  </span>
                ))}
                {selectedBulkAgents.length > 8 ? <span>+{selectedBulkAgents.length - 8}</span> : null}
              </div>
              <div className={styles.editorGrid}>
                <label className={styles.field}>
                  <span className={styles.bulkFieldHeader}>
                    <input
                      type="checkbox"
                      checked={bulkConfigApply.dialogueModelId}
                      onChange={(event) => toggleBulkConfigApply("dialogueModelId", event.target.checked)}
                    />
                    {copy.bulkApplyField}
                  </span>
                  <span>{copy.bulkDialogueModel}</span>
                  <select
                    value={bulkConfigDraft.dialogueModelId}
                    disabled={!bulkConfigApply.dialogueModelId || bulkAgentPending}
                    onChange={(event) => updateBulkConfigDraft({ dialogueModelId: event.target.value })}
                  >
                    <option value="">{bulkConfigMixed.dialogueModelId ? copy.bulkEditMixed : "-"}</option>
                    {agentModelChoices.map((model) => (
                      <option key={`bulk-dialogue:${model.modelId}`} value={model.modelId}>
                        {model.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label className={styles.field}>
                  <span className={styles.bulkFieldHeader}>
                    <input
                      type="checkbox"
                      checked={bulkConfigApply.promptTemplateId}
                      onChange={(event) => toggleBulkConfigApply("promptTemplateId", event.target.checked)}
                    />
                    {copy.bulkApplyField}
                  </span>
                  <span>{copy.prompt}</span>
                  <select
                    value={bulkConfigDraft.promptTemplateId}
                    disabled={!bulkConfigApply.promptTemplateId || bulkAgentPending}
                    onChange={(event) => updateBulkConfigDraft({ promptTemplateId: event.target.value })}
                  >
                    <option value="">{bulkConfigMixed.promptTemplateId ? copy.bulkEditMixed : "-"}</option>
                    {workspace?.promptTemplates.map((template) => (
                      <option key={`bulk-prompt:${template.promptTemplateId || template.templateId}`} value={template.promptTemplateId || template.templateId || ""}>
                        {promptTemplateOptionLabel(template, lang)}
                      </option>
                    ))}
                  </select>
                </label>
                <label className={styles.field}>
                  <span className={styles.bulkFieldHeader}>
                    <input
                      type="checkbox"
                      checked={bulkConfigApply.primaryMode}
                      onChange={(event) => toggleBulkConfigApply("primaryMode", event.target.checked)}
                    />
                    {copy.bulkApplyField}
                  </span>
                  <span>{copy.bulkPrimaryMode}</span>
                  <select
                    value={bulkConfigDraft.primaryMode}
                    disabled={!bulkConfigApply.primaryMode || bulkAgentPending}
                    onChange={(event) => updateBulkConfigDraft({ primaryMode: event.target.value })}
                  >
                    <option value="">{bulkConfigMixed.primaryMode ? copy.bulkEditMixed : "-"}</option>
                    {AGENT_PRIMARY_MODE_OPTIONS.map((mode) => (
                      <option key={`bulk-mode:${mode}`} value={mode}>
                        {modeLabel(mode, lang)}
                      </option>
                    ))}
                  </select>
                </label>
                <label className={styles.field}>
                  <span className={styles.bulkFieldHeader}>
                    <input
                      type="checkbox"
                      checked={bulkConfigApply.roleKey}
                      onChange={(event) => toggleBulkConfigApply("roleKey", event.target.checked)}
                    />
                    {copy.bulkApplyField}
                  </span>
                  <span>{copy.bulkRoleKey}</span>
                  <input
                    value={bulkConfigDraft.roleKey}
                    placeholder={bulkConfigMixed.roleKey ? copy.bulkEditMixed : "-"}
                    disabled={!bulkConfigApply.roleKey || bulkAgentPending}
                    onChange={(event) => updateBulkConfigDraft({ roleKey: event.target.value })}
                  />
                </label>
              </div>
              {notice ? (
                <p className={notice.tone === "error" ? styles.errorText : styles.successText}>{notice.text}</p>
              ) : null}
              <div className={styles.editorActions}>
                <button
                  type="button"
                  className={styles.secondaryButton}
                  disabled={bulkAgentPending}
                  onClick={() => {
                    setBulkConfigDraft(bulkConfigDraftFromAgents(selectedBulkAgents));
                    setBulkConfigApply(DEFAULT_BULK_CONFIG_APPLY);
                  }}
                >
                  {copy.bulkConfigReset}
                </button>
                <button
                  type="button"
                  className={styles.primaryButton}
                  disabled={!bulkConfigCanSave}
                  onClick={bulkApplyAgentConfig}
                >
                  {bulkAgentPending ? copy.bulkWorking : copy.bulkApplyConfig}
                </button>
              </div>
            </section>
          ) : selectedAgent ? (
            <>
              <section className={styles.detailHeader} title={copy.routeHint}>
                <div className={styles.avatarEditorAnchor}>
                  <button
                    type="button"
                    className={styles.detailAvatarButton}
                    onClick={() => setAvatarEditorOpen((current) => !current)}
                    aria-expanded={avatarEditorOpen}
                    aria-label={copy.editAvatar}
                    title={copy.editAvatar}
                  >
                    {renderAgentAvatar(
                      styles.detailAvatar,
                      selectedAgent.avatarImageUrl,
                      avatarInitials(selectedAgent.agentCode, agentLabel(selectedAgent)),
                    )}
                  </button>
                  {avatarEditorOpen ? (
                    <section className={styles.avatarEditorPanel} title={copy.avatarEditorHint}>
                      <div className={styles.avatarEditorHeader}>
                        <div>
                          <p className={styles.panelEyebrow}>{copy.avatarEditorTitle}</p>
                          <strong>{copy.editAvatar}</strong>
                        </div>
                        <button type="button" className={styles.iconButton} onClick={() => setAvatarEditorOpen(false)} aria-label={lang === "zh" ? "关闭" : "Close"}>
                          ×
                        </button>
                      </div>
                      <div className={styles.avatarEditorActions}>
                        <label className={styles.secondaryButton}>
                          <input
                            type="file"
                            accept="image/png,image/jpeg,image/webp"
                            disabled={selectedAgentAvatarUploadPending}
                            onChange={(event) => {
                              uploadSelectedAgentAvatar(event.target.files?.[0]);
                              event.currentTarget.value = "";
                            }}
                          />
                          <span>{selectedAgentAvatarUploadPending ? copy.uploadingAvatar : copy.uploadAvatar}</span>
                        </label>
                        <button type="button" className={styles.secondaryButton} disabled={selectedAgentAvatarUpdatePending} onClick={resetSelectedAgentAvatar}>
                          {selectedAgentAvatarUpdatePending ? copy.resettingAvatar : copy.resetDefaultAvatar}
                        </button>
                      </div>
                      <div className={styles.avatarLibraryHeader}>
                        <span>{copy.avatarLibrary}</span>
                        <small>{avatarOptionsQuery.data?.count ?? 0}</small>
                      </div>
                      {avatarOptionsQuery.isPending ? (
                        <p className={styles.contextLine}>{copy.avatarLibraryLoading}</p>
                      ) : avatarOptionsQuery.data?.options.length ? (
                        <div className={styles.avatarOptionGrid}>
                          {avatarOptionsQuery.data.options.map((option) => {
                            const selected = option.path === selectedAgent.avatarImagePath;
                            return (
                              <button
                                key={option.path}
                                type="button"
                                className={selected ? `${styles.avatarOption} ${styles.avatarOptionSelected}` : styles.avatarOption}
                                onClick={() => selectAgentAvatar(option.path)}
                                disabled={selectedAgentAvatarUpdatePending}
                                title={option.filename}
                              >
                                <img src={option.url} alt="" />
                              </button>
                            );
                          })}
                        </div>
                      ) : (
                        <p className={styles.contextLine}>{copy.avatarLibraryEmpty}</p>
                      )}
                    </section>
                  ) : null}
                </div>
                <div>
                  <p className={styles.panelEyebrow}>{agentFunctionalLabel(selectedAgent, lang)}</p>
                  <h2>{agentLabel(selectedAgent)}</h2>
                  <span className={`${styles.agentRoleTag} ${styles[`agentRoleTag_${agentFunctionTone(selectedAgent, lang)}`]}`}>
                    {agentFunctionalLabel(selectedAgent, lang)}
                  </span>
                </div>
                <div className={styles.detailHeaderActions}>
                  <span className={styles.detailHealthStatus}>
                    <span className={`${styles.issuePill} ${styles[`issue_${issueTone(selectedAgent.health)}`]}`}>
                      {issueLabel(selectedAgent.health, lang)}
                    </span>
                    <small>{issueSummary(selectedAgent.health, lang)}</small>
                  </span>
                </div>
              </section>

              <nav className={styles.detailTabs} aria-label={copy.title}>
                {panes.map((pane) => (
                  <button
                    key={pane.id}
                    type="button"
                    className={activePane === pane.id ? styles.detailTabActive : styles.detailTab}
                    onClick={() => setActivePane(pane.id)}
                  >
                    <span>{pane.label}</span>
                    <strong>{pane.count}</strong>
                  </button>
                ))}
              </nav>

              <section className={styles.managementBriefPanel} title={copy.managementBriefHint}>
                <div className={styles.managementBriefHeader}>
                  <div>
                    <p className={styles.panelEyebrow}>{copy.managementBriefTitle}</p>
                    <h3>{managementBrief.statusLabel}</h3>
                    <span>{managementBrief.statusDetail}</span>
                  </div>
                  <strong>{managementBrief.score}</strong>
                </div>
                <div className={styles.managementChecklist}>
                  {managementBrief.items.map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      className={item.complete ? styles.managementChecklistDone : styles.managementChecklistMissing}
                      onClick={() => setActivePane(item.pane)}
                    >
                      {item.complete ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}
                      <span>{item.label}</span>
                    </button>
                  ))}
                </div>
                <div className={styles.nextActionList}>
                  <span>{copy.nextActionsTitle}</span>
                  {managementBrief.actions.length ? (
                    managementBrief.actions.map((action) => (
                      <button
                        key={action.id}
                        type="button"
                        title={action.detail}
                        onClick={() => {
                          if (action.route) {
                            void navigate(action.route);
                            return;
                          }
                          setActivePane(action.pane);
                        }}
                      >
                        <strong>{action.label}</strong>
                      </button>
                    ))
                  ) : (
                    <p>{copy.nextAllReady}</p>
                  )}
                </div>
              </section>

              {activePane === "overview" ? (
                <>
                  <div className={styles.factGrid}>
                    {(() => {
                      const selectedModelDisplay = agentDialogueModelDisplay(selectedAgent, lang);
                      return (
                    <section>
                      <Bot size={16} />
                      <span>{copy.model}</span>
                      <strong>{selectedModelDisplay.label}</strong>
                      <small>{selectedModelDisplay.detail}</small>
                    </section>
                      );
                    })()}
                    <section>
                      <Brain size={16} />
                      <span>{copy.llmSlots}</span>
                      <strong>
                        {Object.keys(normalizeAgentLlmBindings(selectedAgent.llmBindings)).length}/{llmSlots.length}
                      </strong>
                      <small>{llmSlots.map((slot) => `${slot.label}:${agentLlmSlotModelId(selectedAgent.llmBindings, slot) ? "on" : "off"}`).join(" / ")}</small>
                    </section>
                    <section>
                      <Layers3 size={16} />
                      <span>{lang === "zh" ? "系统编号" : "System IDs"}</span>
                      <strong>{selectedAgent.agentCode || "-"}</strong>
                      <small>{selectedAgent.agentId || "-"}</small>
                    </section>
                    <section>
                      <Brain size={16} />
                      <span>{copy.prompt}</span>
                      <strong>{promptTemplateDisplayName(selectedAgent.promptTemplate, selectedAgent.promptTemplateId, lang)}</strong>
                      <small>{selectedAgent.promptTemplate?.sourcePath || "-"}</small>
                    </section>
                    <section>
                      <Wrench size={16} />
                      <span>{copy.tools}</span>
                      <strong>{selectedAgent.toolPolicyId || "-"}</strong>
                      <small>allowed {selectedAgent.toolPolicy?.allowedTools?.length ?? 0} / blocked {selectedAgent.toolPolicy?.blockedTools?.length ?? 0}</small>
                    </section>
                    <section>
                      <Database size={16} />
                      <span>{copy.memory}</span>
                      <strong>{selectedAgent.memoryPolicyId || "-"}</strong>
                      <small>{selectedAgent.memoryPolicy?.privateMemoryRoot || "-"}</small>
                    </section>
                    {selectedAgentRequiresPersona ? (
                      <section>
                        <UserRound size={16} />
                        <span>{copy.personaTitle}</span>
                        <strong>{personaProfileSummary(selectedAgent, lang)}</strong>
                        <small>{(selectedAgent.personaProfile?.expertise ?? []).join(" / ") || copy.expertise}</small>
                      </section>
                    ) : null}
                    {selectedAgentRequiresTask ? (
                      <section>
                        <CheckCircle2 size={16} />
                        <span>{copy.taskTitle}</span>
                        <strong>{taskProfileSummary(selectedAgent, lang)}</strong>
                        <small>{(selectedAgent.taskProfile?.taskTypes ?? []).join(" / ") || copy.taskTypes}</small>
                      </section>
                    ) : null}
                    <section>
                      <FolderTree size={16} />
                      <span>{copy.territory}</span>
                      <strong>{selectedAgent.workspaceTerritory?.defaultWriteScope || "private"}</strong>
                      <small>{selectedAgent.workspaceTerritory?.privateRoot || selectedAgent.workspacePath || "-"}</small>
                    </section>
                  </div>

                  <section className={styles.detailSection}>
                    <div className={styles.panelHeader}>
                      <div>
                        <p className={styles.panelEyebrow}>{copy.territory}</p>
                        <h3>{selectedAgent.workspaceTerritory?.defaultWriteScope || "private"}</h3>
                      </div>
                      <FolderTree size={16} />
                    </div>
                    <div className={styles.boundarySummaryGrid}>
                      <span>
                        <strong>{copy.privateTerritory}</strong>
                        <small>{selectedAgent.workspaceTerritory?.privateRoot || selectedAgent.workspacePath || "-"}</small>
                      </span>
                      <span>
                        <strong>{copy.sharedTerritory}</strong>
                        <small>{selectedAgent.workspaceTerritory?.sharedRoot || "workspace/shared"}</small>
                      </span>
                      <span>
                        <strong>{copy.writeBoundary}</strong>
                        <small>{(selectedAgent.workspaceTerritory?.writeScopes ?? ["private"]).join(" / ")}</small>
                      </span>
                    </div>
                  </section>

                  <section className={styles.detailSection}>
                    <div className={styles.panelHeader}>
                      <div>
                        <p className={styles.panelEyebrow}>{copy.modeMembership}</p>
                        <h3>{modeLabel(selectedAgent.primaryMode, lang)} / {selectedAgent.roleKey || "-"}</h3>
                      </div>
                      <Layers3 size={16} />
                    </div>
                    <div className={styles.pillList}>
                      {uniqueModes(selectedAgent).map((mode) => (
                        <span key={`${selectedAgent.agentId}:mode:${mode}`}>{modeLabel(mode, lang)}</span>
                      ))}
                    </div>
                  </section>

                  <section className={styles.policyGrid}>
                    <div>
                      <MessageSquare size={16} />
                      <strong>{copy.context}</strong>
                      <span>{selectedAgent.groupContextEvents?.length ?? 0} group events</span>
                    </div>
                    <div>
                      <ShieldCheck size={16} />
                      <strong>{copy.runtimeStatus}</strong>
                      <span>{runtimeStatusLabel(selectedAgent, lang)}</span>
                    </div>
                    <div>
                      <Users size={16} />
                      <strong>{copy.communication}</strong>
                      <span>{selectedAgent.agentInboxPendingCount ?? 0} pending</span>
                    </div>
                    <div>
                      <Layers3 size={16} />
                      <strong>{copy.delegation}</strong>
                      <span>{metadataText(selectedAgent, "maxSubagentDepth") || copy.policyPending}</span>
                    </div>
                  </section>
                </>
              ) : null}

              {activePane === "config" ? (
                <>
              <section className={styles.configEditor} title={copy.personaHint}>
                <div className={styles.panelHeader}>
                  <div>
                    <p className={styles.panelEyebrow}>{copy.configTitle}</p>
                    <h3>{agentLabel(selectedAgent)}</h3>
                  </div>
                  <span className={configDirty ? styles.dirtyPill : styles.cleanPill}>
                    {configDirty ? (lang === "zh" ? "未保存" : "Unsaved") : (lang === "zh" ? "已同步" : "Synced")}
                  </span>
                </div>
                <section className={`${styles.healthGuidePanel} ${styles[`healthGuide_${issueTone(selectedAgent.health)}`]}`}>
                  <div>
                    <span>{issuePanelLabel(selectedAgent.health, copy)}</span>
                    <strong>{issueLabel(selectedAgent.health, lang)} · {issueSummary(selectedAgent.health, lang)}</strong>
                  </div>
                  <p><strong>{copy.healthNextStep}</strong>{issueNextStep(selectedAgent.health, lang)}</p>
                </section>
                <div className={styles.editorGrid}>
                  <label className={styles.field}>
                    <span>Agent</span>
                    <input
                      value={configDraft.displayName}
                      onChange={(event) => updateDraft({ displayName: event.target.value })}
                    />
                  </label>
                  <label className={styles.field}>
                    <span>{copy.status}</span>
                    <select value={configDraft.status} onChange={(event) => updateDraft({ status: event.target.value })}>
                      <option value="active">{lang === "zh" ? "活跃" : "Active"}</option>
                    </select>
                  </label>
                  <section className={styles.fieldWide} title={copy.llmSlotsHint}>
                    <span>{copy.llmSlots}</span>
                    <div className={styles.llmSlotGrid}>
                      {llmSlots.map((slot) => {
                        const selectedSlotModelId = agentLlmSlotModelId(configDraft.llmBindings, slot);
                        const selectedSlotModel = agentModelById(workspace?.agentModelChoices ?? [], selectedSlotModelId);
                        const supportsReasoningEffort = agentModelSupportsReasoningEffort(selectedSlotModel);
                        const slotChoices = buildAgentSlotModelChoicesWithCurrent(
                          workspace?.agentModelChoices ?? [],
                          slot,
                          selectedSlotModelId,
                          lang,
                        );
                        return (
                          <label key={slot.slot} className={styles.llmSlotField} title={slot.description}>
                            <span>
                              <strong>{slot.label}</strong>
                              <small>{slot.required ? copy.requiredSlot : copy.optionalSlot}</small>
                            </span>
                            <select
                              value={selectedSlotModelId}
                              onChange={(event) => {
                                const nextBindings = updateAgentLlmSlotBinding(configDraft.llmBindings, slot, event.target.value);
                                updateDraft({
                                  llmBindings: nextBindings,
                                  reasoningEffortBySlot: pruneAgentReasoningEffortBySlot(
                                    configDraft.reasoningEffortBySlot,
                                    nextBindings,
                                    workspace?.agentModelChoices ?? [],
                                  ),
                                });
                              }}
                            >
                              {!slot.required ? <option value="">{copy.inheritDialogueModel}</option> : null}
                              {slotChoices.map((model) => (
                                <option key={`${slot.slot}:${model.key}`} value={model.modelId} title={model.modelLabel || model.modelId}>
                                  {model.label}
                                </option>
                              ))}
                            </select>
                            {supportsReasoningEffort ? (
                              <select
                                value={normalizeAgentReasoningEffort(configDraft.reasoningEffortBySlot[slot.slot])}
                                aria-label={`${slot.label} ${copy.reasoningEffort}`}
                                onChange={(event) => updateDraft({
                                  reasoningEffortBySlot: updateAgentReasoningEffortBySlot(
                                    configDraft.reasoningEffortBySlot,
                                    slot.slot,
                                    event.target.value,
                                  ),
                                })}
                              >
                                <option value="">{copy.reasoningEffort}: {copy.reasoningEffortDefault}</option>
                                <option value="low">{copy.reasoningEffort}: {copy.reasoningEffortLow}</option>
                                <option value="medium">{copy.reasoningEffort}: {copy.reasoningEffortMedium}</option>
                                <option value="high">{copy.reasoningEffort}: {copy.reasoningEffortHigh}</option>
                              </select>
                            ) : null}
                          </label>
                        );
                      })}
                    </div>
                  </section>
                  <label className={styles.field}>
                    <span>{copy.prompt}</span>
                    <select value={configDraft.promptTemplateId} onChange={(event) => updateDraft({ promptTemplateId: event.target.value })}>
                      <option value="">-</option>
                      {workspace?.promptTemplates.map((template) => (
                        <option key={template.promptTemplateId || template.templateId} value={template.promptTemplateId || template.templateId || ""}>
                          {promptTemplateOptionLabel(template, lang)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className={styles.field} title={toolPolicySource?.description || copy.toolPolicyPickerHint}>
                    <span>{copy.tools}</span>
                    <select value={configDraft.toolPolicyId} onChange={(event) => updateDraft({ toolPolicyId: event.target.value })}>
                      {workspace?.toolPolicies.map((policy) => (
                        <option key={policy.policyId} value={policy.policyId}>
                          {policy.policyId} · {policy.allowedToolCount}/{policy.blockedToolCount}
                        </option>
                      ))}
                    </select>
                    <small>{toolPolicySourceLine}</small>
                  </label>
                  <label className={styles.field} title={copy.memoryPolicyPickerHint}>
                    <span>{copy.memory}</span>
                    <select value={configDraft.memoryPolicyId} onChange={(event) => updateDraft({ memoryPolicyId: event.target.value })}>
                      {workspace?.memoryPolicies.map((policy) => (
                        <option key={policy.policyId} value={policy.policyId}>
                          {policy.policyId} · {policy.privateMemoryRoot || "-"}
                        </option>
                      ))}
                    </select>
                  </label>
                  <section className={styles.fieldWide} title={contextCompressionPolicyLine}>
                    <span>{copy.contextCompressionPolicy}</span>
                    <div className={styles.compressionPolicyGrid}>
                      <label className={styles.field}>
                        <span>{copy.contextCompressionPolicy}</span>
                        <select
                          value={configDraft.contextCompressionPolicy.mode}
                          onChange={(event) => updateContextCompressionDraft({
                            mode: event.target.value === "custom" ? "custom" : "inherit",
                          })}
                        >
                          <option value="inherit">{copy.contextCompressionInherit}</option>
                          <option value="custom">{copy.contextCompressionCustom}</option>
                        </select>
                      </label>
                      <label className={`${styles.field} ${styles.compressionToggleField}`}>
                        <span>{copy.contextCompressionEnabled}</span>
                        <input
                          type="checkbox"
                          checked={configDraft.contextCompressionPolicy.enabled}
                          disabled={!contextCompressionCustom}
                          onChange={(event) => updateContextCompressionDraft({ enabled: event.target.checked })}
                        />
                      </label>
                      <label className={styles.field}>
                        <span>{copy.contextCompressionMaxTokenLimit}</span>
                        <input
                          type="number"
                          min={1}
                          value={configDraft.contextCompressionPolicy.maxTokenLimit}
                          disabled={!contextCompressionCustom}
                          onChange={(event) => updateContextCompressionDraft({ maxTokenLimit: event.target.value })}
                        />
                      </label>
                      <label className={styles.field}>
                        <span>{copy.contextCompressionMaxCount}</span>
                        <input
                          type="number"
                          min={0}
                          value={configDraft.contextCompressionPolicy.maxCompressionsPerSession}
                          disabled={!contextCompressionCustom}
                          onChange={(event) => updateContextCompressionDraft({ maxCompressionsPerSession: event.target.value })}
                        />
                      </label>
                    </div>
                    <div className={styles.compressionPolicySubgrid}>
                      <label className={styles.field}>
                        <span>{copy.contextCompressionThresholds} · {lang === "zh" ? "轻量" : "Light"}</span>
                        <input
                          type="number"
                          min={1}
                          max={100}
                          value={configDraft.contextCompressionPolicy.lightThreshold}
                          disabled={!contextCompressionCustom}
                          onChange={(event) => updateContextCompressionDraft({ lightThreshold: event.target.value })}
                        />
                      </label>
                      <label className={styles.field}>
                        <span>{copy.contextCompressionThresholds} · {lang === "zh" ? "标准" : "Standard"}</span>
                        <input
                          type="number"
                          min={1}
                          max={100}
                          value={configDraft.contextCompressionPolicy.standardThreshold}
                          disabled={!contextCompressionCustom}
                          onChange={(event) => updateContextCompressionDraft({ standardThreshold: event.target.value })}
                        />
                      </label>
                      <label className={styles.field}>
                        <span>{copy.contextCompressionThresholds} · {lang === "zh" ? "深度" : "Deep"}</span>
                        <input
                          type="number"
                          min={1}
                          max={100}
                          value={configDraft.contextCompressionPolicy.deepThreshold}
                          disabled={!contextCompressionCustom}
                          onChange={(event) => updateContextCompressionDraft({ deepThreshold: event.target.value })}
                        />
                      </label>
                      <label className={styles.field}>
                        <span>{copy.contextCompressionThresholds} · {lang === "zh" ? "紧急" : "Emergency"}</span>
                        <input
                          type="number"
                          min={1}
                          max={100}
                          value={configDraft.contextCompressionPolicy.emergencyThreshold}
                          disabled={!contextCompressionCustom}
                          onChange={(event) => updateContextCompressionDraft({ emergencyThreshold: event.target.value })}
                        />
                      </label>
                      <label className={styles.field}>
                        <span>{copy.contextCompressionSummaryChars} · {lang === "zh" ? "轻量" : "Light"}</span>
                        <input
                          type="number"
                          min={1}
                          value={configDraft.contextCompressionPolicy.lightSummaryChars}
                          disabled={!contextCompressionCustom}
                          onChange={(event) => updateContextCompressionDraft({ lightSummaryChars: event.target.value })}
                        />
                      </label>
                      <label className={styles.field}>
                        <span>{copy.contextCompressionSummaryChars} · {lang === "zh" ? "标准" : "Standard"}</span>
                        <input
                          type="number"
                          min={1}
                          value={configDraft.contextCompressionPolicy.standardSummaryChars}
                          disabled={!contextCompressionCustom}
                          onChange={(event) => updateContextCompressionDraft({ standardSummaryChars: event.target.value })}
                        />
                      </label>
                      <label className={styles.field}>
                        <span>{copy.contextCompressionSummaryChars} · {lang === "zh" ? "深度" : "Deep"}</span>
                        <input
                          type="number"
                          min={1}
                          value={configDraft.contextCompressionPolicy.deepSummaryChars}
                          disabled={!contextCompressionCustom}
                          onChange={(event) => updateContextCompressionDraft({ deepSummaryChars: event.target.value })}
                        />
                      </label>
                      <label className={styles.field}>
                        <span>{copy.contextCompressionSummaryChars} · {lang === "zh" ? "紧急" : "Emergency"}</span>
                        <input
                          type="number"
                          min={1}
                          value={configDraft.contextCompressionPolicy.emergencySummaryChars}
                          disabled={!contextCompressionCustom}
                          onChange={(event) => updateContextCompressionDraft({ emergencySummaryChars: event.target.value })}
                        />
                      </label>
                    </div>
                    <div className={styles.compressionPolicyFooter}>
                      <label className={styles.field}>
                        <span>{copy.contextCompressionKeepAi}</span>
                        <input
                          type="number"
                          min={0}
                          value={configDraft.contextCompressionPolicy.keepAiMessages}
                          disabled={!contextCompressionCustom}
                          onChange={(event) => updateContextCompressionDraft({ keepAiMessages: event.target.value })}
                        />
                      </label>
                      <label className={styles.compressionInlineCheck}>
                        <input
                          type="checkbox"
                          checked={configDraft.contextCompressionPolicy.preserveErrors}
                          disabled={!contextCompressionCustom}
                          onChange={(event) => updateContextCompressionDraft({ preserveErrors: event.target.checked })}
                        />
                        <span>{copy.contextCompressionPreserveErrors}</span>
                      </label>
                      <label className={styles.compressionInlineCheck}>
                        <input
                          type="checkbox"
                          checked={configDraft.contextCompressionPolicy.extractKeyDecisions}
                          disabled={!contextCompressionCustom}
                          onChange={(event) => updateContextCompressionDraft({ extractKeyDecisions: event.target.checked })}
                        />
                        <span>{copy.contextCompressionExtractDecisions}</span>
                      </label>
                    </div>
                  </section>
                </div>
                {notice ? (
                  <p className={notice.tone === "error" ? styles.errorText : styles.successText}>{notice.text}</p>
                ) : null}
                <div className={styles.editorActions}>
                  <button type="button" className={styles.secondaryButton} disabled={!configDirty || selectedAgentConfigPending} onClick={() => setConfigDraft(draftFromAgent(selectedAgent))}>
                    {copy.resetConfig}
                  </button>
                  <button type="button" className={styles.primaryButton} disabled={!canSaveConfig || selectedAgentConfigPending} onClick={saveAgentConfig}>
                    {selectedAgentConfigPending ? copy.savingConfig : copy.saveConfig}
                  </button>
                </div>
              </section>

              {selectedAgentRequiresPersona ? (
              <section className={styles.configEditor}>
                <div className={styles.panelHeader}>
                  <div>
                    <p className={styles.panelEyebrow}>{copy.personaTitle}</p>
                    <h3>{personaProfileSummary(selectedAgent, lang)}</h3>
                  </div>
                  <span className={personaDirty ? styles.dirtyPill : styles.cleanPill}>
                    {personaDirty ? (lang === "zh" ? "未保存" : "Unsaved") : (lang === "zh" ? "已同步" : "Synced")}
                  </span>
                </div>
                <div className={styles.editorGrid}>
                  <label className={styles.field}>
                    <span>{copy.gender}</span>
                    <input value={personaDraft.gender} onChange={(event) => updatePersonaDraft({ gender: event.target.value })} />
                  </label>
                  <label className={styles.field}>
                    <span>{copy.age}</span>
                    <input value={personaDraft.age} onChange={(event) => updatePersonaDraft({ age: event.target.value })} />
                  </label>
                  <label className={styles.field}>
                    <span>{copy.pronouns}</span>
                    <input value={personaDraft.pronouns} onChange={(event) => updatePersonaDraft({ pronouns: event.target.value })} />
                  </label>
                  <label className={styles.field}>
                    <span>{copy.expertise}</span>
                    <input
                      value={personaDraft.expertise}
                      placeholder={copy.expertisePlaceholder}
                      onChange={(event) => updatePersonaDraft({ expertise: event.target.value })}
                    />
                  </label>
                  <label className={styles.fieldWide}>
                    <span>{copy.personality}</span>
                    <textarea value={personaDraft.personality} onChange={(event) => updatePersonaDraft({ personality: event.target.value })} />
                  </label>
                  <label className={styles.fieldWide}>
                    <span>{copy.communicationStyle}</span>
                    <textarea
                      value={personaDraft.communicationStyle}
                      onChange={(event) => updatePersonaDraft({ communicationStyle: event.target.value })}
                    />
                  </label>
                  <label className={styles.fieldWide}>
                    <span>{copy.background}</span>
                    <textarea value={personaDraft.background} onChange={(event) => updatePersonaDraft({ background: event.target.value })} />
                  </label>
                  <label className={styles.fieldWide}>
                    <span>{copy.collaborationPreference}</span>
                    <textarea
                      value={personaDraft.collaborationPreference}
                      onChange={(event) => updatePersonaDraft({ collaborationPreference: event.target.value })}
                    />
                  </label>
                  <label className={styles.fieldWide}>
                    <span>{copy.identityNotes}</span>
                    <textarea value={personaDraft.identityNotes} onChange={(event) => updatePersonaDraft({ identityNotes: event.target.value })} />
                  </label>
                </div>
                <div className={styles.editorActions}>
                  <button
                    type="button"
                    className={styles.secondaryButton}
                    disabled={!personaDirty || selectedAgentPersonaPending}
                    onClick={() => setPersonaDraft(personaDraftFromAgent(selectedAgent))}
                  >
                    {copy.resetConfig}
                  </button>
                  <button
                    type="button"
                    className={styles.primaryButton}
                    disabled={!canSavePersona || selectedAgentPersonaPending}
                    onClick={savePersonaProfile}
                  >
                    {selectedAgentPersonaPending ? copy.savingPersona : copy.savePersona}
                  </button>
                </div>
              </section>
              ) : null}

              <section className={styles.configEditor} title={
                lang === "zh"
                  ? "工具治理变更从工具页发起；这里保留最近记录和待审批处理。"
                  : "Tool governance changes start from the Tools page. Recent records and approvals remain visible here."
              }>
                <div className={styles.panelHeader}>
                  <div>
                    <p className={styles.panelEyebrow}>{copy.toolGovernanceTitle}</p>
                    <h3>{copy.toolGovernancePending}: {(selectedAgent.toolGovernanceRequests ?? []).filter((item) => item.status === "pending_review").length}</h3>
                  </div>
                  <ShieldCheck size={16} />
                </div>
                <div className={styles.toolGovernanceList}>
                  {(selectedAgent.toolGovernanceRequests ?? []).length ? (
                    (selectedAgent.toolGovernanceRequests ?? []).map((request) => {
                      const requestPending =
                        resolveToolGovernanceMutation.isPending
                        && resolveToolGovernanceMutation.variables?.agentId === selectedAgent.agentId
                        && resolveToolGovernanceMutation.variables?.requestId === request.requestId;
                      return (
                      <article key={request.requestId} className={styles.toolGovernanceItem}>
                        <div>
                          <strong>{governanceStatusLabel(request.status, lang)} · {governanceRiskLabel(request.riskLevel, lang)}</strong>
                          <span>{governanceDeltaSummary(request, lang)}</span>
                          <small>{request.reason || request.approvalReason || request.requestId}</small>
                        </div>
                        {request.status === "pending_review" ? (
                          <div className={styles.governanceActions}>
                            <button
                              type="button"
                              className={styles.secondaryButton}
                              disabled={requestPending}
                              onClick={() => resolveToolGovernanceRequest(request, "reject")}
                            >
                              {copy.toolGovernanceReject}
                            </button>
                            <button
                              type="button"
                              className={styles.primaryButton}
                              disabled={requestPending}
                              onClick={() => resolveToolGovernanceRequest(request, "approve")}
                            >
                              {copy.toolGovernanceApprove}
                            </button>
                          </div>
                        ) : null}
                      </article>
                      );
                    })
                  ) : (
                    <p className={styles.emptyText}>{copy.toolGovernanceEmpty}</p>
                  )}
                </div>
                <div className={styles.editorActions}>
                  <button
                    type="button"
                    className={styles.primaryButton}
                    onClick={() => navigate(selectedAgentToolConfigRoute)}
                  >
                    <Wrench size={15} />
                    {lang === "zh" ? "去工具页配置" : "Configure in tools"}
                  </button>
                </div>
              </section>

              {selectedAgentRequiresTask ? (
              <section className={styles.configEditor} title={copy.taskHint}>
                <div className={styles.panelHeader}>
                  <div>
                    <p className={styles.panelEyebrow}>{copy.taskTitle}</p>
                    <h3>{taskProfileSummary(selectedAgent, lang)}</h3>
                  </div>
                  <span className={taskDirty ? styles.dirtyPill : styles.cleanPill}>
                    {taskDirty ? (lang === "zh" ? "未保存" : "Unsaved") : (lang === "zh" ? "已同步" : "Synced")}
                  </span>
                </div>
                <div className={styles.editorGrid}>
                  <label className={styles.fieldWide}>
                    <span>{copy.mission}</span>
                    <textarea value={taskDraft.mission} onChange={(event) => updateTaskDraft({ mission: event.target.value })} />
                  </label>
                  <label className={styles.fieldWide}>
                    <span>{copy.taskTypes}</span>
                    <input
                      value={taskDraft.taskTypes}
                      placeholder={copy.taskTypesPlaceholder}
                      onChange={(event) => updateTaskDraft({ taskTypes: event.target.value })}
                    />
                  </label>
                  <label className={styles.fieldWide}>
                    <span>{copy.responsibilities}</span>
                    <textarea value={taskDraft.responsibilities} onChange={(event) => updateTaskDraft({ responsibilities: event.target.value })} />
                  </label>
                  <label className={styles.fieldWide}>
                    <span>{copy.preferredTasks}</span>
                    <textarea value={taskDraft.preferredTasks} onChange={(event) => updateTaskDraft({ preferredTasks: event.target.value })} />
                  </label>
                  <label className={styles.fieldWide}>
                    <span>{copy.avoidTasks}</span>
                    <textarea value={taskDraft.avoidTasks} onChange={(event) => updateTaskDraft({ avoidTasks: event.target.value })} />
                  </label>
                  <label className={styles.fieldWide}>
                    <span>{copy.successCriteria}</span>
                    <textarea value={taskDraft.successCriteria} onChange={(event) => updateTaskDraft({ successCriteria: event.target.value })} />
                  </label>
                  <label className={styles.fieldWide}>
                    <span>{copy.deliverables}</span>
                    <textarea value={taskDraft.deliverables} onChange={(event) => updateTaskDraft({ deliverables: event.target.value })} />
                  </label>
                  <label className={styles.fieldWide}>
                    <span>{copy.constraints}</span>
                    <textarea value={taskDraft.constraints} onChange={(event) => updateTaskDraft({ constraints: event.target.value })} />
                  </label>
                  <label className={styles.fieldWide}>
                    <span>{copy.handoffNotes}</span>
                    <textarea value={taskDraft.handoffNotes} onChange={(event) => updateTaskDraft({ handoffNotes: event.target.value })} />
                  </label>
                </div>
                <div className={styles.editorActions}>
                  <button
                    type="button"
                    className={styles.secondaryButton}
                    disabled={!taskDirty || selectedAgentTaskPending}
                    onClick={() => setTaskDraft(taskDraftFromAgent(selectedAgent))}
                  >
                    {copy.resetConfig}
                  </button>
                  <button
                    type="button"
                    className={styles.primaryButton}
                    disabled={!canSaveTask || selectedAgentTaskPending}
                    onClick={saveTaskProfile}
                  >
                    {selectedAgentTaskPending ? copy.savingTask : copy.saveTask}
                  </button>
                </div>
              </section>
              ) : null}

              <section className={styles.detailSection} title={issueNextStep(selectedAgent.health, lang)}>
                <div className={styles.panelHeader}>
                  <div>
                    <p className={styles.panelEyebrow}>{issuePanelLabel(selectedAgent.health, copy)}</p>
                    <h3>{issueLabel(selectedAgent.health, lang)} · {issueSummary(selectedAgent.health, lang)}</h3>
                  </div>
                  {selectedAgent.health.length ? <AlertTriangle size={16} /> : <CheckCircle2 size={16} />}
                </div>
                {selectedAgent.health.length ? (
                  <div className={styles.issueList}>
                    {selectedAgent.health.map((issue) => (
                      <article key={`${issue.code}:${issue.detail}`} className={`${styles.issueItem} ${styles[`issueItem_${issue.severity}`]}`}>
                        <strong>{issueDisplayTitle(issue, lang)}</strong>
                        <p>{issue.detail}</p>
                        {issue.code === "pending_inbox_messages" ? (
                          <button
                            type="button"
                            className={styles.secondaryButton}
                            onClick={() => setActivePane("activity")}
                          >
                            <MessageSquare size={15} />
                            {copy.handleInboxNow}
                          </button>
                        ) : null}
                      </article>
                    ))}
                  </div>
                ) : (
                  <p className={styles.emptyText}>{copy.noIssues}</p>
                )}
              </section>

              <section className={styles.maintenanceIntro} title={copy.maintenanceHint}>
                <div>
                  <p className={styles.panelEyebrow}>{copy.maintenanceTitle}</p>
                  <h3>{copy.maintenanceTitle}</h3>
                </div>
              </section>

              <section
                className={selectedAgentProtected ? styles.protectedZone : styles.dangerZone}
                title={
                  selectedAgentProtected
                    ? copy.archiveProtectionHint
                    : selectedAgent.status === "archived"
                      ? copy.purgeAgentHint
                      : copy.archiveAgentHint
                }
              >
                <div className={styles.panelHeader}>
                  <div>
                    <p className={styles.panelEyebrow}>
                      {selectedAgentProtected
                        ? copy.archiveProtectionTitle
                        : selectedAgent.status === "archived"
                          ? copy.purgeAgentTitle
                          : copy.archiveAgentTitle}
                    </p>
                    <h3>
                      {selectedAgentProtected
                        ? copy.archiveProtection
                        : selectedAgent.status === "archived"
                          ? copy.purgeAgent
                          : copy.archiveAgent}
                    </h3>
                  </div>
                  {selectedAgentProtected ? <ShieldCheck size={16} /> : <Trash2 size={16} />}
                </div>
                {selectedAgentProtected ? (
                  <span className={styles.cleanPill}>{copy.protectedAgent}</span>
                ) : (
                  <div className={styles.editorActions}>
                    {selectedAgent.status !== "archived" ? (
                      <button
                        type="button"
                        className={styles.secondaryButton}
                        disabled={!canArchiveAgent || selectedAgentArchivePending}
                        onClick={archiveSelectedAgent}
                      >
                        <Archive size={15} />
                        {selectedAgentArchivePending ? copy.archivingAgent : copy.archiveAgent}
                      </button>
                    ) : null}
                    <button
                      type="button"
                      className={styles.dangerButton}
                      disabled={!canPurgeAgent || selectedAgentPurgePending}
                      onClick={purgeSelectedAgent}
                    >
                      <Trash2 size={15} />
                      {selectedAgentPurgePending ? copy.purgingAgent : copy.purgeAgent}
                    </button>
                  </div>
                )}
              </section>
              {selectedAgent.status !== "archived" ? (
                <section className={styles.resetZone} title={copy.resetAgentHint}>
                  <div className={styles.panelHeader}>
                    <div>
                      <p className={styles.panelEyebrow}>{copy.resetAgentTitle}</p>
                      <h3>{copy.resetAgent}</h3>
                    </div>
                    <RefreshCw size={16} />
                  </div>
                  <div className={styles.resetOptionGrid}>
                    <label className={styles.resetOptionField} title={copy.resetClearRuntimeStateHint}>
                      <input
                        type="checkbox"
                        checked={resetOptions.clearRuntimeState}
                        onChange={(event) => updateResetOption("clearRuntimeState", event.target.checked)}
                      />
                      <span>
                        <strong>{copy.resetClearRuntimeState}</strong>
                      </span>
                    </label>
                    <label className={styles.resetOptionField} title={copy.resetDirectSessionHint}>
                      <input
                        type="checkbox"
                        checked={resetOptions.resetDirectSession}
                        onChange={(event) => updateResetOption("resetDirectSession", event.target.checked)}
                      />
                      <span>
                        <strong>{copy.resetDirectSession}</strong>
                      </span>
                    </label>
                    <label className={styles.resetOptionField} title={copy.resetPersonaProfileHint}>
                      <input
                        type="checkbox"
                        checked={resetOptions.resetPersonaProfile}
                        onChange={(event) => updateResetOption("resetPersonaProfile", event.target.checked)}
                      />
                      <span>
                        <strong>{copy.resetPersonaProfile}</strong>
                      </span>
                    </label>
                    <label className={styles.resetOptionField} title={copy.resetTaskProfileHint}>
                      <input
                        type="checkbox"
                        checked={resetOptions.resetTaskProfile}
                        onChange={(event) => updateResetOption("resetTaskProfile", event.target.checked)}
                      />
                      <span>
                        <strong>{copy.resetTaskProfile}</strong>
                      </span>
                    </label>
                    <label className={styles.resetOptionField} title={copy.resetToolPolicyHint}>
                      <input
                        type="checkbox"
                        checked={resetOptions.resetToolPolicy}
                        onChange={(event) => updateResetOption("resetToolPolicy", event.target.checked)}
                      />
                      <span>
                        <strong>{copy.resetToolPolicy}</strong>
                      </span>
                    </label>
                    <label className={styles.resetOptionField} title={copy.resetMemoryPolicyHint}>
                      <input
                        type="checkbox"
                        checked={resetOptions.resetMemoryPolicy}
                        onChange={(event) => updateResetOption("resetMemoryPolicy", event.target.checked)}
                      />
                      <span>
                        <strong>{copy.resetMemoryPolicy}</strong>
                      </span>
                    </label>
                    <label className={styles.resetOptionField} title={copy.resetRuntimePolicyHint}>
                      <input
                        type="checkbox"
                        checked={resetOptions.resetRuntimePolicy}
                        onChange={(event) => updateResetOption("resetRuntimePolicy", event.target.checked)}
                      />
                      <span>
                        <strong>{copy.resetRuntimePolicy}</strong>
                      </span>
                    </label>
                  </div>
                  <div className={styles.editorActions}>
                    <button
                      type="button"
                      className={styles.secondaryButton}
                      disabled={!canResetAgent || selectedAgentResetPending}
                      onClick={resetSelectedAgent}
                    >
                      <RefreshCw size={15} />
                      {selectedAgentResetPending ? copy.resettingAgent : copy.resetAgent}
                    </button>
                  </div>
                </section>
              ) : null}
                </>
              ) : null}

              {activePane === "config" ? (
                <>
              <section
                className={styles.configEditor}
                title={
                  lang === "zh"
                    ? "工具能力已迁移到 Agent 管理的工具页集中配置；这里保留当前 Agent 的工具摘要和入口。"
                    : "Tool permissions are configured in the Agent Tools page. This panel keeps only the current Agent summary and entry point."
                }
              >
                <div className={styles.panelHeader}>
                  <div>
                    <p className={styles.panelEyebrow}>{copy.toolPolicyTitle}</p>
                    <h3>{selectedAgent.toolPolicyId || "-"}</h3>
                  </div>
                  <Wrench size={16} />
                </div>
                <div className={styles.policySummaryGrid}>
                  <span>{copy.allowedTools}: <strong>{selectedAgent.toolPolicy?.allowedTools?.length ?? 0}</strong></span>
                  <span>{copy.preferredTools}: <strong>{selectedAgent.toolPolicy?.preferredTools?.length ?? 0}</strong></span>
                  <span>{copy.blockedTools}: <strong>{selectedAgent.toolPolicy?.blockedTools?.length ?? 0}</strong></span>
                  <span>{copy.toolCategoryCount}: <strong>{toolBundles.length}</strong></span>
                </div>
                <div className={styles.editorActions}>
                  <button
                    type="button"
                    className={styles.primaryButton}
                    onClick={() => navigate(selectedAgentToolConfigRoute)}
                  >
                    <Wrench size={15} />
                    {lang === "zh" ? "配置工具能力" : "Configure tools"}
                  </button>
                </div>
              </section>

              <section className={styles.configEditor}>
                <div className={styles.panelHeader}>
                  <div>
                    <p className={styles.panelEyebrow}>{copy.memoryPolicyTitle}</p>
                    <h3>{selectedAgent.memoryPolicyId || "-"}</h3>
                  </div>
                  <span className={memoryPolicyDirty ? styles.dirtyPill : styles.cleanPill}>
                    {memoryPolicyDirty ? (lang === "zh" ? "未保存" : "Unsaved") : (lang === "zh" ? "已同步" : "Synced")}
                  </span>
                </div>
                <div className={styles.pathList}>
                  <code>{selectedAgent.memoryPolicy?.privateMemoryRoot || selectedAgent.workspacePath || "-"}</code>
                </div>
                <div className={styles.memoryPolicyGrid}>
                  <section>
                    <span>{copy.readSharedGroups}</span>
                    <div className={styles.tagList}>
                      {memoryPolicyDraft.readSharedGroups.length ? memoryPolicyDraft.readSharedGroups.map((group) => (
                        <button key={`read:${group}`} type="button" onClick={() => removeMemoryGroup("readSharedGroups", group)}>
                          {group} x
                        </button>
                      )) : <small>{copy.noSharedGroups}</small>}
                    </div>
                    <div className={styles.inlineAdd}>
                      <input
                        list="agent-memory-groups"
                        value={memoryPolicyDraft.newReadGroup}
                        placeholder={copy.sharedGroupPlaceholder}
                        onChange={(event) => updateMemoryDraftField({ newReadGroup: event.target.value })}
                      />
                      <button type="button" onClick={() => addMemoryGroup("readSharedGroups", memoryPolicyDraft.newReadGroup)}>
                        {copy.addSharedGroup}
                      </button>
                    </div>
                  </section>
                  <section>
                    <span>{copy.writeSharedGroups}</span>
                    <div className={styles.tagList}>
                      {memoryPolicyDraft.writeSharedGroups.length ? memoryPolicyDraft.writeSharedGroups.map((group) => (
                        <button key={`write:${group}`} type="button" onClick={() => removeMemoryGroup("writeSharedGroups", group)}>
                          {group} x
                        </button>
                      )) : <small>{copy.noSharedGroups}</small>}
                    </div>
                    <div className={styles.inlineAdd}>
                      <input
                        list="agent-memory-groups"
                        value={memoryPolicyDraft.newWriteGroup}
                        placeholder={copy.sharedGroupPlaceholder}
                        onChange={(event) => updateMemoryDraftField({ newWriteGroup: event.target.value })}
                      />
                      <button type="button" onClick={() => addMemoryGroup("writeSharedGroups", memoryPolicyDraft.newWriteGroup)}>
                        {copy.addSharedGroup}
                      </button>
                    </div>
                  </section>
                  <section>
                    <span>{copy.readKnowledgeBaseIds}</span>
                    <div className={styles.tagList}>
                      {memoryPolicyDraft.readKnowledgeBaseIds.length ? memoryPolicyDraft.readKnowledgeBaseIds.map((knowledgeBaseId) => (
                        <button key={`kb-read:${knowledgeBaseId}`} type="button" onClick={() => removeKnowledgeBaseId("readKnowledgeBaseIds", knowledgeBaseId)}>
                          {knowledgeBaseId} x
                        </button>
                      )) : <small>{copy.noKnowledgeBaseIds}</small>}
                    </div>
                    <div className={styles.inlineAdd}>
                      <input
                        value={memoryPolicyDraft.newReadKnowledgeBaseId}
                        placeholder={copy.knowledgeBasePlaceholder}
                        onChange={(event) => updateMemoryDraftField({ newReadKnowledgeBaseId: event.target.value })}
                      />
                      <button type="button" onClick={() => addKnowledgeBaseId("readKnowledgeBaseIds", memoryPolicyDraft.newReadKnowledgeBaseId)}>
                        {copy.addSharedGroup}
                      </button>
                    </div>
                  </section>
                  <section>
                    <span>{copy.proposeKnowledgeBaseIds}</span>
                    <div className={styles.tagList}>
                      {memoryPolicyDraft.proposeKnowledgeBaseIds.length ? memoryPolicyDraft.proposeKnowledgeBaseIds.map((knowledgeBaseId) => (
                        <button key={`kb-propose:${knowledgeBaseId}`} type="button" onClick={() => removeKnowledgeBaseId("proposeKnowledgeBaseIds", knowledgeBaseId)}>
                          {knowledgeBaseId} x
                        </button>
                      )) : <small>{copy.noKnowledgeBaseIds}</small>}
                    </div>
                    <div className={styles.inlineAdd}>
                      <input
                        value={memoryPolicyDraft.newProposeKnowledgeBaseId}
                        placeholder={copy.knowledgeBasePlaceholder}
                        onChange={(event) => updateMemoryDraftField({ newProposeKnowledgeBaseId: event.target.value })}
                      />
                      <button type="button" onClick={() => addKnowledgeBaseId("proposeKnowledgeBaseIds", memoryPolicyDraft.newProposeKnowledgeBaseId)}>
                        {copy.addSharedGroup}
                      </button>
                    </div>
                  </section>
                  <section>
                    <span>{copy.reviewKnowledgeBaseIds}</span>
                    <div className={styles.tagList}>
                      {memoryPolicyDraft.reviewKnowledgeBaseIds.length ? memoryPolicyDraft.reviewKnowledgeBaseIds.map((knowledgeBaseId) => (
                        <button key={`kb-review:${knowledgeBaseId}`} type="button" onClick={() => removeKnowledgeBaseId("reviewKnowledgeBaseIds", knowledgeBaseId)}>
                          {knowledgeBaseId} x
                        </button>
                      )) : <small>{copy.noKnowledgeBaseIds}</small>}
                    </div>
                    <div className={styles.inlineAdd}>
                      <input
                        value={memoryPolicyDraft.newReviewKnowledgeBaseId}
                        placeholder={copy.knowledgeBasePlaceholder}
                        onChange={(event) => updateMemoryDraftField({ newReviewKnowledgeBaseId: event.target.value })}
                      />
                      <button type="button" onClick={() => addKnowledgeBaseId("reviewKnowledgeBaseIds", memoryPolicyDraft.newReviewKnowledgeBaseId)}>
                        {copy.addSharedGroup}
                      </button>
                    </div>
                  </section>
                  <section>
                    <span>{copy.rateKnowledgeBaseIds}</span>
                    <div className={styles.tagList}>
                      {memoryPolicyDraft.rateKnowledgeBaseIds.length ? memoryPolicyDraft.rateKnowledgeBaseIds.map((knowledgeBaseId) => (
                        <button key={`kb-rate:${knowledgeBaseId}`} type="button" onClick={() => removeKnowledgeBaseId("rateKnowledgeBaseIds", knowledgeBaseId)}>
                          {knowledgeBaseId} x
                        </button>
                      )) : <small>{copy.noKnowledgeBaseIds}</small>}
                    </div>
                    <div className={styles.inlineAdd}>
                      <input
                        value={memoryPolicyDraft.newRateKnowledgeBaseId}
                        placeholder={copy.knowledgeBasePlaceholder}
                        onChange={(event) => updateMemoryDraftField({ newRateKnowledgeBaseId: event.target.value })}
                      />
                      <button type="button" onClick={() => addKnowledgeBaseId("rateKnowledgeBaseIds", memoryPolicyDraft.newRateKnowledgeBaseId)}>
                        {copy.addSharedGroup}
                      </button>
                    </div>
                  </section>
                </div>
                <datalist id="agent-memory-groups">
                  {memoryGroupOptions.map((group) => <option key={group} value={group} />)}
                </datalist>
                <div className={styles.editorActions}>
                  <button
                    type="button"
                    className={styles.secondaryButton}
                    disabled={!memoryPolicyDirty || selectedAgentMemoryPolicyPending}
                    onClick={() => setMemoryPolicyDraft(memoryPolicyDraftFromAgent(selectedAgent))}
                  >
                    {copy.resetConfig}
                  </button>
                  <button
                    type="button"
                    className={styles.primaryButton}
                    disabled={!canSaveMemoryPolicy || selectedAgentMemoryPolicyPending}
                    onClick={saveMemoryPolicy}
                  >
                    {selectedAgentMemoryPolicyPending ? copy.savingMemoryPolicy : copy.saveMemoryPolicy}
                  </button>
                </div>
              </section>
                </>
              ) : null}

              {activePane === "config" ? (
                <>
              {selectedAgentRequiresTeamMembership ? (
              <section className={styles.configEditor}>
                <div className={styles.panelHeader}>
                  <div>
                    <p className={styles.panelEyebrow}>{copy.membershipTitle}</p>
                    <h3>{uniqueModes(selectedAgent).map((mode) => modeLabel(mode, lang)).join(" / ") || "-"}</h3>
                  </div>
                  <span className={membershipDirty ? styles.dirtyPill : styles.cleanPill}>
                    {membershipDirty ? (lang === "zh" ? "未保存" : "Unsaved") : (lang === "zh" ? "已同步" : "Synced")}
                  </span>
                </div>
                <div className={styles.toggleGrid}>
                  <label className={styles.checkField}>
                    <input
                      type="checkbox"
                      checked={membershipDraft.chatDefault}
                      onChange={(event) => updateMembershipDraft({ chatDefault: event.target.checked, chatAvailable: event.target.checked ? true : membershipDraft.chatAvailable })}
                    />
                    <span>{copy.chatDefault}</span>
                  </label>
                  <label className={styles.checkField}>
                    <input
                      type="checkbox"
                      checked={membershipDraft.chatAvailable}
                      onChange={(event) => updateMembershipDraft({ chatAvailable: event.target.checked, chatDefault: event.target.checked ? membershipDraft.chatDefault : false })}
                    />
                    <span>{copy.chatAvailable}</span>
                  </label>
                  <label className={styles.checkField}>
                    <input
                      type="checkbox"
                      checked={membershipDraft.researchPool}
                      onChange={(event) => updateMembershipDraft({ researchPool: event.target.checked })}
                    />
                    <span>{copy.researchPool}</span>
                  </label>
                </div>
                <div className={styles.editorGrid}>
                  <label className={styles.field}>
                    <span>{copy.supervisedSlot}</span>
                    <select value={membershipDraft.supervisedSlot} onChange={(event) => updateMembershipDraft({ supervisedSlot: event.target.value })}>
                      <option value="">{copy.noSlot}</option>
                      {Object.keys(workspace?.modeBindings.supervised_evolution?.slots ?? {}).map((slot) => (
                        <option key={slot} value={slot}>{slot}</option>
                      ))}
                    </select>
                  </label>
                  <label className={styles.field}>
                    <span>{copy.selfEvolutionSlot}</span>
                    <select value={membershipDraft.selfEvolutionSlot} onChange={(event) => updateMembershipDraft({ selfEvolutionSlot: event.target.value })}>
                      <option value="">{copy.noSlot}</option>
                      {Object.keys(workspace?.modeBindings.self_evolution?.slots ?? {}).map((slot) => (
                        <option key={slot} value={slot}>{slot}</option>
                      ))}
                    </select>
                  </label>
                </div>
                <div className={styles.editorActions}>
                  <button
                    type="button"
                    className={styles.secondaryButton}
                    disabled={!membershipDirty || selectedAgentMembershipPending}
                    onClick={() => setMembershipDraft(membershipDraftFromWorkspace(workspace, selectedAgent))}
                  >
                    {copy.resetConfig}
                  </button>
                  <button
                    type="button"
                    className={styles.primaryButton}
                    disabled={!canSaveMembership || selectedAgentMembershipPending}
                    onClick={saveModeMembership}
                  >
                    {selectedAgentMembershipPending ? copy.savingMembership : copy.saveMembership}
                  </button>
                </div>
              </section>
              ) : null}

              {selectedAgentRequiresTeamMembership ? (
              <section className={styles.configEditor}>
                <div className={styles.panelHeader}>
                  <div>
                    <p className={styles.panelEyebrow}>{copy.chatRoomMembership}</p>
                    <h3>{selectedAgent.references.filter((reference) => reference.kind === "chat_room").length} / {workspace?.chatRooms.length ?? 0}</h3>
                  </div>
                  <span className={styles.cleanPill}>{lang === "zh" ? "只读引用" : "Read-only"}</span>
                </div>
                {(workspace?.chatRooms.length ?? 0) > 0 ? (
                  <div className={styles.roomMembershipList}>
                    {workspace?.chatRooms.map((room) => {
                      const selected = room.agentIds.includes(selectedAgent.agentId);
                      return (
                        <div key={room.roomId} className={styles.roomCheckField}>
                          <span className={selected ? styles.referenceStatusActive : styles.referenceStatusStale}>
                            {selected ? (lang === "zh" ? "已加入" : "Joined") : (lang === "zh" ? "未加入" : "Not joined")}
                          </span>
                          <span>
                            <strong>{room.title || room.roomId}</strong>
                            <small>{room.mode || "-"} · {room.participantCount} members · {formatTimestamp(room.updatedAt, lang)}</small>
                          </span>
                          <button
                            type="button"
                            className={styles.referenceRouteButton}
                            onClick={() => navigate(`/chat?room=${encodeURIComponent(room.roomId)}`)}
                          >
                            <ExternalLink size={12} />
                            {lang === "zh" ? "打开群聊" : "Open room"}
                          </button>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <p className={styles.emptyText}>{copy.noChatRooms}</p>
                )}
                <p className={styles.emptyText}>
                  {lang === "zh"
                    ? "群聊成员关系在对话页的群设置中维护；团队关联群聊由团队页同步。这里仅展示引用，避免多处写同一份成员状态。"
                    : "Group membership is edited from Chat group settings, while Team-owned rooms sync from Teams. This Agent view is read-only to avoid duplicate writers."}
                </p>
              </section>
              ) : null}

              <section className={styles.detailSection}>
                <div className={styles.panelHeader}>
                  <div>
                    <p className={styles.panelEyebrow}>{copy.references}</p>
                    <h3>{selectedAgent.references.length}</h3>
                  </div>
                  <Users size={16} />
                </div>
                {selectedAgent.references.length ? (
                  <div className={styles.referenceList}>
                    {selectedAgent.references.map((reference) => (
                      <div key={`${reference.kind}:${reference.sourceId}:${reference.mode}:${reference.field}`} className={styles.referenceItem}>
                        <div className={styles.referenceHeader}>
                          <strong>{referenceLabel(reference, lang)}</strong>
                          <span className={reference.status === "stale" ? styles.referenceStatusStale : styles.referenceStatusActive}>
                            {reference.status || "active"}
                          </span>
                        </div>
                        <span>{reference.sourceLabel}</span>
                        <div className={styles.referenceMetaRow}>
                          <small>{[reference.mode, reference.field].filter(Boolean).join(" / ") || reference.sourceId}</small>
                          {referenceRoute(reference) ? (
                            <button
                              type="button"
                              className={styles.referenceRouteButton}
                              onClick={() => navigate(referenceRoute(reference))}
                            >
                              <ExternalLink size={12} />
                              {lang === "zh" ? "打开" : "Open"}
                            </button>
                          ) : null}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className={styles.emptyText}>{copy.selectAgent}</p>
                )}
              </section>
                </>
              ) : null}

              {activePane === "activity" ? (
                <>
              <section className={styles.runtimeFocusPanel}>
                <div className={styles.runtimeFocusHeader}>
                  <div>
                    <p className={styles.panelEyebrow}>{copy.runtimeFocus}</p>
                    <h3>{runtimeStatusLabel(selectedAgent, lang)}</h3>
                  </div>
                  <span className={`${styles.runtimePill} ${styles[`runtime_${runtimeStatusTone(selectedAgent)}`]}`}>
                    {selectedAgent.runtimeStatus?.reason || selectedAgent.status || "-"}
                  </span>
                </div>
                <p>{selectedAgent.runtimeStatus?.summary || selectedAgent.directSessionId || selectedAgent.workspacePath || "-"}</p>
                <div className={styles.runtimeFocusMeta}>
                  <span>
                    <strong>{copy.runtimeLatestRun}</strong>
                    <code>{selectedAgent.runtimeStatus?.runId || "-"}</code>
                  </span>
                  <span>
                    <strong>{copy.runtimeReason}</strong>
                    <code>{selectedAgent.runtimeStatus?.runKind || selectedAgent.runtimeStatus?.state || "-"}</code>
                  </span>
                  <span>
                    <strong>{copy.runtimeUpdated}</strong>
                    <code>{formatTimestamp(selectedAgent.runtimeStatus?.updatedAt || selectedAgent.updatedAt, lang)}</code>
                  </span>
                </div>
                <div className={styles.runtimeNextStep}>
                  <strong>{copy.runtimeNextStep}</strong>
                  <span>{runtimeNextStep(selectedAgent, lang)}</span>
                </div>
                <div className={styles.runtimeEvidenceHint}>
                  <strong>{copy.runtimeEvidence}</strong>
                  <span>{runtimeEvidenceReasonLabel(runtimeFocusEvidence.reason, lang)}</span>
                  <code>{runtimeFocusEvidence.match?.runtimeSceneId || "-"}</code>
                </div>
                <div className={styles.timelineActions}>
                  {selectedAgent.runtimeStatus?.sessionId || selectedAgent.directSessionId ? (
                    <button
                      type="button"
                      onClick={() => openAgentSession(selectedAgent.runtimeStatus?.sessionId || selectedAgent.directSessionId)}
                    >
                      <ExternalLink size={13} />
                      {copy.openSession}
                    </button>
                  ) : null}
                  <button type="button" onClick={() => openAgentLogs(runtimeFocusEvidence.match)}>
                    <Search size={13} />
                    {runtimeFocusEvidence.match ? `${copy.openLogs} · ${runtimeFocusEvidence.match.runtimeSceneId}` : copy.openLogs}
                  </button>
                </div>
              </section>

              <section className={styles.detailSection}>
                <div className={styles.panelHeader}>
                  <div>
                    <p className={styles.panelEyebrow}>{copy.sessions}</p>
                    <h3>{selectedAgent.directSessionId || "-"}</h3>
                  </div>
                  <MessageSquare size={16} />
                </div>
                <div className={styles.pathList}>
                  <code>{selectedAgent.workspacePath || "-"}</code>
                  <code>{selectedAgent.directSessionId || "-"}</code>
                  <span>{copy.logs}: {formatTimestamp(selectedAgent.updatedAt, lang)}</span>
                </div>
              </section>

              <section className={styles.detailSection}>
                <div className={styles.panelHeader}>
                  <div>
                    <p className={styles.panelEyebrow}>{copy.activityPane}</p>
                    <h3>{copy.activityTimeline}</h3>
                  </div>
                  <Layers3 size={16} />
                </div>
                {agentRunsQuery.isPending || agentMessagesQuery.isPending ? (
                  <p className={styles.emptyText}>{copy.loading}</p>
                ) : activityTimeline.length ? (
                  <div className={styles.activityTimelineList}>
                    {activityTimeline.map((item) => (
                      <article key={item.id} className={`${styles.activityTimelineItem} ${styles[`activityTimelineItem_${item.kind}`]}`}>
                        <strong>{item.title}</strong>
                        <p>{item.body}</p>
                        <small>{item.meta}</small>
                        <div className={styles.timelineActions}>
                          {item.sessionId ? (
                            <button type="button" onClick={() => openAgentSession(item.sessionId)}>
                              <ExternalLink size={13} />
                              {copy.openSession}
                            </button>
                          ) : null}
                          {item.canOpenLogs ? (
                            <button type="button" onClick={() => openAgentLogs(item.evidence)}>
                              <Search size={13} />
                              {item.evidence ? `${copy.openLogs} · ${item.evidence.runtimeSceneId}` : copy.openLogs}
                            </button>
                          ) : null}
                          {item.messageId ? (
                            <button type="button" onClick={() => focusInboxMessage(item.messageId)}>
                              <MessageSquare size={13} />
                              {copy.focusMessage}
                            </button>
                          ) : null}
                        </div>
                      </article>
                    ))}
                  </div>
                ) : (
                  <p className={styles.emptyText}>{copy.activityTimelineEmpty}</p>
                )}
              </section>

              <section className={styles.detailSection}>
                <div className={styles.panelHeader}>
                  <div>
                    <p className={styles.panelEyebrow}>{copy.runHistoryTitle}</p>
                    <h3>{copy.parentRuns}: {agentRunsQuery.data?.runs.length ?? 0} / {copy.subAgentRuns}: {agentRunsQuery.data?.subAgentRuns.length ?? 0}</h3>
                  </div>
                  <ShieldCheck size={16} />
                </div>
                {agentRunsQuery.isPending ? (
                  <p className={styles.emptyText}>{copy.runHistoryLoading}</p>
                ) : (agentRunsQuery.data?.runs.length ?? 0) + (agentRunsQuery.data?.subAgentRuns.length ?? 0) > 0 ? (
                  <div className={styles.runHistoryList}>
                    {agentRunsQuery.data?.runs.map((run) => (
                      <article key={run.runId} className={styles.runHistoryItem}>
                        <strong>{run.status || run.currentPhase || run.runKind}</strong>
                        <span>{run.summary || run.runId}</span>
                        <small>{run.currentPhase || run.sessionId || "-"} · {formatTimestamp(run.updatedAt || run.startedAt, lang)}</small>
                      </article>
                    ))}
                    {agentRunsQuery.data?.subAgentRuns.map((run) => (
                      <article key={run.runId} className={styles.runHistoryItem}>
                        <strong>{copy.subAgentRuns} · {run.status || run.currentPhase || run.runKind}</strong>
                        <span>{run.summary || run.subRunId || run.runId}</span>
                        <small>{run.contextMode || "-"} · {copy.maxDepth} {run.depth}/{run.maxDepth} · {formatTimestamp(run.updatedAt || run.createdAt, lang)}</small>
                      </article>
                    ))}
                  </div>
                ) : (
                  <p className={styles.emptyText}>{copy.noRunHistory}</p>
                )}
              </section>

              <section className={styles.detailSection}>
                <div className={styles.panelHeader}>
                  <div>
                    <p className={styles.panelEyebrow}>{copy.communication}</p>
                    <h3>{copy.inboxTitle}: {selectedAgentInboxPendingCount}</h3>
                  </div>
                  <div className={styles.panelHeaderActions}>
                    <button
                      type="button"
                      className={styles.secondaryButton}
                      disabled={selectedAgentInboxPendingCount <= 0 || selectedAgentConsumeAllPending}
                      onClick={consumeAllInboxMessages}
                    >
                      {selectedAgentConsumeAllPending ? copy.consumingMessage : copy.consumeAllMessages}
                    </button>
                    <MessageSquare size={16} />
                  </div>
                </div>
                {agentMessagesQuery.isPending ? (
                  <p className={styles.emptyText}>{copy.inboxLoading}</p>
                ) : (agentMessagesQuery.data?.length ?? 0) > 0 ? (
                  <div className={styles.inboxMessageList}>
                    {agentMessagesQuery.data?.map((message) => {
                      const messageId = message.messageId || message.eventId;
                      const messagePending =
                        consumeMessageMutation.isPending
                        && consumeMessageMutation.variables?.agentId === selectedAgent.agentId
                        && consumeMessageMutation.variables?.messageId === messageId;
                      return (
                        <article
                          key={messageId}
                          className={focusedMessageId === messageId ? `${styles.inboxMessageItem} ${styles.inboxMessageItemFocused}` : styles.inboxMessageItem}
                        >
                          <div className={styles.inboxMessageTop}>
                            <span>
                              <strong>{message.sourceAgentName || message.sourceAgentCode || message.sourceAgentId || "-"}</strong>
                              <small>{formatTimestamp(message.createdAt, lang)} · {message.kind || "agent_message"}</small>
                            </span>
                            <button
                              type="button"
                              className={styles.secondaryButton}
                              disabled={messagePending}
                              onClick={() => consumeInboxMessage(message)}
                            >
                              {messagePending ? copy.consumingMessage : copy.consumeMessage}
                            </button>
                          </div>
                          <p>{message.summary || message.content || message.threadId || messageId}</p>
                          <small>
                            {copy.wakeStatus}: {message.delivery?.wakeStatus || "pending"} · thread {message.threadId || "-"}
                          </small>
                        </article>
                      );
                    })}
                  </div>
                ) : (
                  <p className={styles.emptyText}>{copy.inboxEmpty}</p>
                )}
              </section>

              <section className={styles.configEditor}>
                <div className={styles.panelHeader}>
                  <div>
                    <p className={styles.panelEyebrow}>{copy.delegation}</p>
                    <h3>{copy.supervisedRole}: {metadataText(selectedAgent, "supervisedRole") || metadataText(selectedAgent, "selfEvolutionRole") || "-"}</h3>
                  </div>
                  <span className={runtimePolicyDirty ? styles.dirtyPill : styles.cleanPill}>
                    {runtimePolicyDirty ? (lang === "zh" ? "未保存" : "Unsaved") : (lang === "zh" ? "已同步" : "Synced")}
                  </span>
                </div>
                <div className={styles.runtimePolicyGrid}>
                  <section>
                    <span>{copy.delegationPolicyTitle}</span>
                    <div className={styles.toggleGrid}>
                      <label className={styles.checkField}>
                        <input
                          type="checkbox"
                          checked={delegationPolicyDraft.allowSubagents}
                          onChange={(event) => updateDelegationPolicyDraft({ allowSubagents: event.target.checked })}
                        />
                        <span>{copy.allowSubagents}</span>
                      </label>
                      <label className={styles.checkField}>
                        <input
                          type="checkbox"
                          checked={delegationPolicyDraft.allowWakeMessages}
                          onChange={(event) => updateDelegationPolicyDraft({ allowWakeMessages: event.target.checked })}
                        />
                        <span>{copy.allowWakeMessages}</span>
                      </label>
                    </div>
                    <div className={styles.editorGrid}>
                      <label className={styles.field}>
                        <span>{copy.maxConcurrent}</span>
                        <input
                          type="number"
                          min={0}
                          max={8}
                          value={delegationPolicyDraft.maxConcurrent}
                          onChange={(event) => updateDelegationPolicyDraft({ maxConcurrent: clampNumber(event.target.value, 0, 8, 0) })}
                        />
                      </label>
                      <label className={styles.field}>
                        <span>{copy.maxDepth}</span>
                        <input
                          type="number"
                          min={0}
                          max={4}
                          value={delegationPolicyDraft.maxDepth}
                          onChange={(event) => updateDelegationPolicyDraft({ maxDepth: clampNumber(event.target.value, 0, 4, 0) })}
                        />
                      </label>
                    </div>
                    <div className={styles.contextModeGrid}>
                      <label className={styles.checkField}>
                        <input
                          type="checkbox"
                          checked={delegationPolicyDraft.allowedContextModes.includes("isolated")}
                          onChange={(event) => toggleDelegationContextMode("isolated", event.target.checked)}
                        />
                        <span>{copy.allowedContextModes}: isolated</span>
                      </label>
                      <label className={styles.checkField}>
                        <input
                          type="checkbox"
                          checked={delegationPolicyDraft.allowedContextModes.includes("fork")}
                          onChange={(event) => toggleDelegationContextMode("fork", event.target.checked)}
                        />
                        <span>{copy.allowedContextModes}: fork</span>
                      </label>
                    </div>
                  </section>
                  <section>
                    <span>{copy.supervisionPolicyTitle}</span>
                    <div className={styles.toggleGrid}>
                      <label className={styles.checkField}>
                        <input
                          type="checkbox"
                          checked={supervisionPolicyDraft.supervisionEnabled}
                          onChange={(event) => updateSupervisionPolicyDraft({ supervisionEnabled: event.target.checked })}
                        />
                        <span>{copy.supervisionEnabled}</span>
                      </label>
                      <label className={styles.checkField}>
                        <input
                          type="checkbox"
                          checked={supervisionPolicyDraft.requiresReview}
                          disabled={supervisionPolicyDraft.reviewMode === "required" || supervisionPolicyDraft.reviewMode === "disabled"}
                          onChange={(event) => updateSupervisionPolicyDraft({ requiresReview: event.target.checked })}
                        />
                        <span>{copy.requiresReview}</span>
                      </label>
                    </div>
                    <div className={styles.editorGrid}>
                      <label className={styles.field}>
                        <span>{copy.reviewMode}</span>
                        <select value={supervisionPolicyDraft.reviewMode} onChange={(event) => updateSupervisionPolicyDraft({ reviewMode: event.target.value })}>
                          <option value="advisory">{lang === "zh" ? "建议" : "Advisory"}</option>
                          <option value="required">{lang === "zh" ? "强制" : "Required"}</option>
                          <option value="disabled">{lang === "zh" ? "关闭" : "Disabled"}</option>
                        </select>
                      </label>
                      <label className={styles.field}>
                        <span>{copy.evidenceLevel}</span>
                        <select value={supervisionPolicyDraft.evidenceLevel} onChange={(event) => updateSupervisionPolicyDraft({ evidenceLevel: event.target.value })}>
                          <option value="light">{lang === "zh" ? "轻量" : "Light"}</option>
                          <option value="standard">{lang === "zh" ? "标准" : "Standard"}</option>
                          <option value="strict">{lang === "zh" ? "严格" : "Strict"}</option>
                        </select>
                      </label>
                    </div>
                    <div className={styles.pathList}>
                      <span>{copy.communication}: {selectedAgent.agentInboxPendingCount ?? 0} pending</span>
                      <span>{copy.context}: {selectedAgent.groupContextEvents?.length ?? 0} group events</span>
                    </div>
                  </section>
                </div>
                {notice ? (
                  <p className={notice.tone === "error" ? styles.errorText : styles.successText}>{notice.text}</p>
                ) : null}
                <div className={styles.editorActions}>
                  <button
                    type="button"
                    className={styles.secondaryButton}
                    disabled={!runtimePolicyDirty || selectedAgentRuntimePolicyPending}
                    onClick={() => {
                      setDelegationPolicyDraft(delegationPolicyDraftFromAgent(selectedAgent));
                      setSupervisionPolicyDraft(supervisionPolicyDraftFromAgent(selectedAgent));
                    }}
                  >
                    {copy.resetConfig}
                  </button>
                  <button
                    type="button"
                    className={styles.primaryButton}
                    disabled={!canSaveRuntimePolicy || selectedAgentRuntimePolicyPending}
                    onClick={saveRuntimePolicy}
                  >
                    {selectedAgentRuntimePolicyPending ? copy.savingRuntimePolicy : copy.saveRuntimePolicy}
                  </button>
                </div>
              </section>
                </>
              ) : null}
            </>
          ) : (
            <section className={styles.emptyState}>
              <Bot size={24} />
              <strong>{copy.selectAgent}</strong>
            </section>
          )}
        </aside>
      </div>
    </section>
  );
}
