import {
  type AgentConfigWorkspace,
  type AgentLlmBindings,
  type AgentModelChoice,
  type ToolBundle,
} from "../../api/types";

export type AgentCreateDraft = {
  displayName: string;
  llmBindings: AgentLlmBindings;
  primaryMode: string;
  roleKey: string;
  promptTemplateId: string;
  personaSummary: string;
  taskMission: string;
  selectedToolBundleIds: string[];
  allowedTools: string;
  /** Empty = use role/default avatar; otherwise workspace/avatars/... library path. */
  avatarImagePath: string;
};

export type AgentModelProbeStatus = "idle" | "probing" | "ok" | "fail";

export type AgentModelProbeResult = {
  status: AgentModelProbeStatus;
  message: string;
  checkedAt: string;
};

export type AgentCreatePanelModelChoice = {
  key: string;
  modelId: string;
  label: string;
  modelLabel: string;
  providerId: string;
  providerLabel: string;
  providerKind: string;
  /**
   * Credential-level readiness from config projection (API key present when required).
   * Real connectivity is tracked separately via probeStatus.
   */
  available: boolean;
  unavailableReason: string;
  /** True only when credentials look ready and a live probe succeeded. */
  probeUsable: boolean;
  probeStatus: AgentModelProbeStatus;
  probeMessage: string;
};

export type AgentCreatePanelProviderChoice = {
  id: string;
  label: string;
  providerLabel: string;
  providerKind: string;
  availableCount: number;
  totalCount: number;
  available: boolean;
};

export type AgentCreateSelectOption = {
  value: string;
  label: string;
};

export type AgentCreatePreset = {
  id: "recommended" | "coding" | "research";
  label: string;
  description: string;
  draft: AgentCreateDraft;
};

const DEFAULT_SESSION_AGENT_ALLOWED_TOOLS = [
  "grep_search_tool",
  "glob_tool",
  "get_core_context_tool",
  "get_current_goal_tool",
  "task_list_tool",
  "get_git_status_summary_tool",
  "get_recent_changes_tool",
  "conversation_log_inspect_tool",
];

export const REQUIRED_SESSION_AGENT_ALLOWED_TOOLS = [
  "exec_command",
  "write_stdin",
  "agent_tool_permission_request_tool",
];

export const REQUIRED_SESSION_AGENT_PREFERRED_TOOLS = [
  "exec_command",
  "write_stdin",
];

const DEFAULT_SESSION_AGENT_MAX_CALLS_PER_TURN = 32;

const DIALOGUE_SLOT = "dialogue";

export function sortedIds(values: string[]) {
  return Array.from(new Set(values.map((item) => String(item || "").trim()).filter(Boolean))).sort();
}

function sameStringSet(left: string[], right: string[]) {
  const leftSorted = sortedIds(left);
  const rightSorted = sortedIds(right);
  return leftSorted.length === rightSorted.length && leftSorted.every((value, index) => value === rightSorted[index]);
}

function normalizeBindings(bindings: AgentLlmBindings | null | undefined): AgentLlmBindings {
  return Object.fromEntries(
    Object.entries(bindings ?? {})
      .map(([slot, binding]) => [slot, String(binding?.modelId ?? "").trim()])
      .filter(([, modelId]) => modelId)
      .map(([slot, modelId]) => [slot, { modelId }]),
  ) as AgentLlmBindings;
}

export function dialogueModelId(bindings: AgentLlmBindings | null | undefined) {
  return String(bindings?.[DIALOGUE_SLOT]?.modelId ?? "").trim();
}

export function withDialogueModel(bindings: AgentLlmBindings, modelId: string): AgentLlmBindings {
  const next = { ...normalizeBindings(bindings) };
  const normalized = String(modelId || "").trim();
  if (normalized) {
    next[DIALOGUE_SLOT] = { modelId: normalized };
  } else {
    delete next[DIALOGUE_SLOT];
  }
  return next;
}

