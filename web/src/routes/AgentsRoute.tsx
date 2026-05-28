import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Bot,
  Brain,
  CheckCircle2,
  Database,
  Layers3,
  MessageSquare,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  Trash2,
  Users,
  Wrench,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import {
  AgentDelegationPolicy,
  AgentRunHistory,
  AgentConfigHealthIssue,
  AgentConfigReference,
  AgentSupervisionPolicy,
  AgentConfigWorkspace,
  AgentConfigWorkspaceAgent,
  MemoryPolicy,
  ToolPolicy,
  ToolRegistryPayload,
} from "../api/types";
import { resolvePollingInterval, usePageVisibility } from "../app/pollingPolicy";
import { useAppI18n } from "../i18n/useAppI18n";
import styles from "./AgentsRoute.module.css";

type FilterId = string;

type AgentConfigDraft = {
  displayName: string;
  profileId: string;
  promptTemplateId: string;
  toolPolicyId: string;
  memoryPolicyId: string;
  status: string;
};

type AgentCreateDraft = {
  displayName: string;
  profileId: string;
  primaryMode: string;
  roleKey: string;
  promptTemplateId: string;
};

type AgentModeMembershipDraft = {
  chatDefault: boolean;
  chatAvailable: boolean;
  researchPool: boolean;
  supervisedSlot: string;
  selfEvolutionSlot: string;
};

type AgentChatRoomMembershipDraft = {
  roomIds: string[];
};

type AgentToolPolicyDraft = {
  allowedTools: string[];
  blockedTools: string[];
};

type AgentMemoryPolicyDraft = {
  readSharedGroups: string[];
  writeSharedGroups: string[];
  newReadGroup: string;
  newWriteGroup: string;
};

type AgentDelegationPolicyDraft = AgentDelegationPolicy;
type AgentSupervisionPolicyDraft = AgentSupervisionPolicy;

type ToolPolicyMode = "inherited" | "allowed" | "blocked" | "excluded";
type AgentConfigPaneId = "overview" | "config" | "policies" | "membership" | "activity";

const AGENT_PRIMARY_MODE_OPTIONS = ["chat", "research", "supervised_evolution", "self_evolution", "general"];

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

function agentLabel(agent: AgentConfigWorkspaceAgent | null | undefined) {
  if (!agent) {
    return "-";
  }
  return agent.displayName || metadataString(agent, "functionalDisplayName") || agent.agentId || "-";
}

function agentFunctionalLabel(agent: AgentConfigWorkspaceAgent | null | undefined) {
  if (!agent) {
    return "-";
  }
  return metadataString(agent, "functionalDisplayName") || agent.roleKey || agent.primaryMode || "-";
}

