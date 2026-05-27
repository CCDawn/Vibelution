import type { AgentInstance, ConfigDraftMeta, ConfigModelOption, ConfigModelPresetOption, ConfigProfileCard, ResearchAgentConfig } from "../api/types";

export type PublicConfigShape = Record<string, unknown>;

export type ModelPresetGroupId = "official" | "relay" | "openai_compatible" | "local";

export type ModelPresetGroup = {
  id: ModelPresetGroupId;
  label: string;
  presets: ConfigModelPresetOption[];
};

export type ModelPresetGroupLabels = Record<ModelPresetGroupId, string>;

export type ProviderKindOption = {
  value: string;
  label: string;
};

export type ConfigEditorSyncStateInput = {
  editorText: string;
  formattedConfigText: string;
  configLoaded: boolean;
  hasUnsavedConfigChanges: boolean;
  hasPendingSecretChanges: boolean;
  busy: boolean;
};

export type ConfigEditorSyncState = {
  hasEditorChanges: boolean;
  hasPendingApply: boolean;
  structuredActionsDisabled: boolean;
  canSaveConfig: boolean;
  canCheckCurrentChanges: boolean;
  canRestoreEditorText: boolean;
};

export type ConfigLeaveGuardInput = {
  hasPendingApply: boolean;
  busy: boolean;
  currentPathname: string;
  nextPathname: string;
};

export type ProfileDisplayState = {
  selectedModelId: string;
  selectedModelLabel: string;
  providerKind: string;
  model: string;
  baseUrl: string;
  apiKeyEnv: string;
  apiKeyState: string;
  apiKeySource: string;
  selectionDirty: boolean;
};

export type ConfigProfileModeGroupId = "chat" | "support" | "subagents" | "evolution" | "research" | "other";

export type ConfigProfileModeGroupLabels = Record<ConfigProfileModeGroupId, string>;

export type ConfigProfileModeGroup = {
  id: ConfigProfileModeGroupId;
  label: string;
  profiles: ConfigProfileCard[];
};

export type ModelEditability = {
  editable: boolean;
  deletable: boolean;
};

export function resolveResearchAgentInstance(
  researchAgent: Pick<ResearchAgentConfig, "key" | "agentId" | "agentInstanceId">,
  agentInstances: AgentInstance[],
): AgentInstance | null {
  const linkedAgentId = researchAgent.agentId || researchAgent.agentInstanceId || "";
  const byId = agentInstances.find((agent) => agent.agentId === linkedAgentId);
  if (byId) {
    return byId;
  }
  return agentInstances.find((agent) => agent.metadata?.researchAgentKey === researchAgent.key) ?? null;
}

export function supervisedAgentRole(agent: Pick<AgentInstance, "metadata">): string {
  const value = agent.metadata?.supervisedRole;
  return typeof value === "string" ? value.trim() : "";
}

export function supervisedAgentRoleLabel(agent: AgentInstance): string {
  const value = agent.metadata?.supervisedRoleLabel;
  return typeof value === "string" && value.trim() ? value.trim() : supervisedAgentRole(agent);
}

export function listSupervisedAgentInstances(agentInstances: AgentInstance[]): AgentInstance[] {
  const roleOrder = new Map([
    ["baseline", 0],
    ["candidate", 1],
    ["reviewer", 2],
    ["auditor", 3],
    ["judge", 4],
  ]);
  return agentInstances
    .filter((agent) => supervisedAgentRole(agent))
    .slice()
    .sort((left, right) => {
      const leftOrder = roleOrder.get(supervisedAgentRole(left)) ?? 99;
      const rightOrder = roleOrder.get(supervisedAgentRole(right)) ?? 99;
      if (leftOrder !== rightOrder) {
        return leftOrder - rightOrder;
      }
      return supervisedAgentRoleLabel(left).localeCompare(supervisedAgentRoleLabel(right));
    });
}

export type AvatarCropGeometry = {
  imageWidth: number;
  imageHeight: number;
  frameSize: number;
  zoom: number;
  offsetX: number;
  offsetY: number;
};

export type AvatarCropSourceRect = {
  sx: number;
  sy: number;
  size: number;
};

export function clonePublicConfig<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

export function asRecord(value: unknown): Record<string, unknown> {
  return isRecord(value) ? value : {};
}

export function getString(value: unknown): string {
  return typeof value === "string" ? value : value == null ? "" : String(value);
}

export function clampAvatarCropOffset(geometry: AvatarCropGeometry): { offsetX: number; offsetY: number } {
  const scale = Math.max(geometry.frameSize / Math.min(geometry.imageWidth, geometry.imageHeight), 0.0001) * Math.max(geometry.zoom, 1);
  const renderedWidth = geometry.imageWidth * scale;
  const renderedHeight = geometry.imageHeight * scale;
  const maxX = Math.max(0, (renderedWidth - geometry.frameSize) / 2);
  const maxY = Math.max(0, (renderedHeight - geometry.frameSize) / 2);
  return {
    offsetX: maxX === 0 ? 0 : Math.min(maxX, Math.max(-maxX, geometry.offsetX)),
    offsetY: maxY === 0 ? 0 : Math.min(maxY, Math.max(-maxY, geometry.offsetY)),
  };
}