function agentModelLabel(model: AgentModelChoice | null | undefined) {
  return String(model?.label || model?.model || model?.modelId || "").trim() || "-";
}

/** Dialogue-eligible for the create wizard list (includes missing-key skeletons). */
export function isDialogueEligibleAgentModel(model: AgentModelChoice) {
  const text = [agentModelLabel(model), model.model, model.modelId, model.providerKind]
    .join(" ")
    .trim()
    .toLowerCase();
  if (!model.runtimeSelectable) return false;
  if (/\bimage\d*\b/.test(text) || text.includes("image2") || text.includes("gpt-image")) {
    return false;
  }
  const slot = model.slotCompatibility?.dialogue;
  if (slot && slot.allowed === false) return false;
  return true;
}

export function agentModelUnavailableReason(model: AgentModelChoice, lang: "zh" | "en" = "zh"): string {
  if (model.missingApiKey || (model.requiresApiKey && !model.apiKeyConfigured)) {
    return lang === "zh" ? "未配置 API Key" : "API key missing";
  }
  if (!model.apiKeyConfigured && model.requiresApiKey !== false) {
    // Defensive: older payloads may omit missingApiKey.
    if (model.apiKeyState === "missing" || model.apiKeyState === "unconfigured") {
      return lang === "zh" ? "未配置 API Key" : "API key missing";
    }
  }
  const availability = String(model.availability || "").toLowerCase();
  if (["missing", "missing_remote", "stale", "unavailable", "unknown"].includes(availability)) {
    return lang === "zh" ? "上游当前不可用" : "Upstream unavailable";
  }
  if (model.catalogStale || model.verificationStatus === "stale") {
    return lang === "zh" ? "模型发现已过期" : "Catalog stale";
  }
  return "";
}

export function isAgentModelAvailable(model: AgentModelChoice): boolean {
  if (!isDialogueEligibleAgentModel(model)) return false;
  if (model.missingApiKey) return false;
  if (model.requiresApiKey && !model.apiKeyConfigured) return false;
  // Local / no-credential providers report apiKeyConfigured true with requiresApiKey false.
  if (!model.apiKeyConfigured && model.requiresApiKey !== false && model.apiKeyState === "missing") {
    return false;
  }
  return true;
}

export function probeStatusLabel(status: AgentModelProbeStatus, lang: "zh" | "en" = "zh"): string {
  if (status === "probing") return lang === "zh" ? "探测中" : "probing";
  if (status === "ok") return lang === "zh" ? "探测通过" : "probe ok";
  if (status === "fail") return lang === "zh" ? "探测失败" : "probe failed";
  return lang === "zh" ? "未探测" : "not probed";
}

export function applyProbeResultsToModelChoices(
  choices: AgentCreatePanelModelChoice[],
  probes: Record<string, AgentModelProbeResult>,
  lang: "zh" | "en" = "zh",
): AgentCreatePanelModelChoice[] {
  return choices
    .map((choice) => {
      const probe = probes[choice.modelId];
      const probeStatus = probe?.status || "idle";
      const probeMessage = String(probe?.message || "").trim();
      const probeUsable = Boolean(choice.available && probeStatus === "ok");
      const baseCore = choice.modelLabel;
      const provider = String(choice.providerKind || "").trim();
      // Rebuild display label from stable fields.
      const baseLabel = [
        baseCore,
        provider && provider !== baseCore ? provider : "",
        choice.modelId.includes("/") ? choice.modelId.split("/")[1] : "",
      ].filter(Boolean).join(" · ") || choice.modelId;

      let suffix = "";
      if (!choice.available) {
        suffix = ` · ${lang === "zh" ? "不可用" : "unavailable"}${choice.unavailableReason ? `（${choice.unavailableReason}）` : ""}`;
      } else if (probeStatus === "ok") {
        suffix = ` · ${probeStatusLabel("ok", lang)}`;
      } else if (probeStatus === "fail") {
        suffix = ` · ${probeStatusLabel("fail", lang)}`;
      } else if (probeStatus === "probing") {
        suffix = ` · ${probeStatusLabel("probing", lang)}`;
      } else {
        suffix = ` · ${probeStatusLabel("idle", lang)}`;
      }

      return {
        ...choice,
        label: `${baseLabel}${suffix}`,
        probeStatus,
        probeMessage,
        probeUsable,
        // Keep option selectable when credential-ready so user can probe it;
        // create/next gates use probeUsable separately.
        available: choice.available,
      };
    })
    .sort((left, right) => {
      if (left.probeUsable !== right.probeUsable) return left.probeUsable ? -1 : 1;
      if (left.available !== right.available) return left.available ? -1 : 1;
      return left.label.localeCompare(right.label) || left.modelId.localeCompare(right.modelId);
    });
}