function agentSearchText(agent: AgentConfigWorkspaceAgent) {
  return normalizeText(
    [
      agent.agentId,
      agent.agentCode,
      agent.displayName,
      agent.primaryMode,
      agent.roleKey,
      agent.profileId,
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
    return lang === "zh" ? "提示" : "Info";
  }
  return lang === "zh" ? "正常" : "OK";
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
  };
  const en: Record<string, string> = {
    direct_session: "Direct session",
    mode_default: "Mode default",
    mode_available: "Mode available",
    mode_pool: "Mode pool",
    mode_slot: "Role slot",
    flow_binding: "Flow binding",
    chat_room: "Group room",
  };
  return (lang === "zh" ? zh : en)[kind] ?? kind;
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

function filterAgents(
  workspace: AgentConfigWorkspace | undefined,
  activeFilter: FilterId,
  searchText: string,
) {
  const agents = workspace?.agents ?? [];
  const query = normalizeText(searchText);
  const group = (workspace?.groups ?? []).find((item) => item.id === activeFilter);
  const groupIds = new Set(group?.agentIds ?? []);
  return agents.filter((agent) => {
    if (group && !groupIds.has(agent.agentId)) {
      return false;
    }
    return !query || agentSearchText(agent).includes(query);
  });
}

function selectedAgentFromList(
  agents: AgentConfigWorkspaceAgent[],
  selectedAgentId: string,
  fallbackAgents: AgentConfigWorkspaceAgent[],
) {
  return (
    agents.find((agent) => agent.agentId === selectedAgentId) ??
    fallbackAgents.find((agent) => agent.agentId === selectedAgentId) ??
    agents[0] ??
    fallbackAgents[0] ??
    null
  );
}

function draftFromAgent(agent: AgentConfigWorkspaceAgent | null | undefined): AgentConfigDraft {
  return {
    displayName: agent?.displayName ?? "",
    profileId: agent?.profileId ?? "",
    promptTemplateId: agent?.promptTemplateId ?? "",
    toolPolicyId: agent?.toolPolicyId ?? "",
    memoryPolicyId: agent?.memoryPolicyId ?? "",
    status: agent?.status ?? "active",
  };
}

function draftEqualsAgent(draft: AgentConfigDraft, agent: AgentConfigWorkspaceAgent | null | undefined) {
  if (!agent) {
    return true;
  }
  const base = draftFromAgent(agent);
  return (Object.keys(base) as Array<keyof AgentConfigDraft>).every((key) => draft[key] === base[key]);
}

function createDraftFromWorkspace(workspace: AgentConfigWorkspace | undefined): AgentCreateDraft {
  const firstProfile = workspace?.modelProfiles?.[0]?.profileId ?? "primary";
  const firstPrompt = workspace?.promptTemplates?.find((item) => item.category === "chat") ?? workspace?.promptTemplates?.[0];
  return {
    displayName: "",
    profileId: firstProfile || "primary",
    primaryMode: "chat",
    roleKey: "",
    promptTemplateId: firstPrompt?.promptTemplateId || firstPrompt?.templateId || "prompt-chat-default",
  };
}

function normalizeCreateDraftForWorkspace(draft: AgentCreateDraft, workspace: AgentConfigWorkspace | undefined) {
  if (!workspace) {
    return draft;
  }
  const defaults = createDraftFromWorkspace(workspace);
  const profileIds = new Set((workspace.modelProfiles ?? []).map((profile) => profile.profileId));
  const promptIds = new Set((workspace.promptTemplates ?? []).map((template) => template.promptTemplateId || template.templateId || ""));
  const profileId = profileIds.size === 0 || profileIds.has(draft.profileId) ? draft.profileId : defaults.profileId;
  const promptTemplateId = !draft.promptTemplateId || promptIds.size === 0 || promptIds.has(draft.promptTemplateId)
    ? draft.promptTemplateId || defaults.promptTemplateId
    : defaults.promptTemplateId;
  return {
    ...draft,
    profileId: profileId || defaults.profileId,
    promptTemplateId,
  };
}

function createDraftReady(draft: AgentCreateDraft) {
  return Boolean(draft.displayName.trim() && draft.profileId.trim() && draft.primaryMode.trim());
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

function chatRoomDraftFromWorkspace(
  workspace: AgentConfigWorkspace | undefined,
  agent: AgentConfigWorkspaceAgent | null | undefined,
): AgentChatRoomMembershipDraft {
  const agentId = agent?.agentId ?? "";
  return {
    roomIds: (workspace?.chatRooms ?? [])
      .filter((room) => agentId && room.agentIds.includes(agentId))
      .map((room) => room.roomId),
  };
}

function sortedIds(values: string[]) {
  return Array.from(new Set(values.map((item) => String(item || "").trim()).filter(Boolean))).sort();
}

function sameStringSet(left: string[], right: string[]) {
  const leftSorted = sortedIds(left);
  const rightSorted = sortedIds(right);
  return leftSorted.length === rightSorted.length && leftSorted.every((value, index) => value === rightSorted[index]);
}

function chatRoomDraftEqualsWorkspace(
  draft: AgentChatRoomMembershipDraft,
  workspace: AgentConfigWorkspace | undefined,
  agent: AgentConfigWorkspaceAgent | null | undefined,
) {
  return sameStringSet(draft.roomIds, chatRoomDraftFromWorkspace(workspace, agent).roomIds);
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
  return {
    allowedTools: sortedIds(agent?.toolPolicy?.allowedTools ?? []),
    blockedTools: sortedIds(agent?.toolPolicy?.blockedTools ?? []),
  };
}

function toolPolicyDraftEqualsAgent(draft: AgentToolPolicyDraft, agent: AgentConfigWorkspaceAgent | null | undefined) {
  const base = toolPolicyDraftFromAgent(agent);
  return sameStringSet(draft.allowedTools, base.allowedTools) && sameStringSet(draft.blockedTools, base.blockedTools);
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

function toolPolicyModeLabel(mode: ToolPolicyMode, lang: "zh" | "en") {
  const zh = {
    inherited: "跟随默认",
    allowed: "允许",
    blocked: "禁用",
    excluded: "未列入",
  };
  const en = {
    inherited: "Default",
    allowed: "Allowed",
    blocked: "Blocked",
    excluded: "Excluded",
  };
  return (lang === "zh" ? zh : en)[mode];
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
  };
}

function memoryPolicyDraftFromAgent(agent: AgentConfigWorkspaceAgent | null | undefined): AgentMemoryPolicyDraft {
  return {
    readSharedGroups: sortedIds(agent?.memoryPolicy?.readSharedGroups ?? []),
    writeSharedGroups: sortedIds(agent?.memoryPolicy?.writeSharedGroups ?? []),
    newReadGroup: "",
    newWriteGroup: "",
  };
}

function memoryPolicyDraftEqualsAgent(draft: AgentMemoryPolicyDraft, agent: AgentConfigWorkspaceAgent | null | undefined) {
  const base = memoryPolicyDraftFromAgent(agent);
  return sameStringSet(draft.readSharedGroups, base.readSharedGroups) && sameStringSet(draft.writeSharedGroups, base.writeSharedGroups);
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
  return metadataFlag(agent, "protected") || systemRole === "ceo" || researchOrgRole === "organization_advisor";
}

function agentConfigPanes(copy: ReturnType<typeof agentsRouteCopy>, agent: AgentConfigWorkspaceAgent | null): Array<{
  id: AgentConfigPaneId;
  label: string;
  count: number;
}> {
  return [
    { id: "overview", label: copy.overviewPane, count: agent ? uniqueModes(agent).length : 0 },
    { id: "config", label: copy.configTitle, count: agent?.health.length ?? 0 },
    {
      id: "policies",
      label: copy.policiesPane,
      count: (agent?.toolPolicy?.allowedTools?.length ?? 0) + (agent?.toolPolicy?.blockedTools?.length ?? 0)
        + (agent?.memoryPolicy?.readSharedGroups?.length ?? 0) + (agent?.memoryPolicy?.writeSharedGroups?.length ?? 0),
    },
    { id: "membership", label: copy.membershipPane, count: agent?.references.length ?? 0 },
    { id: "activity", label: copy.activityPane, count: (agent?.agentInboxPendingCount ?? 0) + (agent?.groupContextEvents?.length ?? 0) },
  ];
}

function agentsRouteCopy(lang: "zh" | "en") {
  return lang === "zh"
    ? {
        eyebrow: "Agent Center",
        title: "Agent 中心",
        subtitle: "统一查看长期 Agent 的身份、模型、提示词、工具、记忆、模式归属和健康状态。",
        refresh: "刷新",
        loading: "正在整理 Agent 配置...",
        loadFailed: "Agent 配置加载失败",
        search: "搜索 Agent、模型、提示词、模式或引用",
        allAgents: "全部 Agent",
        activeAgents: "活跃 Agent",
        createAgent: "新增 Agent",
        createAgentTitle: "新增长期 Agent",
        createAgentHint: "新 Agent 会创建一个直连会话，并保留独立工作区、记忆策略和工具策略。",
        createAgentName: "功能名",
        createAgentNamePlaceholder: "例如：科研复核 Agent",
        createAgentRole: "角色键",
        createAgentRolePlaceholder: "可选，例如 research_reviewer",
        cancelCreate: "取消",
        creatingAgent: "创建中...",
        archiveAgent: "安全归档",
        archivingAgent: "归档中...",
        archiveAgentTitle: "安全删减",
        archiveAgentHint: "归档会从默认模式、群聊成员和可选池中移除该 Agent，但保留会话、记忆、日志和工作区。",
        archiveConfirm: "确认归档 {name}？这会隐藏该 Agent 并清理模式/群聊引用，但不会物理删除数据。",
        protectedAgent: "受保护 Agent 不能归档",
        healthIssues: "健康问题",
        chatRooms: "群聊",
        inbox: "待处理消息",
        model: "模型模板",
        prompt: "提示词",
        tools: "工具权限",
        memory: "记忆策略",
        context: "上下文",
        run: "运行",
        communication: "通信",
        delegation: "子 Agent",
        modeMembership: "模式归属",
        references: "引用位置",
        sessions: "会话 / 群聊 / 工作区",
        logs: "运行记录与日志",
        noAgents: "没有匹配当前筛选的 Agent。",
        selectAgent: "选择一个 Agent 查看统一配置卡片。",
        readOnly: "只读总览",
        policyPending: "策略注册表待接入",
        noIssues: "当前没有明显健康问题。",
        routeHint: "这张卡片是 Agent 的唯一配置点；业务页面只引用这里的 Agent。",
        overviewPane: "总览",
        policiesPane: "策略",
        membershipPane: "归属",
        activityPane: "运行",
        configTitle: "基础配置",
        saveConfig: "保存配置",
        resetConfig: "重置",
        savingConfig: "保存中...",
        status: "状态",
        membershipTitle: "模式归属",
        saveMembership: "保存归属",
        savingMembership: "保存归属中...",
        chatRoomMembership: "群聊成员",
        saveChatRooms: "保存群聊",
        savingChatRooms: "保存群聊中...",
        noChatRooms: "还没有可配置的群聊。",
        toolPolicyTitle: "工具权限",
        saveToolPolicy: "保存权限",
        savingToolPolicy: "保存权限中...",
        toolSearch: "筛选工具",
        noTools: "当前没有可配置的工具。",
        allowedTools: "允许",
        blockedTools: "禁用",
        inheritedTools: "默认",
        memoryPolicyTitle: "记忆策略",
        saveMemoryPolicy: "保存记忆",
        savingMemoryPolicy: "保存记忆中...",
        readSharedGroups: "可读共享组",
        writeSharedGroups: "可写共享组",
        addSharedGroup: "添加",
        sharedGroupPlaceholder: "输入共享组，例如 project",
        noSharedGroups: "未配置共享组。",
        delegationPolicyTitle: "委托策略",
        supervisionPolicyTitle: "监督策略",
        saveRuntimePolicy: "保存运行策略",
        savingRuntimePolicy: "保存运行策略中...",
        allowSubagents: "允许子 Agent",
        maxConcurrent: "最大并发",
        allowWakeMessages: "允许唤醒消息",
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
        runHistoryLoading: "正在读取运行历史...",
        noRunHistory: "还没有运行或子 Agent 记录。",
        subAgentRuns: "子 Agent 运行",
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
        allAgents: "All Agents",
        activeAgents: "Active Agents",
        createAgent: "New Agent",
        createAgentTitle: "Create persistent Agent",
        createAgentHint: "A new Agent gets a direct chat session plus its own workspace, memory policy, and tool policy.",
        createAgentName: "Functional name",
        createAgentNamePlaceholder: "e.g. Research review Agent",
        createAgentRole: "Role key",
        createAgentRolePlaceholder: "Optional, e.g. research_reviewer",
        cancelCreate: "Cancel",
        creatingAgent: "Creating...",
        archiveAgent: "Safe archive",
        archivingAgent: "Archiving...",
        archiveAgentTitle: "Safe removal",
        archiveAgentHint: "Archiving removes this Agent from defaults, rooms, and pools while keeping sessions, memory, logs, and workspace data.",
        archiveConfirm: "Archive {name}? This hides the Agent and cleans mode/room references, but does not physically delete data.",
        protectedAgent: "Protected Agents cannot be archived",
        healthIssues: "Health Issues",
        chatRooms: "Group Rooms",
        inbox: "Pending inbox",
        model: "Model profile",
        prompt: "Prompt",
        tools: "Tool policy",
        memory: "Memory policy",
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
        noIssues: "No obvious health issues.",
        routeHint: "This card is the single Agent config point. Product pages should only reference Agents from here.",
        overviewPane: "Overview",
        policiesPane: "Policies",
        membershipPane: "Membership",
        activityPane: "Activity",
        configTitle: "Base config",
        saveConfig: "Save config",
        resetConfig: "Reset",
        savingConfig: "Saving...",
        status: "Status",
        membershipTitle: "Mode membership",
        saveMembership: "Save membership",
        savingMembership: "Saving membership...",
        chatRoomMembership: "Group room membership",
        saveChatRooms: "Save rooms",
        savingChatRooms: "Saving rooms...",
        noChatRooms: "No group rooms available.",
        toolPolicyTitle: "Tool permissions",
        saveToolPolicy: "Save permissions",
        savingToolPolicy: "Saving permissions...",
        toolSearch: "Filter tools",
        noTools: "No configurable tools are available.",
        allowedTools: "Allowed",
        blockedTools: "Blocked",
        inheritedTools: "Default",
        memoryPolicyTitle: "Memory policy",
        saveMemoryPolicy: "Save memory",
        savingMemoryPolicy: "Saving memory...",
        readSharedGroups: "Readable shared groups",
        writeSharedGroups: "Writable shared groups",
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
        runHistoryLoading: "Loading run history...",
        noRunHistory: "No run or sub-agent history yet.",
        subAgentRuns: "Sub-agent runs",
        parentRuns: "Parent runs",
        supervisedRole: "Supervised role",
        maxDepth: "Max depth",
      };
}

export function AgentsRoute() {
  const { lang } = useAppI18n();
  const queryClient = useQueryClient();
  const pageVisible = usePageVisibility();
  const copy = useMemo(() => agentsRouteCopy(lang), [lang]);
  const [activeFilter, setActiveFilter] = useState<FilterId>("all");
  const [searchText, setSearchText] = useState("");
  const [selectedAgentId, setSelectedAgentId] = useState("");
  const [activePane, setActivePane] = useState<AgentConfigPaneId>("overview");
  const [createOpen, setCreateOpen] = useState(false);
  const [createDraft, setCreateDraft] = useState<AgentCreateDraft>(() => createDraftFromWorkspace(undefined));
  const [configDraft, setConfigDraft] = useState<AgentConfigDraft>(() => draftFromAgent(null));
  const [membershipDraft, setMembershipDraft] = useState<AgentModeMembershipDraft>(() => membershipDraftFromWorkspace(undefined, null));
  const [chatRoomDraft, setChatRoomDraft] = useState<AgentChatRoomMembershipDraft>(() => chatRoomDraftFromWorkspace(undefined, null));
  const [toolPolicyDraft, setToolPolicyDraft] = useState<AgentToolPolicyDraft>(() => toolPolicyDraftFromAgent(null));
  const [memoryPolicyDraft, setMemoryPolicyDraft] = useState<AgentMemoryPolicyDraft>(() => memoryPolicyDraftFromAgent(null));
  const [delegationPolicyDraft, setDelegationPolicyDraft] = useState<AgentDelegationPolicyDraft>(() => delegationPolicyDraftFromAgent(null));
  const [supervisionPolicyDraft, setSupervisionPolicyDraft] = useState<AgentSupervisionPolicyDraft>(() => supervisionPolicyDraftFromAgent(null));
  const [toolSearchText, setToolSearchText] = useState("");
  const [notice, setNotice] = useState<{ tone: "success" | "error"; text: string } | null>(null);

  const workspaceQuery = useQuery({
    queryKey: queryKeys.agentConfigWorkspace(),
    queryFn: () => fetchJson<AgentConfigWorkspace>("/api/agents/config-workspace"),
    refetchInterval: resolvePollingInterval(pageVisible, 12_000),
    refetchIntervalInBackground: false,
  });

  const toolsQuery = useQuery({
    queryKey: queryKeys.tools(),
    queryFn: () => fetchJson<ToolRegistryPayload>("/api/tools"),
    refetchInterval: resolvePollingInterval(pageVisible, 15_000),
    refetchIntervalInBackground: false,
  });

  const workspace = workspaceQuery.data;
  const tools = toolsQuery.data?.tools ?? [];
  const visibleAgents = useMemo(
    () => filterAgents(workspace, activeFilter, searchText),
    [activeFilter, searchText, workspace],
  );
  const visiblePolicyTools = useMemo(() => {
    const query = normalizeText(toolSearchText);
    return tools.filter((tool) => {
      if (!tool.llmVisible && !tool.runtimeActive) {
        return false;
      }
      if (!query) {
        return true;
      }
      return normalizeText(`${tool.name} ${tool.description} ${tool.source} ${tool.status}`).includes(query);
    });
  }, [toolSearchText, tools]);
  const selectedAgent = selectedAgentFromList(visibleAgents, selectedAgentId, workspace?.agents ?? []);
  const memoryGroupOptions = useMemo(() => sharedGroupCandidates(workspace, selectedAgent), [selectedAgent?.agentId, workspace?.generatedAt]);
  const panes = useMemo(() => agentConfigPanes(copy, selectedAgent), [copy, selectedAgent]);
  const agentRunsQuery = useQuery({
    queryKey: queryKeys.agentRuns(selectedAgent?.agentId ?? ""),
    queryFn: () => fetchJson<AgentRunHistory>(`/api/agents/${encodeURIComponent(selectedAgent?.agentId ?? "")}/runs?limit=12`),
    enabled: Boolean(selectedAgent?.agentId && activePane === "activity"),
    refetchInterval: resolvePollingInterval(pageVisible, 12_000),
    refetchIntervalInBackground: false,
  });
  const groups = workspace?.groups ?? [];
  const summary = workspace?.summary;
  const healthStatus = workspace?.health.status ?? "ok";
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.agentConfigWorkspace() });
  };

  useEffect(() => {
    setConfigDraft(draftFromAgent(selectedAgent));
    setMembershipDraft(membershipDraftFromWorkspace(workspace, selectedAgent));
    setChatRoomDraft(chatRoomDraftFromWorkspace(workspace, selectedAgent));
    setToolPolicyDraft(toolPolicyDraftFromAgent(selectedAgent));
    setMemoryPolicyDraft(memoryPolicyDraftFromAgent(selectedAgent));
    setDelegationPolicyDraft(delegationPolicyDraftFromAgent(selectedAgent));
    setSupervisionPolicyDraft(supervisionPolicyDraftFromAgent(selectedAgent));
    setToolSearchText("");
    setNotice(null);
  }, [selectedAgent?.agentId, workspace?.generatedAt]);

  useEffect(() => {
    setActivePane("overview");
  }, [selectedAgent?.agentId]);

  useEffect(() => {
    setCreateDraft((current) => {
      if (current.profileId || current.promptTemplateId) {
        return normalizeCreateDraftForWorkspace(current, workspace);
      }
      return createDraftFromWorkspace(workspace);
    });
  }, [workspace]);

  const configDirty = !draftEqualsAgent(configDraft, selectedAgent);
  const membershipDirty = !membershipDraftEqualsWorkspace(membershipDraft, workspace, selectedAgent);
  const chatRoomDirty = !chatRoomDraftEqualsWorkspace(chatRoomDraft, workspace, selectedAgent);
  const toolPolicyDirty = !toolPolicyDraftEqualsAgent(toolPolicyDraft, selectedAgent);
  const memoryPolicyDirty = !memoryPolicyDraftEqualsAgent(memoryPolicyDraft, selectedAgent);
  const runtimePolicyDirty = !delegationPolicyDraftEqualsAgent(delegationPolicyDraft, selectedAgent)
    || !supervisionPolicyDraftEqualsAgent(supervisionPolicyDraft, selectedAgent);
  const canSaveConfig = Boolean(selectedAgent?.agentId && configDraft.displayName.trim() && configDirty);
  const canSaveMembership = Boolean(selectedAgent?.agentId && membershipDirty);
  const canSaveChatRooms = Boolean(selectedAgent?.agentId && chatRoomDirty);
  const canSaveToolPolicy = Boolean(selectedAgent?.agentId && toolPolicyDirty);
  const canSaveMemoryPolicy = Boolean(selectedAgent?.agentId && memoryPolicyDirty);
  const canSaveRuntimePolicy = Boolean(selectedAgent?.agentId && runtimePolicyDirty);
  const canCreateAgent = createDraftReady(createDraft);
  const selectedAgentProtected = agentArchiveProtected(selectedAgent);
  const canArchiveAgent = Boolean(selectedAgent?.agentId && selectedAgent.status !== "archived" && !selectedAgentProtected);

  const createAgentMutation = useMutation({
    mutationFn: (draft: AgentCreateDraft) =>
      fetchJson<AgentConfigWorkspaceAgent>("/api/agents", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          displayName: draft.displayName.trim(),
          profileId: draft.profileId,
          primaryMode: draft.primaryMode,
          roleKey: draft.roleKey,
          promptTemplateId: draft.promptTemplateId,
        }),
      }),
    onSuccess: (agent) => {
      setSelectedAgentId(agent.agentId);
      setActivePane("config");
      setCreateOpen(false);
      setCreateDraft(createDraftFromWorkspace(workspace));
      setNotice({
        tone: "success",
        text: lang === "zh" ? `已新增 ${agentLabel(agent)}` : `Created ${agentLabel(agent)}`,
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.agentConfigWorkspace() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.agents() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.sessions() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.conversations() });
    },
    onError: (error) => {
      setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    },
  });

  const updateAgentMutation = useMutation({
    mutationFn: (payload: { agentId: string; draft: AgentConfigDraft }) =>
      fetchJson<AgentConfigWorkspaceAgent>(`/api/agents/${encodeURIComponent(payload.agentId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          displayName: payload.draft.displayName,
          profileId: payload.draft.profileId,
          promptTemplateId: payload.draft.promptTemplateId,
          toolPolicyId: payload.draft.toolPolicyId,
          memoryPolicyId: payload.draft.memoryPolicyId,
          status: payload.draft.status,
        }),
      }),
    onSuccess: (agent) => {
      setNotice({
        tone: "success",
        text: lang === "zh" ? `已保存 ${agentLabel(agent)} 的 Agent 配置` : `Saved config for ${agentLabel(agent)}`,
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.agentConfigWorkspace() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.agents() });
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
    onSuccess: (agent) => {
      setSelectedAgentId("");
      setActivePane("overview");
      setNotice({
        tone: "success",
        text: lang === "zh" ? `已安全归档 ${agentLabel(agent)}` : `Archived ${agentLabel(agent)}`,
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.agentConfigWorkspace() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.agents() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.agentModeBindings() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.chatRooms() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.sessions() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.conversations() });
    },
    onError: (error) => {
      setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    },
  });

  const updateMembershipMutation = useMutation({
    mutationFn: (payload: { agentId: string; draft: AgentModeMembershipDraft }) =>
      fetchJson(`/api/agents/${encodeURIComponent(payload.agentId)}/mode-membership`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload.draft),
      }),
    onSuccess: () => {
      setNotice({
        tone: "success",
        text: lang === "zh" ? "已保存 Agent 模式归属" : "Saved Agent mode membership",
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.agentConfigWorkspace() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.agentModeBindings() });
    },
    onError: (error) => {
      setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    },
  });

  const updateChatRoomsMutation = useMutation({
    mutationFn: (payload: { agentId: string; draft: AgentChatRoomMembershipDraft }) =>
      fetchJson(`/api/agents/${encodeURIComponent(payload.agentId)}/chat-rooms`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ roomIds: sortedIds(payload.draft.roomIds) }),
      }),
    onSuccess: () => {
      setNotice({
        tone: "success",
        text: lang === "zh" ? "已保存 Agent 群聊成员关系" : "Saved Agent group room membership",
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.agentConfigWorkspace() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.chatRooms() });
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
            blockedTools: sortedIds(payload.draft.blockedTools),
          },
        }),
      }),
    onSuccess: (agent) => {
      setNotice({
        tone: "success",
        text: lang === "zh" ? `已保存 ${agentLabel(agent)} 的工具权限` : `Saved tool permissions for ${agentLabel(agent)}`,
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.agentConfigWorkspace() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.agents() });
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
          },
        }),
      }),
    onSuccess: (agent) => {
      setNotice({
        tone: "success",
        text: lang === "zh" ? `已保存 ${agentLabel(agent)} 的记忆策略` : `Saved memory policy for ${agentLabel(agent)}`,
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.agentConfigWorkspace() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.agents() });
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
      setNotice({
        tone: "success",
        text: lang === "zh" ? `已保存 ${agentLabel(agent)} 的运行策略` : `Saved runtime policy for ${agentLabel(agent)}`,
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.agentConfigWorkspace() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.agents() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.agentRuns(agent.agentId) });
    },
    onError: (error) => {
      setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    },
  });

  const updateDraft = (patch: Partial<AgentConfigDraft>) => {
    setConfigDraft((current) => ({ ...current, ...patch }));
  };

  const updateCreateDraft = (patch: Partial<AgentCreateDraft>) => {
    setCreateDraft((current) => ({ ...current, ...patch }));
  };

  const updateMembershipDraft = (patch: Partial<AgentModeMembershipDraft>) => {
    setMembershipDraft((current) => ({ ...current, ...patch }));
  };

  const toggleChatRoomDraft = (roomId: string, selected: boolean) => {
    setChatRoomDraft((current) => {
      const roomIds = new Set(current.roomIds);
      if (selected) {
        roomIds.add(roomId);
      } else {
        roomIds.delete(roomId);
      }
      return { roomIds: Array.from(roomIds) };
    });
  };

  const updateToolPolicyMode = (toolName: string, mode: Exclude<ToolPolicyMode, "excluded">) => {
    setToolPolicyDraft((current) => {
      const allowed = new Set(current.allowedTools);
      const blocked = new Set(current.blockedTools);
      allowed.delete(toolName);
      blocked.delete(toolName);
      if (mode === "allowed") {
        allowed.add(toolName);
      }
      if (mode === "blocked") {
        blocked.add(toolName);
      }
      return { allowedTools: sortedIds(Array.from(allowed)), blockedTools: sortedIds(Array.from(blocked)) };
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
    if (!selectedAgent || !canSaveConfig) {
      return;
    }
    updateAgentMutation.mutate({ agentId: selectedAgent.agentId, draft: configDraft });
  };

  const saveModeMembership = () => {
    if (!selectedAgent || !canSaveMembership) {
      return;
    }
    updateMembershipMutation.mutate({ agentId: selectedAgent.agentId, draft: membershipDraft });
  };

  const saveChatRoomMembership = () => {
    if (!selectedAgent || !canSaveChatRooms) {
      return;
    }
    updateChatRoomsMutation.mutate({ agentId: selectedAgent.agentId, draft: chatRoomDraft });
  };

  const saveToolPolicy = () => {
    if (!selectedAgent || !canSaveToolPolicy) {
      return;
    }
    updateToolPolicyMutation.mutate({
      agentId: selectedAgent.agentId,
      draft: toolPolicyDraft,
      basePolicy: selectedAgent.toolPolicy,
    });
  };

  const saveMemoryPolicy = () => {
    if (!selectedAgent || !canSaveMemoryPolicy) {
      return;
    }
    updateMemoryPolicyMutation.mutate({
      agentId: selectedAgent.agentId,
      draft: memoryPolicyDraft,
      basePolicy: selectedAgent.memoryPolicy,
    });
  };

  const saveRuntimePolicy = () => {
    if (!selectedAgent || !canSaveRuntimePolicy) {
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

  const archiveSelectedAgent = () => {
    if (!selectedAgent || !canArchiveAgent || archiveAgentMutation.isPending) {
      return;
    }
    const confirmed = window.confirm(copy.archiveConfirm.replace("{name}", agentLabel(selectedAgent)));
    if (!confirmed) {
      return;
    }
    archiveAgentMutation.mutate({ agentId: selectedAgent.agentId });
  };

  return (
    <section className={styles.route}>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>{copy.eyebrow}</p>
          <h1 className={styles.title}>{copy.title}</h1>
          <p className={styles.subtitle}>{copy.subtitle}</p>
        </div>
        <span className={`${styles.healthPill} ${styles[`health_${healthStatus}`]}`}>
          {healthStatus}
        </span>
        <button type="button" className={styles.refreshButton} onClick={refresh}>
          <RefreshCw size={16} />
          {copy.refresh}
        </button>
      </header>

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
      </div>

      <div className={styles.workspace}>
        <aside className={styles.filterPanel}>
          <label className={styles.searchBox}>
            <Search size={15} />
            <input value={searchText} placeholder={copy.search} onChange={(event) => setSearchText(event.target.value)} />
          </label>
          <nav className={styles.groupList} aria-label={copy.allAgents}>
            {groups.map((group) => {
              const active = activeFilter === group.id;
              return (
                <button
                  key={group.id}
                  type="button"
                  className={active ? `${styles.groupButton} ${styles.groupButtonActive}` : styles.groupButton}
                  onClick={() => setActiveFilter(group.id)}
                >
                  <span>
                    <Bot size={15} />
                    {group.label}
                  </span>
                  <strong>{group.count}</strong>
                  {group.healthCount ? <em>{group.healthCount}</em> : null}
                </button>
              );
            })}
          </nav>
          <section className={styles.storagePanel}>
            <p className={styles.panelEyebrow}>{copy.readOnly}</p>
            <code>{workspace?.storage.agentRegistryPath ?? "workspace/agents/agents.json"}</code>
            <code>{workspace?.storage.modeBindingPath ?? "workspace/agent_config/mode_bindings.json"}</code>
          </section>
        </aside>

        <main className={styles.agentPanel}>
          <div className={styles.panelHeader}>
            <div>
              <p className={styles.panelEyebrow}>{copy.allAgents}</p>
              <h2>{groups.find((group) => group.id === activeFilter)?.label ?? copy.allAgents}</h2>
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
            <section className={styles.createAgentPanel}>
              <div className={styles.panelHeader}>
                <div>
                  <p className={styles.panelEyebrow}>{copy.createAgentTitle}</p>
                  <h3>{copy.createAgent}</h3>
                </div>
                <Bot size={16} />
              </div>
              <p>{copy.createAgentHint}</p>
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
                  <select value={createDraft.profileId} onChange={(event) => updateCreateDraft({ profileId: event.target.value })}>
                    {workspace?.modelProfiles.map((profile) => (
                      <option key={profile.profileId} value={profile.profileId}>
                        {profile.label || profile.profileId} · {profile.model || profile.providerKind || "-"}
                      </option>
                    ))}
                  </select>
                </label>
                <label className={styles.field}>
                  <span>{copy.modeMembership}</span>
                  <select value={createDraft.primaryMode} onChange={(event) => updateCreateDraft({ primaryMode: event.target.value })}>
                    {AGENT_PRIMARY_MODE_OPTIONS.map((mode) => (
                      <option key={mode} value={mode}>
                        {modeLabel(mode, lang)}
                      </option>
                    ))}
                  </select>
                </label>
                <label className={styles.field}>
                  <span>{copy.createAgentRole}</span>
                  <input
                    value={createDraft.roleKey}
                    placeholder={copy.createAgentRolePlaceholder}
                    onChange={(event) => updateCreateDraft({ roleKey: event.target.value })}
                  />
                </label>
                <label className={styles.field}>
                  <span>{copy.prompt}</span>
                  <select value={createDraft.promptTemplateId} onChange={(event) => updateCreateDraft({ promptTemplateId: event.target.value })}>
                    <option value="">-</option>
                    {workspace?.promptTemplates.map((template) => (
                      <option key={template.promptTemplateId || template.templateId} value={template.promptTemplateId || template.templateId || ""}>
                        {template.name || template.promptTemplateId} · {template.category}
                      </option>
                    ))}
                  </select>
                </label>
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
                    setCreateDraft(createDraftFromWorkspace(workspace));
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
            <div className={styles.agentTable}>
              <div className={styles.agentTableHead}>
                <span>Agent</span>
                <span>{copy.model}</span>
                <span>{copy.prompt}</span>
                <span>{copy.modeMembership}</span>
                <span>{copy.healthIssues}</span>
              </div>
              {visibleAgents.map((agent) => {
                const active = selectedAgent?.agentId === agent.agentId;
                const tone = issueTone(agent.health);
                return (
                  <button
                    key={agent.agentId}
                    type="button"
                    className={active ? `${styles.agentRow} ${styles.agentRowActive}` : styles.agentRow}
                    onClick={() => setSelectedAgentId(agent.agentId)}
                  >
                    <span className={styles.agentIdentity}>
                      <strong>{agentLabel(agent)}</strong>
                      <span>{agentFunctionalLabel(agent)}</span>
                    </span>
                    <span>{agent.modelProfile?.label || agent.profileId || "-"}</span>
                    <span>{agent.promptTemplate?.name || agent.promptTemplateId || "-"}</span>
                    <span className={styles.modeList}>
                      {uniqueModes(agent).slice(0, 3).map((mode) => (
                        <em key={`${agent.agentId}:${mode}`}>{modeLabel(mode, lang)}</em>
                      ))}
                    </span>
                    <span className={`${styles.issuePill} ${styles[`issue_${tone}`]}`}>
                      {issueLabel(agent.health, lang)}
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </main>

        <aside className={styles.detailPanel}>
          {selectedAgent ? (
            <>
              <section className={styles.detailHeader}>
                <div>
                  <p className={styles.panelEyebrow}>{agentFunctionalLabel(selectedAgent)}</p>
                  <h2>{agentLabel(selectedAgent)}</h2>
                  <p>{copy.routeHint}</p>
                </div>
                <span className={`${styles.issuePill} ${styles[`issue_${issueTone(selectedAgent.health)}`]}`}>
                  {issueLabel(selectedAgent.health, lang)}
                </span>
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

              {activePane === "overview" ? (
                <>
                  <div className={styles.factGrid}>
                    <section>
                      <Bot size={16} />
                      <span>{copy.model}</span>
                      <strong>{selectedAgent.modelProfile?.label || selectedAgent.profileId || "-"}</strong>
                      <small>{selectedAgent.modelProfile?.model || selectedAgent.modelProfile?.providerKind || "-"}</small>
                    </section>
                    <section>
                      <Layers3 size={16} />
                      <span>{lang === "zh" ? "后台编号" : "Backend IDs"}</span>
                      <strong>{selectedAgent.agentCode || "-"}</strong>
                      <small>{selectedAgent.agentId || "-"}</small>
                    </section>
                    <section>
                      <Brain size={16} />
                      <span>{copy.prompt}</span>
                      <strong>{selectedAgent.promptTemplate?.name || selectedAgent.promptTemplateId || "-"}</strong>
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
                  </div>

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
                      <strong>{copy.run}</strong>
                      <span>{selectedAgent.status || "-"}</span>
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
              <section className={styles.configEditor}>
                <div className={styles.panelHeader}>
                  <div>
                    <p className={styles.panelEyebrow}>{copy.configTitle}</p>
                    <h3>{agentLabel(selectedAgent)}</h3>
                  </div>
                  <span className={configDirty ? styles.dirtyPill : styles.cleanPill}>
                    {configDirty ? (lang === "zh" ? "未保存" : "Unsaved") : (lang === "zh" ? "已同步" : "Synced")}
                  </span>
                </div>
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
                      <option value="archived">{lang === "zh" ? "归档" : "Archived"}</option>
                    </select>
                  </label>
                  <label className={styles.field}>
                    <span>{copy.model}</span>
                    <select value={configDraft.profileId} onChange={(event) => updateDraft({ profileId: event.target.value })}>
                      {workspace?.modelProfiles.map((profile) => (
                        <option key={profile.profileId} value={profile.profileId}>
                          {profile.label || profile.profileId} · {profile.model || profile.providerKind || "-"}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className={styles.field}>
                    <span>{copy.prompt}</span>
                    <select value={configDraft.promptTemplateId} onChange={(event) => updateDraft({ promptTemplateId: event.target.value })}>
                      <option value="">-</option>
                      {workspace?.promptTemplates.map((template) => (
                        <option key={template.promptTemplateId || template.templateId} value={template.promptTemplateId || template.templateId || ""}>
                          {template.name || template.promptTemplateId} · {template.category}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className={styles.field}>
                    <span>{copy.tools}</span>
                    <select value={configDraft.toolPolicyId} onChange={(event) => updateDraft({ toolPolicyId: event.target.value })}>
                      {workspace?.toolPolicies.map((policy) => (
                        <option key={policy.policyId} value={policy.policyId}>
                          {policy.policyId} · {policy.allowedToolCount}/{policy.blockedToolCount}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className={styles.field}>
                    <span>{copy.memory}</span>
                    <select value={configDraft.memoryPolicyId} onChange={(event) => updateDraft({ memoryPolicyId: event.target.value })}>
                      {workspace?.memoryPolicies.map((policy) => (
                        <option key={policy.policyId} value={policy.policyId}>
                          {policy.policyId} · {policy.privateMemoryRoot || "-"}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                {notice ? (
                  <p className={notice.tone === "error" ? styles.errorText : styles.successText}>{notice.text}</p>
                ) : null}
                <div className={styles.editorActions}>
                  <button type="button" className={styles.secondaryButton} disabled={!configDirty || updateAgentMutation.isPending} onClick={() => setConfigDraft(draftFromAgent(selectedAgent))}>
                    {copy.resetConfig}
                  </button>
                  <button type="button" className={styles.primaryButton} disabled={!canSaveConfig || updateAgentMutation.isPending} onClick={saveAgentConfig}>
                    {updateAgentMutation.isPending ? copy.savingConfig : copy.saveConfig}
                  </button>
                </div>
              </section>

              <section className={styles.detailSection}>
                <div className={styles.panelHeader}>
                  <div>
                    <p className={styles.panelEyebrow}>{copy.healthIssues}</p>
                    <h3>{selectedAgent.health.length || copy.noIssues}</h3>
                  </div>
                  {selectedAgent.health.length ? <AlertTriangle size={16} /> : <CheckCircle2 size={16} />}
                </div>
                {selectedAgent.health.length ? (
                  <div className={styles.issueList}>
                    {selectedAgent.health.map((issue) => (
                      <article key={`${issue.code}:${issue.detail}`} className={`${styles.issueItem} ${styles[`issueItem_${issue.severity}`]}`}>
                        <strong>{issue.title}</strong>
                        <p>{issue.detail}</p>
                      </article>
                    ))}
                  </div>
                ) : (
                  <p className={styles.emptyText}>{copy.noIssues}</p>
                )}
              </section>

              <section className={styles.dangerZone}>
                <div className={styles.panelHeader}>
                  <div>
                    <p className={styles.panelEyebrow}>{copy.archiveAgentTitle}</p>
                    <h3>{copy.archiveAgent}</h3>
                  </div>
                  <Trash2 size={16} />
                </div>
                <p>{selectedAgentProtected ? copy.protectedAgent : copy.archiveAgentHint}</p>
                <div className={styles.editorActions}>
                  <button
                    type="button"
                    className={styles.dangerButton}
                    disabled={!canArchiveAgent || archiveAgentMutation.isPending}
                    onClick={archiveSelectedAgent}
                  >
                    <Trash2 size={15} />
                    {archiveAgentMutation.isPending ? copy.archivingAgent : copy.archiveAgent}
                  </button>
                </div>
              </section>
                </>
              ) : null}

              {activePane === "policies" ? (
                <>
              <section className={styles.configEditor}>
                <div className={styles.panelHeader}>
                  <div>
                    <p className={styles.panelEyebrow}>{copy.toolPolicyTitle}</p>
                    <h3>{selectedAgent.toolPolicyId || "-"}</h3>
                  </div>
                  <span className={toolPolicyDirty ? styles.dirtyPill : styles.cleanPill}>
                    {toolPolicyDirty ? (lang === "zh" ? "未保存" : "Unsaved") : (lang === "zh" ? "已同步" : "Synced")}
                  </span>
                </div>
                <div className={styles.policySummaryGrid}>
                  <span>{copy.allowedTools}: <strong>{toolPolicyDraft.allowedTools.length}</strong></span>
                  <span>{copy.blockedTools}: <strong>{toolPolicyDraft.blockedTools.length}</strong></span>
                  <span>{copy.inheritedTools}: <strong>{Math.max(0, visiblePolicyTools.length - toolPolicyDraft.allowedTools.length - toolPolicyDraft.blockedTools.length)}</strong></span>
                </div>
                <label className={styles.searchBox}>
                  <Search size={15} />
                  <input value={toolSearchText} placeholder={copy.toolSearch} onChange={(event) => setToolSearchText(event.target.value)} />
                </label>
                {visiblePolicyTools.length ? (
                  <div className={styles.toolPermissionList}>
                    {visiblePolicyTools.map((tool) => {
                      const mode = toolPolicyMode(toolPolicyDraft, tool.name);
                      return (
                        <div key={`${tool.source}:${tool.id}`} className={styles.toolPermissionRow}>
                          <span>
                            <strong>{tool.name}</strong>
                            <small>{tool.description || tool.source}</small>
                          </span>
                          <div className={styles.segmentedControl} aria-label={tool.name}>
                            <button
                              type="button"
                              className={mode === "inherited" || mode === "excluded" ? styles.segmentActive : styles.segmentButton}
                              onClick={() => updateToolPolicyMode(tool.name, "inherited")}
                            >
                              {toolPolicyModeLabel(mode === "excluded" ? "excluded" : "inherited", lang)}
                            </button>
                            <button
                              type="button"
                              className={mode === "allowed" ? styles.segmentActive : styles.segmentButton}
                              onClick={() => updateToolPolicyMode(tool.name, "allowed")}
                            >
                              {toolPolicyModeLabel("allowed", lang)}
                            </button>
                            <button
                              type="button"
                              className={mode === "blocked" ? styles.segmentActiveDanger : styles.segmentButton}
                              onClick={() => updateToolPolicyMode(tool.name, "blocked")}
                            >
                              {toolPolicyModeLabel("blocked", lang)}
                            </button>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <p className={styles.emptyText}>{copy.noTools}</p>
                )}
                <div className={styles.editorActions}>
                  <button
                    type="button"
                    className={styles.secondaryButton}
                    disabled={!toolPolicyDirty || updateToolPolicyMutation.isPending}
                    onClick={() => setToolPolicyDraft(toolPolicyDraftFromAgent(selectedAgent))}
                  >
                    {copy.resetConfig}
                  </button>
                  <button
                    type="button"
                    className={styles.primaryButton}
                    disabled={!canSaveToolPolicy || updateToolPolicyMutation.isPending}
                    onClick={saveToolPolicy}
                  >
                    {updateToolPolicyMutation.isPending ? copy.savingToolPolicy : copy.saveToolPolicy}
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
                </div>
                <datalist id="agent-memory-groups">
                  {memoryGroupOptions.map((group) => <option key={group} value={group} />)}
                </datalist>
                <div className={styles.editorActions}>
                  <button
                    type="button"
                    className={styles.secondaryButton}
                    disabled={!memoryPolicyDirty || updateMemoryPolicyMutation.isPending}
                    onClick={() => setMemoryPolicyDraft(memoryPolicyDraftFromAgent(selectedAgent))}
                  >
                    {copy.resetConfig}
                  </button>
                  <button
                    type="button"
                    className={styles.primaryButton}
                    disabled={!canSaveMemoryPolicy || updateMemoryPolicyMutation.isPending}
                    onClick={saveMemoryPolicy}
                  >
                    {updateMemoryPolicyMutation.isPending ? copy.savingMemoryPolicy : copy.saveMemoryPolicy}
                  </button>
                </div>
              </section>
                </>
              ) : null}

              {activePane === "membership" ? (
                <>
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
                    disabled={!membershipDirty || updateMembershipMutation.isPending}
                    onClick={() => setMembershipDraft(membershipDraftFromWorkspace(workspace, selectedAgent))}
                  >
                    {copy.resetConfig}
                  </button>
                  <button
                    type="button"
                    className={styles.primaryButton}
                    disabled={!canSaveMembership || updateMembershipMutation.isPending}
                    onClick={saveModeMembership}
                  >
                    {updateMembershipMutation.isPending ? copy.savingMembership : copy.saveMembership}
                  </button>
                </div>
              </section>

              <section className={styles.configEditor}>
                <div className={styles.panelHeader}>
                  <div>
                    <p className={styles.panelEyebrow}>{copy.chatRoomMembership}</p>
                    <h3>{chatRoomDraft.roomIds.length} / {workspace?.chatRooms.length ?? 0}</h3>
                  </div>
                  <span className={chatRoomDirty ? styles.dirtyPill : styles.cleanPill}>
                    {chatRoomDirty ? (lang === "zh" ? "未保存" : "Unsaved") : (lang === "zh" ? "已同步" : "Synced")}
                  </span>
                </div>
                {(workspace?.chatRooms.length ?? 0) > 0 ? (
                  <div className={styles.roomMembershipList}>
                    {workspace?.chatRooms.map((room) => {
                      const selected = chatRoomDraft.roomIds.includes(room.roomId);
                      return (
                        <label key={room.roomId} className={styles.roomCheckField}>
                          <input
                            type="checkbox"
                            checked={selected}
                            onChange={(event) => toggleChatRoomDraft(room.roomId, event.target.checked)}
                          />
                          <span>
                            <strong>{room.title || room.roomId}</strong>
                            <small>{room.mode || "-"} · {room.participantCount} members · {formatTimestamp(room.updatedAt, lang)}</small>
                          </span>
                        </label>
                      );
                    })}
                  </div>
                ) : (
                  <p className={styles.emptyText}>{copy.noChatRooms}</p>
                )}
                <div className={styles.editorActions}>
                  <button
                    type="button"
                    className={styles.secondaryButton}
                    disabled={!chatRoomDirty || updateChatRoomsMutation.isPending}
                    onClick={() => setChatRoomDraft(chatRoomDraftFromWorkspace(workspace, selectedAgent))}
                  >
                    {copy.resetConfig}
                  </button>
                  <button
                    type="button"
                    className={styles.primaryButton}
                    disabled={!canSaveChatRooms || updateChatRoomsMutation.isPending}
                    onClick={saveChatRoomMembership}
                  >
                    {updateChatRoomsMutation.isPending ? copy.savingChatRooms : copy.saveChatRooms}
                  </button>
                </div>
              </section>

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
                        <strong>{referenceLabel(reference, lang)}</strong>
                        <span>{reference.sourceLabel}</span>
                        <small>{[reference.mode, reference.field].filter(Boolean).join(" / ") || reference.sourceId}</small>
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
                    disabled={!runtimePolicyDirty || updateRuntimePolicyMutation.isPending}
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
                    disabled={!canSaveRuntimePolicy || updateRuntimePolicyMutation.isPending}
                    onClick={saveRuntimePolicy}
                  >
                    {updateRuntimePolicyMutation.isPending ? copy.savingRuntimePolicy : copy.saveRuntimePolicy}
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