export function avatarCropSourceRect(geometry: AvatarCropGeometry): AvatarCropSourceRect {
  const clamped = clampAvatarCropOffset(geometry);
  const scale = Math.max(geometry.frameSize / Math.min(geometry.imageWidth, geometry.imageHeight), 0.0001) * Math.max(geometry.zoom, 1);
  const sourceSize = geometry.frameSize / scale;
  const sx = (geometry.imageWidth - sourceSize) / 2 - clamped.offsetX / scale;
  const sy = (geometry.imageHeight - sourceSize) / 2 - clamped.offsetY / scale;
  return {
    sx: Math.max(0, Math.min(geometry.imageWidth - sourceSize, sx)),
    sy: Math.max(0, Math.min(geometry.imageHeight - sourceSize, sy)),
    size: sourceSize,
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function ensureRecord(target: Record<string, unknown>, key: string): Record<string, unknown> {
  const current = target[key];
  if (isRecord(current)) {
    return current;
  }
  const created: Record<string, unknown> = {};
  target[key] = created;
  return created;
}

export function collectModelDetailKeys(options: ConfigModelOption[]): string[] {
  const keys = new Set<string>();
  for (const option of options) {
    for (const key of Object.keys(asRecord(option.details))) {
      keys.add(key);
    }
  }
  return Array.from(keys);
}

export function hasPendingSecretChanges(draftMeta: ConfigDraftMeta): boolean {
  return Boolean(Object.keys(draftMeta.pending_api_keys).length || draftMeta.pending_cleared_api_keys.length);
}

export function deriveConfigEditorSyncState(input: ConfigEditorSyncStateInput): ConfigEditorSyncState {
  const hasEditorChanges = input.editorText !== input.formattedConfigText;
  const hasPendingApply = input.hasUnsavedConfigChanges || input.hasPendingSecretChanges || hasEditorChanges;
  return {
    hasEditorChanges,
    hasPendingApply,
    structuredActionsDisabled: !input.configLoaded || hasEditorChanges || input.busy,
    canSaveConfig: input.configLoaded && hasPendingApply && !hasEditorChanges && !input.busy,
    canCheckCurrentChanges: input.configLoaded && !input.busy,
    canRestoreEditorText: input.configLoaded && hasEditorChanges && !input.busy,
  };
}

export function shouldBlockConfigLeave(input: ConfigLeaveGuardInput): boolean {
  return input.hasPendingApply && !input.busy && input.currentPathname === "/config" && input.nextPathname !== "/config";
}

export function resolveProfileDisplayState(
  profile: ConfigProfileCard,
  selectedModelId: string,
  selectedModel: ConfigModelOption | null,
  isEditingProfile: boolean,
): ProfileDisplayState {
  const selectionDirty = Boolean(isEditingProfile && selectedModelId && selectedModelId !== profile.selectedModelId);
  const resolvedSelectedModel = selectionDirty ? selectedModel : null;
  const providerKind = selectionDirty ? resolvedSelectedModel?.provider_kind ?? profile.providerKind : profile.providerKind;
  const model = selectionDirty ? resolvedSelectedModel?.model ?? profile.model : profile.model;
  const baseUrl = selectionDirty
    ? getString(asRecord(resolvedSelectedModel?.provider).base_url) || profile.baseUrl
    : profile.baseUrl;
  const apiKeyEnv = selectionDirty ? resolvedSelectedModel?.api_key_env ?? profile.apiKeyEnv : profile.apiKeyEnv;
  const apiKeyState = selectionDirty ? resolvedSelectedModel?.api_key_state ?? profile.apiKeyState : profile.apiKeyState;
  const apiKeySource = selectionDirty ? apiKeyEnv || "-" : profile.apiKeySource || "-";
  return {
    selectedModelId,
    selectedModelLabel: selectionDirty ? selectedModel?.label ?? profile.selectedModelLabel : profile.selectedModelLabel,
    providerKind,
    model,
    baseUrl,
    apiKeyEnv,
    apiKeyState,
    apiKeySource,
    selectionDirty,
  };
}

export function resolveModelEditability(option: ConfigModelOption): ModelEditability {
  return option.source === "model_library"
    ? { editable: true, deletable: true }
    : { editable: false, deletable: false };
}

export function profileModeGroupId(profileId: string): ConfigProfileModeGroupId {
  const normalized = profileId.trim();
  if (normalized === "primary") {
    return "chat";
  }
  if (normalized === "mental_model" || normalized === "compression") {
    return "support";
  }
  if (normalized === "subagent_worker" || normalized === "subagent_explorer") {
    return "subagents";
  }
  if (normalized === "supervised_baseline" || normalized === "supervised_candidate") {
    return "evolution";
  }
  if (normalized.startsWith("research_")) {
    return "research";
  }
  return "other";
}

export function groupConfigProfileCards(
  profiles: ConfigProfileCard[],
  labels: ConfigProfileModeGroupLabels,
): ConfigProfileModeGroup[] {
  const groups: ConfigProfileModeGroup[] = [
    { id: "chat", label: labels.chat, profiles: [] },
    { id: "support", label: labels.support, profiles: [] },
    { id: "subagents", label: labels.subagents, profiles: [] },
    { id: "evolution", label: labels.evolution, profiles: [] },
    { id: "research", label: labels.research, profiles: [] },
    { id: "other", label: labels.other, profiles: [] },
  ];
  const groupById = new Map(groups.map((group) => [group.id, group]));
  for (const profile of profiles) {
    groupById.get(profileModeGroupId(profile.profileId))?.profiles.push(profile);
  }
  return groups.filter((group) => group.profiles.length);
}

export function presetCategory(preset: ConfigModelPresetOption): ModelPresetGroupId {
  const explicit = getString(preset.category).trim().toLowerCase();
  if (explicit === "relay" || explicit === "openai_compatible" || explicit === "local" || explicit === "official") {
    return explicit;
  }
  const provider = asRecord(preset.provider);
  const kind = getString(provider.kind).trim().toLowerCase();
  const baseUrl = getString(provider.base_url).trim().toLowerCase();
  if (kind === "relay") {
    return "relay";
  }
  if (kind === "openai_compatible") {
    return "openai_compatible";
  }
  if (kind === "local" || kind === "ollama" || baseUrl.includes("localhost") || baseUrl.includes("127.0.0.1")) {
    return "local";
  }
  return "official";
}

export function groupModelPresets(
  presets: ConfigModelPresetOption[],
  labels: ModelPresetGroupLabels,
): ModelPresetGroup[] {
  const groups: ModelPresetGroup[] = [
    { id: "official", label: labels.official, presets: [] },
    { id: "relay", label: labels.relay, presets: [] },
    { id: "openai_compatible", label: labels.openai_compatible, presets: [] },
    { id: "local", label: labels.local, presets: [] },
  ];
  const groupById = new Map(groups.map((group) => [group.id, group]));
  for (const preset of presets) {
    groupById.get(presetCategory(preset))?.presets.push(preset);
  }
  return groups.filter((group) => group.presets.length);
}

export function defaultModelApiKeyEnv(modelId: string): string {
  const token = modelId
    .toUpperCase()
    .replace(/[^A-Z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  return token ? `VIBELUTION_LLM_${token}_API_KEY` : "VIBELUTION_LLM_MODEL_API_KEY";
}

export function modelLibraryIdFromParts(label: string, model: string): string {
  const raw = `${label}-${model}`.trim();
  const token = raw
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  return token || "custom_model";
}

export function uniqueModelLibraryId(baseId: string, existingIds: Iterable<string>): string {
  const existing = new Set(Array.from(existingIds, (value) => value.trim()).filter(Boolean));
  const base = modelLibraryIdFromParts(baseId, "") || "custom_model";
  if (!existing.has(base)) {
    return base;
  }
  let index = 2;
  while (existing.has(`${base}_${index}`)) {
    index += 1;
  }
  return `${base}_${index}`;
}

export const PROVIDER_KIND_OPTIONS: ProviderKindOption[] = [
  { value: "relay", label: "Relay Responses" },
  { value: "openai_compatible", label: "OpenAI 兼容 API" },
  { value: "openai", label: "OpenAI" },
  { value: "deepseek", label: "DeepSeek" },
  { value: "minimax", label: "MiniMax" },
  { value: "xiaomi", label: "Xiaomi MiMo" },
  { value: "anthropic", label: "Anthropic" },
  { value: "google", label: "Google" },
  { value: "aliyun", label: "DashScope" },
  { value: "siliconflow", label: "SiliconFlow" },
  { value: "local", label: "Local" },
];

export function applyModelOptionToProfileDraft(
  config: PublicConfigShape,
  profileId: string,
  option: ConfigModelOption,
  modelDetailKeys: string[],
): void {
  const llm = ensureRecord(config, "llm");
  const profiles = ensureRecord(llm, "profiles");
  const profile = ensureRecord(profiles, profileId);

  delete profile.overrides;
  delete profile.provider_id;
  for (const key of modelDetailKeys) {
    delete profile[key];
  }

  if (option.source === "model_library") {
    profile.model_ref = option.model_id;
    profile.overrides = {};
    delete profile.provider;
    delete profile.model;
    delete profile.api_key_env;
    return;
  }

  delete profile.model_ref;
  profile.provider = clonePublicConfig(asRecord(option.provider));
  profile.model = option.model;
  if (option.api_key_env) {
    profile.api_key_env = option.api_key_env;
  } else {
    delete profile.api_key_env;
  }
  for (const [key, value] of Object.entries(asRecord(option.details))) {
    profile[key] = clonePublicConfig(value);
  }
}