export function buildAgentModelChoices(
  models: AgentModelChoice[],
  lang: "zh" | "en" = "zh",
  probes: Record<string, AgentModelProbeResult> = {},
): AgentCreatePanelModelChoice[] {
  const base = models
    .filter(isDialogueEligibleAgentModel)
    .map((model) => {
      const label = agentModelLabel(model);
      const provider = String(model.providerKind || "").trim();
      const modelName = String(model.model || "").trim();
      const available = isAgentModelAvailable(model);
      const unavailableReason = available ? "" : agentModelUnavailableReason(model, lang);
      const baseLabel = [label, provider && provider !== label ? provider : "", modelName && modelName !== label ? modelName : ""]
        .filter(Boolean)
        .join(" · ") || "-";
      return {
        key: model.modelId,
        modelId: model.modelId,
        label: baseLabel,
        modelLabel: label,
        providerId: model.providerId,
        providerLabel: model.providerLabel,
        providerKind: model.providerKind,
        available,
        unavailableReason,
        probeUsable: false,
        probeStatus: "idle" as AgentModelProbeStatus,
        probeMessage: "",
      };
    });
  return applyProbeResultsToModelChoices(base, probes, lang);
}

export function buildAgentProviderChoices(
  models: AgentCreatePanelModelChoice[],
  lang: "zh" | "en" = "zh",
): AgentCreatePanelProviderChoice[] {
  const groups = new Map<string, {
    id: string;
    providerLabel: string;
    providerKind: string;
    sortLabel: string;
    availableCount: number;
    probeUsableCount: number;
    totalCount: number;
  }>();
  for (const model of models) {
    const existing = groups.get(model.providerId);
    if (existing) {
      existing.totalCount += 1;
      if (model.available) existing.availableCount += 1;
      if (model.probeUsable) existing.probeUsableCount += 1;
      continue;
    }
    const providerLabel = model.providerLabel || model.providerKind || model.providerId;
    const sortLabel = [
      providerLabel,
      model.providerKind && model.providerKind !== providerLabel ? model.providerKind : "",
      model.providerId !== providerLabel ? model.providerId : "",
    ].filter(Boolean).join(" · ");
    groups.set(model.providerId, {
      id: model.providerId,
      providerLabel,
      providerKind: model.providerKind,
      sortLabel,
      availableCount: model.available ? 1 : 0,
      probeUsableCount: model.probeUsable ? 1 : 0,
      totalCount: 1,
    });
  }
  return Array.from(groups.values())
    .map((group) => {
      const available = group.availableCount > 0;
      let statusText: string;
      if (group.probeUsableCount > 0) {
        statusText = lang === "zh"
          ? `${group.probeUsableCount} 探测通过`
          : `${group.probeUsableCount} probe ok`;
      } else if (available) {
        statusText = lang === "zh"
          ? `${group.availableCount} 已配密钥 · 未探测`
          : `${group.availableCount} keyed · not probed`;
      } else {
        statusText = lang === "zh" ? "0 可用 · 不可用" : "0 available · unavailable";
      }
      return {
        id: group.id,
        label: `${group.sortLabel} · ${statusText}`,
        providerLabel: group.providerLabel,
        providerKind: group.providerKind,
        availableCount: group.probeUsableCount > 0 ? group.probeUsableCount : group.availableCount,
        totalCount: group.totalCount,
        available,
      };
    })
    .sort((left, right) => {
      if (left.available !== right.available) return left.available ? -1 : 1;
      return left.label.localeCompare(right.label) || left.id.localeCompare(right.id);
    });
}

