import type {
  AgentInstance,
  ConfigDraftMeta,
  ConfigModelOption,
  ConfigModelPresetOption,
  ConfigProviderPresetOption,
  ResearchAgentConfig,
} from "../api/types";

export type PublicConfigShape = Record<string, unknown>;

export type ModelPresetGroupId = "official" | "relay" | "openai_compatible" | "local";

export type ModelPresetGroup = {
  id: ModelPresetGroupId;
  label: string;
  presets: ConfigModelPresetOption[];
};

export type ProviderVendorGroup = {
  id: string;
  label: string;
  templates: ConfigProviderPresetOption[];
};

export type ModelPresetGroupLabels = Record<ModelPresetGroupId, string>;

export type ProviderKindOption = {
  value: string;
  label: string;
};

export type SelectOption = {
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

export type ConfigSectionExpansionState = {
  expanded: boolean;
};

export type ConfigLeaveGuardInput = {
  hasPendingApply: boolean;
  busy: boolean;
  currentPathname: string;
  nextPathname: string;
};

export type ConfigEditableSectionPath = {
  path: string;
};

export type ConfigInvalidationDomain = "config" | "runtime" | "sessions" | "reset" | "evolution";

export type ModelEditability = {
  editable: boolean;
  deletable: boolean;
};

export type ConfigApplyPayload = {
  publicConfig: PublicConfigShape;
  draftMeta: ConfigDraftMeta;
  baseHash: string;
  baseConfig: PublicConfigShape;
};

export type BuildConfigApplyPayloadInput = {
  draftConfig: PublicConfigShape | null;
  draftMeta: ConfigDraftMeta;
  baseHash: string;
  baseConfig: PublicConfigShape | null;
  editorText: string;
  hasEditorChanges: boolean;
  editorSections: ConfigEditableSectionPath[];
  loadFailedMessage: string;
};

export type ModelScenarioId = "chat" | "relay" | "image" | "local" | "manual";

export const MODEL_SCENARIOS: ModelScenarioId[] = ["chat", "relay", "image", "local", "manual"];

export type ModelCenterAccount = {
  id: string;
  providerKind: string;
  baseUrl: string;
  keyEnv: string;
  modelIds: string[];
  modelCount: number;
  configuredCount: number;
  missingCount: number;
  pendingCount: number;
  clearPendingCount: number;
  apiKeyState: string;
};

export type ModelCenterSummary = {
  accounts: ModelCenterAccount[];
};

export type ModelCenterInventoryRow = {
  modelId: string;
  label: string;
  providerKind: string;
  providerApi: string;
  baseUrl: string;
  model: string;
  configuredProtocol: string;
  resolvedProtocol: string;
  protocolSource: string;
  protocolWarnings: string[];
  compatSummary: string;
  apiKeyEnv: string;
  apiKeyState: string;
  supportsImageInput: boolean | null;
  capabilityStatus: string;
  imageInputStatus: "supported" | "unsupported" | "unknown";
  capabilitySource: string;
  capabilityCheckedAt: string;
  capabilityError: string;
  source: ConfigModelOption["source"];
  editable: boolean;
  deletable: boolean;
};

export function summarizeModelCompat(value: unknown): string {
  const compat = asRecord(value);
  const entries = Object.entries(compat).filter(([, entryValue]) => entryValue !== undefined && entryValue !== null && entryValue !== "");
  if (!entries.length) {
    return "";
  }
  return entries
    .slice(0, 4)
    .map(([key, entryValue]) => `${key}=${String(entryValue)}`)
    .join(" · ");
}

export function resolveImageInputCapabilityStatus(input: {
  supportsImageInput?: boolean | null;
  capabilityStatus?: string | null;
}): "supported" | "unsupported" | "unknown" {
  if (input.supportsImageInput === true) {
    return "supported";
  }
  if (input.supportsImageInput === false) {
    return "unsupported";
  }
  const capabilityStatus = String(input.capabilityStatus || "").trim().toLowerCase();
  if (capabilityStatus === "unsupported") {
    return "unsupported";
  }
  return "unknown";
}

export function resolveResearchAgentInstance(
  researchAgent: Pick<ResearchAgentConfig, "key" | "agentId" | "agentInstanceId" | "roleKey">,
  agentInstances: AgentInstance[],
): AgentInstance | null {
  const linkedAgentId = researchAgent.agentId || researchAgent.agentInstanceId || "";
  const byId = agentInstances.find((agent) => agent.agentId === linkedAgentId);
  if (byId) {
    return byId;
  }
  const roleKey = researchAgent.roleKey || `research_${researchAgent.key}`;
  const byRoleKey = agentInstances.find((agent) => agent.roleKey === roleKey);
  if (byRoleKey) {
    return byRoleKey;
  }
  return agentInstances.find((agent) => agent.metadata?.researchAgentKey === researchAgent.key) ?? null;
}

export function supervisedAgentRole(agent: Pick<AgentInstance, "metadata">): string {
  const roleKey = "roleKey" in agent ? (agent as Pick<AgentInstance, "roleKey">).roleKey : "";
  if (typeof roleKey === "string" && ["baseline", "candidate", "reviewer", "auditor", "judge"].includes(roleKey)) {
    return roleKey;
  }
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

function splitConfigPath(path: string): string[] {
  return path.split(".").filter(Boolean);
}

function getValueAtConfigPath(root: unknown, path: string): unknown {
  let current = root;
  for (const token of splitConfigPath(path)) {
    if (Array.isArray(current)) {
      current = current[Number(token)];
      continue;
    }
    if (isRecord(current)) {
      current = current[token];
      continue;
    }
    return undefined;
  }
  return current;
}

function setValueAtConfigPath<T>(root: T, path: string, nextValue: unknown): T {
  if (!path) {
    return clonePublicConfig(nextValue as T);
  }
  const cloned = clonePublicConfig(root);
  const tokens = splitConfigPath(path);
  let current: unknown = cloned;
  for (let index = 0; index < tokens.length - 1; index += 1) {
    const token = tokens[index];
    if (Array.isArray(current)) {
      current = current[Number(token)];
      continue;
    }
    if (isRecord(current)) {
      if (!isRecord(current[token]) && !Array.isArray(current[token])) {
        current[token] = {};
      }
      current = current[token];
      continue;
    }
    throw new Error(`Unknown config path: ${path}`);
  }
  const leaf = tokens[tokens.length - 1];
  if (Array.isArray(current)) {
    current[Number(leaf)] = clonePublicConfig(nextValue);
  } else if (isRecord(current)) {
    current[leaf] = clonePublicConfig(nextValue);
  }
  return cloned;
}

export function pickEditableConfigView(
  publicConfig: PublicConfigShape,
  sections: ConfigEditableSectionPath[],
): PublicConfigShape {
  return sections.reduce<PublicConfigShape>((view, section) => {
    const path = section.path.trim();
    if (!path) {
      return view;
    }
    const value = getValueAtConfigPath(publicConfig, path);
    if (value === undefined) {
      return view;
    }
    return setValueAtConfigPath(view, path, value);
  }, {});
}

export function mergeEditableConfigView(
  baseConfig: PublicConfigShape,
  editableView: PublicConfigShape,
  sections: ConfigEditableSectionPath[],
): PublicConfigShape {
  return sections.reduce<PublicConfigShape>((merged, section) => {
    const path = section.path.trim();
    if (!path) {
      return merged;
    }
    const value = getValueAtConfigPath(editableView, path);
    if (value === undefined) {
      return merged;
    }
    return setValueAtConfigPath(merged, path, value);
  }, clonePublicConfig(baseConfig));
}

export function buildConfigApplyPayload(input: BuildConfigApplyPayloadInput): ConfigApplyPayload {
  if (!input.draftConfig) {
    throw new Error(input.loadFailedMessage);
  }
  const publicConfig = input.hasEditorChanges
    ? mergeEditableConfigView(input.draftConfig, JSON.parse(input.editorText) as PublicConfigShape, input.editorSections)
    : input.draftConfig;
  return {
    publicConfig,
    draftMeta: input.draftMeta,
    baseHash: input.baseHash,
    baseConfig: input.baseConfig ?? input.draftConfig,
  };
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

export function resolveConfigSectionUiStateOnSelect<T extends ConfigSectionExpansionState>(
  existingState: T | undefined,
  defaultState: T,
): T {
  return existingState ?? defaultState;
}

export function shouldBlockConfigLeave(input: ConfigLeaveGuardInput): boolean {
  return input.hasPendingApply && !input.busy && input.currentPathname === "/config" && input.nextPathname !== "/config";
}

export function configInvalidationDomainsForApply(config: PublicConfigShape | null | undefined): ConfigInvalidationDomain[] {
  const domains = new Set<ConfigInvalidationDomain>(["config", "runtime", "sessions", "reset"]);
  if (config && typeof config === "object" && "evolution" in config) {
    domains.add("evolution");
  }
  return [...domains];
}

export function resolveModelEditability(option: ConfigModelOption): ModelEditability {
  return option.source === "model_library"
    ? { editable: true, deletable: true }
    : { editable: false, deletable: false };
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
  if (kind === "local" || kind === "ollama" || kind === "llamacpp" || baseUrl.includes("localhost") || baseUrl.includes("127.0.0.1")) {
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

export function providerPresetCategory(preset: ConfigProviderPresetOption): ModelPresetGroupId {
  return presetCategory({
    category: preset.category,
    label: preset.label,
    model: preset.default_model,
    model_id: preset.source_preset_id,
    preset_id: preset.source_preset_id,
    provider: preset.provider,
    provider_id: preset.provider_id,
  });
}

export function groupProviderPresetsByVendor(presets: ConfigProviderPresetOption[]): ProviderVendorGroup[] {
  const groups: ProviderVendorGroup[] = [];
  const groupById = new Map<string, ProviderVendorGroup>();
  for (const preset of presets) {
    const vendorId = getString(preset.vendor_id) || providerPresetCategory(preset);
    const vendorLabel = getString(preset.vendor_label) || vendorId;
    let group = groupById.get(vendorId);
    if (!group) {
      group = { id: vendorId, label: vendorLabel, templates: [] };
      groupById.set(vendorId, group);
      groups.push(group);
    }
    group.templates.push(preset);
  }
  return groups.filter((group) => group.templates.length);
}

export function selectModelScenarioProviderPresetId(
  scenario: ModelScenarioId,
  presets: ConfigProviderPresetOption[],
): string {
  if (scenario === "manual") {
    return "";
  }
  const byId = (presetId: string) => presets.find((preset) => preset.provider_preset_id === presetId)?.provider_preset_id ?? "";
  if (scenario === "image") {
    return byId("relay_image") || byId("openai_image") || presets.find((preset) => preset.label.toLowerCase().includes("image"))?.provider_preset_id || "";
  }
  if (scenario === "relay") {
    return byId("relay_openai") || byId("custom_relay_responses") || presets.find((preset) => providerPresetCategory(preset) === "relay")?.provider_preset_id || "";
  }
  if (scenario === "local") {
    return byId("local_main") || presets.find((preset) => providerPresetCategory(preset) === "local")?.provider_preset_id || "";
  }
  return byId("relay_openai") || byId("openai_main") || presets[0]?.provider_preset_id || "";
}

export function selectModelScenarioPresetId(
  scenario: ModelScenarioId,
  presets: ConfigModelPresetOption[],
): string {
  if (scenario === "manual") {
    return "";
  }
  const byId = (presetId: string) => presets.find((preset) => preset.preset_id === presetId)?.preset_id ?? "";
  if (scenario === "image") {
    const image2Preset = byId("relay_image2");
    if (image2Preset) {
      return image2Preset;
    }
    return (
      presets.find((preset) => {
        const model = getString(asRecord(preset.model).model).toLowerCase();
        const label = preset.label.toLowerCase();
        return model.includes("image") || model === "image2" || label.includes("image");
      })?.preset_id ?? ""
    );
  }
  if (scenario === "relay") {
    return byId("relay_openai_gpt_5_5") || (presets.find((preset) => presetCategory(preset) === "relay")?.preset_id ?? "");
  }
  if (scenario === "local") {
    return presets.find((preset) => presetCategory(preset) === "local")?.preset_id ?? "";
  }
  return byId("relay_openai_gpt_5_5") || byId("openai_gpt_5_5") || (presets.find((preset) => presetCategory(preset) === "official")?.preset_id ?? "");
}

export function defaultModelApiKeyEnv(modelId: string): string {
  const token = compactRepeatedTokenHalves(modelId
    .toUpperCase()
    .replace(/[^A-Z0-9]+/g, "_")
    .replace(/^_+|_+$/g, ""));
  return token ? `VIBELUTION_LLM_MODEL_${token}_API_KEY` : "VIBELUTION_LLM_MODEL_API_KEY";
}

function compactRepeatedTokenHalves(token: string): string {
  const parts = token.split("_").filter(Boolean);
  for (let size = Math.floor(parts.length / 2); size > 0; size -= 1) {
    const compacted: string[] = [];
    let index = 0;
    let changed = false;
    while (index < parts.length) {
      const chunk = parts.slice(index, index + size);
      const nextChunk = parts.slice(index + size, index + size * 2);
      if (chunk.length === size && chunk.every((part, offset) => part === nextChunk[offset]) && (size > 1 || !/^\d+$/.test(chunk[0]))) {
        compacted.push(...chunk);
        index += size * 2;
        changed = true;
      } else {
        compacted.push(parts[index]);
        index += 1;
      }
    }
    if (changed) {
      return compacted.join("_");
    }
  }
  return parts.join("_");
}

export function modelLibraryIdFromParts(label: string, model: string): string {
  const raw = `${label}-${model}`.trim();
  const token = compactRepeatedTokenHalves(raw
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, ""));
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
  { value: "ollama", label: "Ollama" },
  { value: "llamacpp", label: "llama.cpp" },
];

export const MODEL_TRANSPORT_OPTIONS: SelectOption[] = [
  { value: "chat_completions", label: "chat_completions" },
  { value: "responses", label: "responses" },
];

export const MODEL_CONTRACT_OPTIONS: SelectOption[] = [
  { value: "basic_chat", label: "basic_chat" },
  { value: "tool_chat", label: "tool_chat" },
  { value: "reasoning_chat", label: "reasoning_chat" },
  { value: "responses_agent", label: "responses_agent" },
];

export const MODEL_TOOL_CALLING_MODE_OPTIONS: SelectOption[] = [
  { value: "disabled", label: "disabled" },
  { value: "auto", label: "auto" },
  { value: "parallel", label: "parallel" },
];

export const MODEL_PROMPT_CACHE_MODE_OPTIONS: SelectOption[] = [
  { value: "automatic", label: "automatic" },
  { value: "explicit_cache_control", label: "explicit_cache_control" },
  { value: "disabled", label: "disabled" },
  { value: "unsupported", label: "unsupported" },
];

export const PROVIDER_COMPAT_MODE_OPTIONS: SelectOption[] = [
  { value: "openai", label: "openai" },
  { value: "openai_compatible", label: "openai_compatible" },
  { value: "native", label: "native" },
];

export function canDiscoverModelsForProvider(provider: Record<string, unknown>): boolean {
  const kind = getString(provider.kind).trim().toLowerCase();
  const compatMode = getString(provider.compat_mode).trim().toLowerCase();
  if (!getString(provider.base_url).trim()) {
    return false;
  }
  if (kind === "anthropic" || kind === "google" || kind === "minimax") {
    return false;
  }
  if (["local", "ollama", "llamacpp", "openai_compatible", "relay", "openai", "deepseek", "xiaomi", "zhipu", "aliyun", "siliconflow", "groq"].includes(kind)) {
    return true;
  }
  return compatMode === "openai" || compatMode === "openai_compatible";
}

function accountIdForModelOption(option: ConfigModelOption): string {
  const provider = asRecord(option.provider);
  const providerKind = option.provider_kind || getString(provider.kind) || "unknown";
  const baseUrl = getString(provider.base_url) || providerKind;
  const keyEnv = option.api_key_env || getString(provider.api_key_env);
  return [providerKind, baseUrl, keyEnv].map((part) => part.trim().toLowerCase()).join("::");
}

function summarizeAccountState(account: Omit<ModelCenterAccount, "modelCount" | "apiKeyState">): string {
  if (account.missingCount > 0) {
    return "missing";
  }
  if (account.pendingCount > 0) {
    return "pending";
  }
  if (account.clearPendingCount > 0) {
    return "clear_pending";
  }
  if (account.configuredCount > 0) {
    return "configured";
  }
  return "unknown";
}

export function deriveModelCenterSummary(input: {
  modelOptions: ConfigModelOption[];
}): ModelCenterSummary {
  const accountsById = new Map<string, Omit<ModelCenterAccount, "modelCount" | "apiKeyState">>();
  for (const option of input.modelOptions) {
    const provider = asRecord(option.provider);
    const id = accountIdForModelOption(option);
    const current =
      accountsById.get(id) ?? {
        id,
        providerKind: option.provider_kind || getString(provider.kind) || "unknown",
        baseUrl: getString(provider.base_url),
        keyEnv: option.api_key_env || getString(provider.api_key_env),
        modelIds: [],
        configuredCount: 0,
        missingCount: 0,
        pendingCount: 0,
        clearPendingCount: 0,
      };
    current.modelIds.push(option.model_id);
    const state = option.api_key_state;
    if (state === "configured" || option.api_key_configured) {
      current.configuredCount += 1;
    } else if (state === "pending") {
      current.pendingCount += 1;
    } else if (state === "clear_pending") {
      current.clearPendingCount += 1;
    } else if (state === "missing") {
      current.missingCount += 1;
    }
    accountsById.set(id, current);
  }

  const accounts = Array.from(accountsById.values())
    .map((account) => ({
      ...account,
      modelCount: account.modelIds.length,
      apiKeyState: summarizeAccountState(account),
    }))
    .sort((left, right) => `${left.providerKind}:${left.baseUrl}`.localeCompare(`${right.providerKind}:${right.baseUrl}`));

  return {
    accounts,
  };
}

export function deriveModelCenterInventoryRows(
  modelOptions: ConfigModelOption[],
): ModelCenterInventoryRow[] {
  return modelOptions.map((option) => {
    const provider = asRecord(option.provider);
    const editability = resolveModelEditability(option);
    const supportsImageInput =
      typeof option.supports_image_input === "boolean"
        ? option.supports_image_input
        : typeof asRecord(option.details).supports_image_input === "boolean"
          ? (asRecord(option.details).supports_image_input as boolean)
          : null;
    const capabilityStatus = option.capability_status || getString(asRecord(option.details).capability_status) || "unknown";
    const configuredProtocol = option.protocol || getString(asRecord(option.details).protocol);
    const resolvedCompat = Object.keys(asRecord(option.resolved_compat)).length ? option.resolved_compat : option.compat || asRecord(option.details).compat;
    return {
      modelId: option.model_id,
      label: option.label,
      providerKind: option.provider_kind || getString(provider.kind) || "unknown",
      providerApi: option.resolved_provider_api || option.provider_api || getString(provider.api),
      baseUrl: getString(provider.base_url),
      model: option.model,
      configuredProtocol,
      resolvedProtocol: option.resolved_protocol || configuredProtocol || "auto",
      protocolSource: option.protocol_source || (configuredProtocol ? "explicit_model" : "inferred"),
      protocolWarnings: Array.isArray(option.protocol_warnings) ? option.protocol_warnings.filter((item): item is string => typeof item === "string") : [],
      compatSummary: summarizeModelCompat(resolvedCompat),
      apiKeyEnv: option.api_key_env || getString(provider.api_key_env),
      apiKeyState: option.api_key_state,
      supportsImageInput,
      capabilityStatus,
      imageInputStatus: resolveImageInputCapabilityStatus({ supportsImageInput, capabilityStatus }),
      capabilitySource: option.capability_source || getString(asRecord(option.details).capability_source),
      capabilityCheckedAt: option.capability_checked_at || getString(asRecord(option.details).capability_checked_at),
      capabilityError: option.capability_error || getString(asRecord(option.details).capability_error),
      source: option.source,
      editable: editability.editable,
      deletable: editability.deletable,
    };
  });
}

export function countModelCenterHealthIssues(rows: ModelCenterInventoryRow[]): number {
  return rows.filter(
    (row) =>
      row.apiKeyState === "missing" ||
      row.apiKeyState === "clear_pending" ||
      (row.capabilitySource === "runtime_probe" && row.imageInputStatus === "unknown" && Boolean(row.capabilityError.trim())),
  ).length;
}
