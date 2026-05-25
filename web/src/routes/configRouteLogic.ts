import type { ConfigDraftMeta, ConfigModelOption, ConfigModelPresetOption, ConfigProfileCard } from "../api/types";

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

export type ModelEditability = {
  editable: boolean;
  deletable: boolean;
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