export function firstAvailableModelId(models: AgentCreatePanelModelChoice[], providerId = ""): string {
  const scoped = providerId
    ? models.filter((model) => model.providerId === providerId)
    : models;
  return scoped.find((model) => model.probeUsable)?.modelId
    || scoped.find((model) => model.available)?.modelId
    || "";
}

export function credentialReadyModelIds(models: AgentCreatePanelModelChoice[]): string[] {
  return models.filter((model) => model.available).map((model) => model.modelId);
}

export function isWorkSessionCreateDraft(draft: AgentCreateDraft) {
  const primaryMode = String(draft.primaryMode || "").trim();
  return primaryMode === "" || primaryMode === "chat";
}

function defaultCreateToolBundleIds(workSession: boolean, bundles: ToolBundle[]) {
  const available = new Set(bundles.map((bundle) => bundle.bundleId));
  const preferred = workSession ? ["core"] : ["core", "research", "collaboration"];
  const selected = preferred.filter((bundleId) => available.has(bundleId));
  return selected.length ? selected : bundles[0]?.bundleId ? [bundles[0].bundleId] : [];
}

function selectAvailableToolBundles(bundles: ToolBundle[], preferred: string[], fallback: string[]) {
  const available = new Set(bundles.map((bundle) => bundle.bundleId));
  const selected = preferred.filter((bundleId) => available.has(bundleId));
  return selected.length ? selected : fallback;
}

export function toolBundleSelectionToPolicy(bundleIds: string[], bundles: ToolBundle[]) {
  const selectedIds = new Set(sortedIds(bundleIds));
  const selectedBundles = bundles.filter((bundle) => selectedIds.has(bundle.bundleId));
  const allowed = new Set<string>();
  const preferred = new Set<string>();
  for (const bundle of selectedBundles) {
    for (const tool of bundle.toolNames ?? []) allowed.add(tool);
    for (const tool of bundle.preferredToolNames ?? []) {
      if ((bundle.toolNames ?? []).includes(tool)) preferred.add(tool);
    }
  }
  return {
    selectedBundles,
    allowedTools: sortedIds(Array.from(allowed)),
    preferredTools: sortedIds(Array.from(preferred).filter((tool) => allowed.has(tool))),
  };
}

function expertiseFromDraft(value: string) {
  return sortedIds(String(value || "").split(/[,，;；\n]+/).map((item) => item.trim()).filter(Boolean));
}

export function createDraftFromWorkspace(
  workspace: Pick<AgentConfigWorkspace, "agentModelChoices" | "promptTemplates"> | undefined,
  bundles: ToolBundle[] = [],
  lang: "zh" | "en" = "zh",
): AgentCreateDraft {
  const choices = buildAgentModelChoices(workspace?.agentModelChoices ?? [], lang);
  const firstModel = firstAvailableModelId(choices)
    || choices[0]?.modelId
    || workspace?.agentModelChoices?.[0]?.modelId
    || "";
  const firstPrompt = workspace?.promptTemplates?.find((item) => item.promptTemplateId === "prompt-chat-default")
    ?? workspace?.promptTemplates?.find((item) => item.category === "chat")
    ?? workspace?.promptTemplates?.[0];
  return {
    displayName: lang === "zh" ? "新会话 Agent" : "New chat Agent",
    llmBindings: firstModel ? { [DIALOGUE_SLOT]: { modelId: firstModel } } : {},
    primaryMode: "chat",
    roleKey: "",
    promptTemplateId: firstPrompt?.promptTemplateId || firstPrompt?.templateId || "prompt-chat-default",
    personaSummary: "",
    taskMission: "",
    selectedToolBundleIds: defaultCreateToolBundleIds(true, bundles),
    allowedTools: DEFAULT_SESSION_AGENT_ALLOWED_TOOLS.join(", "),
    avatarImagePath: "",
  };
}

export function normalizeCreateDraftForWorkspace(
  draft: AgentCreateDraft,
  workspace: Pick<AgentConfigWorkspace, "agentModelChoices" | "promptTemplates"> | undefined,
  bundles: ToolBundle[] = [],
  lang: "zh" | "en" = "zh",
) {
  if (!workspace) return draft;
  const defaults = createDraftFromWorkspace(workspace, bundles, lang);
  const choices = buildAgentModelChoices(workspace.agentModelChoices ?? [], lang);
  const availableIds = new Set(choices.filter((choice) => choice.available).map((choice) => choice.modelId));
  const modelIds = new Set(choices.map((choice) => choice.modelId));
  const promptIds = new Set((workspace.promptTemplates ?? []).map((template) => template.promptTemplateId || template.templateId || ""));
  const currentModel = dialogueModelId(draft.llmBindings);
  const defaultModel = dialogueModelId(defaults.llmBindings);
  let nextModel = currentModel;
  if (modelIds.size === 0) {
    nextModel = currentModel;
  } else if (!modelIds.has(currentModel)) {
    nextModel = defaultModel;
  } else if (availableIds.size > 0 && !availableIds.has(currentModel)) {
    nextModel = defaultModel || firstAvailableModelId(choices);
  }
  const promptTemplateId = !draft.promptTemplateId || promptIds.size === 0 || promptIds.has(draft.promptTemplateId)
    ? draft.promptTemplateId || defaults.promptTemplateId
    : defaults.promptTemplateId;
  return {
    ...draft,
    displayName: draft.displayName || defaults.displayName,
    llmBindings: withDialogueModel(draft.llmBindings, nextModel || defaultModel),
    promptTemplateId,
  };
}

export function createAgentPresets(
  workspace: Pick<AgentConfigWorkspace, "agentModelChoices" | "promptTemplates"> | undefined,
  bundles: ToolBundle[],
  lang: "zh" | "en",
): AgentCreatePreset[] {
  const base = createDraftFromWorkspace(workspace, bundles, lang);
  const prompts = workspace?.promptTemplates ?? [];
  const promptId = (category: string, preferredIds: string[]) => {
    const exact = prompts.find((prompt) => preferredIds.includes(prompt.promptTemplateId || prompt.templateId || ""));
    const categoryMatch = prompts.find((prompt) => prompt.category === category);
    return exact?.promptTemplateId || exact?.templateId || categoryMatch?.promptTemplateId || categoryMatch?.templateId || base.promptTemplateId;
  };
  const workDefaults = defaultCreateToolBundleIds(true, bundles);
  const teamDefaults = defaultCreateToolBundleIds(false, bundles);
  const copy = lang === "zh" ? {
    recommendedLabel: "推荐配置", recommendedDescription: "通用会话、默认提示词与核心工具", recommendedName: "新会话 Agent",
    codingLabel: "代码开发", codingDescription: "面向实现、调试和测试的工作配置", codingName: "代码开发 Agent",
    researchLabel: "研究协作", researchDescription: "研究提示词、检索与协作工具", researchName: "研究协作 Agent",
    researchPersona: "严谨、证据优先，能够区分事实、推断和待验证结论。",
    researchMission: "完成研究、资料核验与协作交付，并明确证据来源和下一步。",
  } : {
    recommendedLabel: "Recommended", recommendedDescription: "General chat, default prompt, and core tools", recommendedName: "New chat Agent",
    codingLabel: "Code development", codingDescription: "A work setup for implementation, debugging, and testing", codingName: "Code development Agent",
    researchLabel: "Research collaboration", researchDescription: "Research prompt with search and collaboration tools", researchName: "Research collaboration Agent",
    researchPersona: "Rigorous and evidence-first, clearly separating facts, inference, and open questions.",
    researchMission: "Deliver research, source verification, and collaboration outputs with evidence and explicit next steps.",
  };
  return [
    { id: "recommended", label: copy.recommendedLabel, description: copy.recommendedDescription, draft: { ...base, displayName: copy.recommendedName } },
    {
      id: "coding", label: copy.codingLabel, description: copy.codingDescription,
      draft: { ...base, displayName: copy.codingName, promptTemplateId: promptId("chat", ["prompt-chat-operation-default", "prompt-chat-default"]), selectedToolBundleIds: selectAvailableToolBundles(bundles, ["core", "coding", "development"], workDefaults) },
    },
    {
      id: "research", label: copy.researchLabel, description: copy.researchDescription,
      draft: { ...base, displayName: copy.researchName, primaryMode: "research", roleKey: "research_assistant", promptTemplateId: promptId("research", ["prompt-research-default"]), personaSummary: copy.researchPersona, taskMission: copy.researchMission, selectedToolBundleIds: selectAvailableToolBundles(bundles, ["core", "research", "collaboration"], teamDefaults) },
    },
  ];
}

export function toolBundleIdsForModeChange(draft: AgentCreateDraft, nextPrimaryMode: string, bundles: ToolBundle[]) {
  const currentDefaults = defaultCreateToolBundleIds(isWorkSessionCreateDraft(draft), bundles);
  const hasCustomSelection = draft.selectedToolBundleIds.length > 0 && !sameStringSet(draft.selectedToolBundleIds, currentDefaults);
  if (hasCustomSelection) return draft.selectedToolBundleIds;
  return defaultCreateToolBundleIds(!String(nextPrimaryMode || "").trim() || nextPrimaryMode === "chat", bundles);
}

export function createToolBundleSummary(
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
  return {
    ...policy,
    allowedTools,
    preferredTools,
    bundleLabels,
    highRiskCount,
    explicitAllowCount,
    label: bundleLabels.length ? bundleLabels.join(" / ") : requiredAllowedTools.length ? (lang === "zh" ? "会话推荐默认" : "Recommended session default") : (lang === "zh" ? "未选择工具包" : "No package selected"),
    meta: [
      lang === "zh" ? `${allowedTools.length} 个允许工具` : `${allowedTools.length} allowed tools`,
      lang === "zh" ? `${preferredTools.length} 个优先工具` : `${preferredTools.length} preferred tools`,
      highRiskCount ? (lang === "zh" ? `${highRiskCount} 个高风险` : `${highRiskCount} high risk`) : "",
      explicitAllowCount ? (lang === "zh" ? `${explicitAllowCount} 个需显式授权` : `${explicitAllowCount} explicit allow`) : "",
    ].filter(Boolean).join(" · "),
  };
}

export function createDraftReady(
  draft: AgentCreateDraft,
  bundles: ToolBundle[] = [],
  availableModelIds?: Set<string> | string[],
) {
  const workSession = isWorkSessionCreateDraft(draft);
  const selectedPolicy = toolBundleSelectionToPolicy(draft.selectedToolBundleIds, bundles);
  const fallbackAllowedTools = bundles.length ? [] : expertiseFromDraft(draft.allowedTools);
  const configuredToolCount = selectedPolicy.allowedTools.length || fallbackAllowedTools.length;
  const hasToolPolicyChoice = selectedPolicy.selectedBundles.length > 0 || fallbackAllowedTools.length > 0;
  const modelId = dialogueModelId(draft.llmBindings);
  const availableSet = availableModelIds
    ? (availableModelIds instanceof Set ? availableModelIds : new Set(availableModelIds))
    : null;
  const modelOk = Boolean(modelId) && (availableSet ? availableSet.has(modelId) : true);
  return Boolean(
    draft.displayName.trim()
    && modelOk
    && draft.primaryMode.trim()
    && (workSession || draft.roleKey.trim())
    && draft.promptTemplateId.trim()
    && (workSession || draft.personaSummary.trim())
    && (workSession || draft.taskMission.trim())
    && (workSession ? hasToolPolicyChoice : configuredToolCount > 0),
  );
}

export function toolBundleMeta(bundle: ToolBundle, lang: "zh" | "en") {
  const parts = [
    lang === "zh" ? `${bundle.toolCount} 个工具` : `${bundle.toolCount} tools`,
    lang === "zh" ? `${bundle.preferredToolCount} 个优先` : `${bundle.preferredToolCount} preferred`,
  ];
  if (bundle.highRiskToolCount > 0) parts.push(lang === "zh" ? `${bundle.highRiskToolCount} 个高风险` : `${bundle.highRiskToolCount} high risk`);
  if (bundle.explicitAllowToolCount > 0) parts.push(lang === "zh" ? `${bundle.explicitAllowToolCount} 个需显式允许` : `${bundle.explicitAllowToolCount} explicit allow`);
  return parts.join(" · ");
}

export function createAgentPayload(draft: AgentCreateDraft, bundles: ToolBundle[]) {
  const workSession = isWorkSessionCreateDraft(draft);
  const roleKey = workSession ? "" : draft.roleKey.trim();
  const selectedToolPolicy = toolBundleSelectionToPolicy(draft.selectedToolBundleIds, bundles);
  const fallbackAllowedTools = bundles.length ? [] : expertiseFromDraft(draft.allowedTools);
  const selectedAllowedTools = selectedToolPolicy.allowedTools.length ? selectedToolPolicy.allowedTools : fallbackAllowedTools;
  const requiredAllowedTools = workSession ? REQUIRED_SESSION_AGENT_ALLOWED_TOOLS : [];
  const allowedTools = sortedIds([...selectedAllowedTools, ...requiredAllowedTools]);
  const selectedPreferredTools = selectedToolPolicy.preferredTools.length
    ? selectedToolPolicy.preferredTools
    : fallbackAllowedTools.includes("agent_message_tool") ? ["agent_message_tool"] : [];
  const requiredPreferredTools = workSession ? REQUIRED_SESSION_AGENT_PREFERRED_TOOLS : [];
  const preferredTools = sortedIds(
    [...selectedPreferredTools, ...requiredPreferredTools].filter((tool) => allowedTools.includes(tool)),
  );
  const personaProfile = workSession ? {} : {
    personality: draft.personaSummary.trim(),
    communicationStyle: "按角色边界回应；先给结论，再说明依据和需要交接的事项。",
    background: `由 Agent 中心创建，用于 ${draft.displayName.trim()}。`,
    collaborationPreference: "优先保持短反馈和清晰交接；超出任务使命时主动说明边界。",
    identityNotes: "创建时已完成最小建档；可在人物档案中继续细化。",
    expertise: roleKey ? [roleKey] : [],
  };
  const taskProfile = workSession ? {} : {
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
  const avatarImagePath = String(draft.avatarImagePath || "").trim();
  return {
    displayName: draft.displayName.trim(),
    llmBindings: normalizeBindings(draft.llmBindings),
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
      maxCallsPerTurn: workSession ? DEFAULT_SESSION_AGENT_MAX_CALLS_PER_TURN : 8,
    },
    metadata: {
      creationChannel: "agent_center",
      onboardingStatus: "complete",
      onboardingMissing: [],
      creationToolBundleIds: sortedIds(draft.selectedToolBundleIds),
    },
    ...(avatarImagePath ? { avatarImagePath } : {}),
  };
}
