/**
 * Settings-align wave 3 — pure ConfigRoute editor/domain model helpers,
 * extracted verbatim from ConfigRoute.tsx (zero behavior changes): draft
 * shapes + builders, payload builders, path/value utilities, display
 * formatting, and bilingual issue describers.
 */

import type { ConfigDraftMeta, ConfigEditorMeta, ConfigModelOption } from "../../api/types";
import { asRecord, getString, type PublicConfigShape } from "../configRouteLogic";
import { configSectionExpandedByDefault, configSectionFieldCopy } from "../configSectionPresentation";
import type { ConfigCopy, ConfigLanguage } from "./configCopy";
import type { JsonParseIssue, ListIssue, NumberIssue } from "./configFieldEditorsModel";
type ProviderDiscoveryFailureDetail = {
  providerId: string;
  reasonCode: string;
  retryable: boolean;
};

export type ProviderDraft = {
  kind: string;
  api: string;
  api_key_env: string;
  base_url: string;
  compat_mode: string;
  requires_api_key: boolean;
  context_window: string;
};

export type ModelDetailsDraft = {
  transport: string;
  contract: string;
  protocol: string;
  compat: string;
  reasoning_state_field: string;
  strict_compatibility: boolean;
  temperature: string;
  max_output_tokens: string;
  timeout: string;
  connect_timeout: string;
  streaming: boolean;
  tool_calling_mode: string;
  prompt_cache_mode: string;
  prompt_cache_configured: boolean;
  discovery_enabled: boolean;
  supports_image_input: "unknown" | "supported" | "unsupported";
};

export type ModelEditorState = {
  mode: "create" | "edit";
  preset_id: string;
  provider_template_id: string;
  model_id: string;
  label: string;
  model: string;
  api_key_env: string;
  api_key: string;
  clear_api_key: boolean;
  provider: ProviderDraft;
  details: ModelDetailsDraft;
};

export type ConfigSectionUiState = {
  expanded: boolean;
  editing: boolean;
  advancedExpanded: boolean;
  expandedPaths: Record<string, boolean>;
  draftValue?: unknown;
};

export function defaultSectionUiState(sectionId = ""): ConfigSectionUiState {
  return {
    expanded: configSectionExpandedByDefault(sectionId),
    editing: false,
    advancedExpanded: false,
    expandedPaths: {},
  };
}

export function emptyDraftMeta(): ConfigDraftMeta {
  return {
    pending_api_keys: {},
    pending_cleared_api_keys: [],
  };
}

export function emptyProviderDraft(): ProviderDraft {
  return {
    kind: "openai_compatible",
    api: "",
    api_key_env: "",
    base_url: "",
    compat_mode: "openai",
    requires_api_key: true,
    context_window: "",
  };
}

export function emptyModelDetailsDraft(): ModelDetailsDraft {
  return {
    transport: "chat_completions",
    contract: "tool_chat",
    protocol: "",
    compat: "",
    reasoning_state_field: "",
    strict_compatibility: false,
    temperature: "",
    max_output_tokens: "",
    timeout: "",
    connect_timeout: "",
    streaming: true,
    tool_calling_mode: "auto",
    prompt_cache_mode: "disabled",
    prompt_cache_configured: false,
    discovery_enabled: true,
    supports_image_input: "unknown",
  };
}

export function emptyModelEditorState(): ModelEditorState {
  return {
    mode: "create",
    preset_id: "",
    provider_template_id: "",
    model_id: "",
    label: "",
    model: "",
    api_key_env: "",
    api_key: "",
    clear_api_key: false,
    provider: emptyProviderDraft(),
    details: emptyModelDetailsDraft(),
  };
}

export function formatJson(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

export function readableErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function providerDiscoveryFailureDetail(error: unknown): ProviderDiscoveryFailureDetail | null {
  const message = readableErrorMessage(error);
  try {
    const payload = JSON.parse(message) as { detail?: unknown };
    const detail = asRecord(payload.detail);
    if (detail.code !== "provider_discovery_failed" || !getString(detail.providerId) || !getString(detail.reasonCode)) {
      return null;
    }
    return {
      providerId: getString(detail.providerId),
      reasonCode: getString(detail.reasonCode),
      retryable: getBoolean(detail.retryable),
    };
  } catch {
    return null;
  }
}

/** Copy templates for provider discovery failure reasons (subset of ConfigCopy). */
export type DiscoveryFailureLabels = {
  discoveryFailureCredentialMissing: string;
  discoveryFailureCredentialRejected: string;
  discoveryFailureEndpointInvalid: string;
  discoveryFailureNetwork: string;
  discoveryFailureTimeout: string;
  discoveryFailureProtocolMismatch: string;
  discoveryFailureInvalidResponse: string;
  discoveryFailureRateLimited: string;
  discoveryFailureUpstreamRejected: string;
  discoveryFailureDefault: string;
};

export function providerDiscoveryFailureMessage(
  detail: ProviderDiscoveryFailureDetail | null,
  labels: DiscoveryFailureLabels,
): string {
  switch (detail?.reasonCode) {
    case "credential_missing": return labels.discoveryFailureCredentialMissing;
    case "credential_rejected": return labels.discoveryFailureCredentialRejected;
    case "endpoint_invalid": return labels.discoveryFailureEndpointInvalid;
    case "network": return labels.discoveryFailureNetwork;
    case "timeout": return labels.discoveryFailureTimeout;
    case "protocol_mismatch": return labels.discoveryFailureProtocolMismatch;
    case "invalid_response": return labels.discoveryFailureInvalidResponse;
    case "rate_limited": return labels.discoveryFailureRateLimited;
    case "upstream_rejected": return labels.discoveryFailureUpstreamRejected;
    default: return labels.discoveryFailureDefault;
  }
}

export function getBoolean(value: unknown, fallback = false): boolean {
  return typeof value === "boolean" ? value : fallback;
}

export function getDraftLanguage(config: PublicConfigShape | null, fallback: ConfigLanguage): ConfigLanguage {
  const ui = asRecord(config?.ui);
  return ui.language === "en" ? "en" : fallback;
}

export function buildProviderDraft(providerInput: Record<string, unknown>): ProviderDraft {
  return {
    kind: getString(providerInput.kind),
    api: getString(providerInput.api),
    api_key_env: getString(providerInput.api_key_env),
    base_url: getString(providerInput.base_url),
    compat_mode: getString(providerInput.compat_mode) || "openai",
    requires_api_key: getBoolean(providerInput.requires_api_key, true),
    context_window: getString(providerInput.context_window),
  };
}

export function buildModelDetailsDraft(detailsInput: Record<string, unknown>): ModelDetailsDraft {
  const promptCache = asRecord(detailsInput.prompt_cache);
  const supportsImageInput =
    typeof detailsInput.supports_image_input === "boolean"
      ? detailsInput.supports_image_input
        ? "supported"
        : "unsupported"
      : "unknown";
  return {
    transport: getString(detailsInput.transport) || "chat_completions",
    contract: getString(detailsInput.contract) || "tool_chat",
    protocol: getString(detailsInput.protocol),
    compat: Object.keys(asRecord(detailsInput.compat)).length ? JSON.stringify(asRecord(detailsInput.compat), null, 2) : "",
    reasoning_state_field: getString(detailsInput.reasoning_state_field),
    strict_compatibility: getBoolean(detailsInput.strict_compatibility, false),
    temperature: getString(detailsInput.temperature),
    max_output_tokens: getString(detailsInput.max_output_tokens),
    timeout: getString(detailsInput.timeout),
    connect_timeout: getString(detailsInput.connect_timeout),
    streaming: getBoolean(detailsInput.streaming, true),
    tool_calling_mode: getString(detailsInput.tool_calling_mode) || "auto",
    prompt_cache_mode: getString(promptCache.mode) || "disabled",
    prompt_cache_configured: Boolean(promptCache.mode),
    discovery_enabled: getBoolean(detailsInput.discovery_enabled, true),
    supports_image_input: supportsImageInput,
  };
}

export function hydrateModelEditorFromOption(option: ConfigModelOption): ModelEditorState {
  return {
    mode: "edit",
    preset_id: "",
    provider_template_id: "",
    model_id: option.model_id,
    label: option.label,
    model: option.model,
    api_key_env: option.api_key_env,
    api_key: "",
    clear_api_key: false,
    provider: buildProviderDraft(asRecord(option.provider)),
    details: buildModelDetailsDraft(asRecord(option.details)),
  };
}

export function buildProviderPayload(draft: ProviderDraft): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    kind: draft.kind.trim(),
    api: draft.api.trim(),
    api_key_env: draft.api_key_env.trim(),
    base_url: draft.base_url.trim(),
    compat_mode: draft.compat_mode.trim(),
    requires_api_key: draft.requires_api_key,
  };
  // Empty means unconfigured — send null so backend clears schema defaults instead of inventing 32768.
  const contextWindowRaw = draft.context_window.trim();
  if (contextWindowRaw) {
    const parsed = Number(contextWindowRaw);
    if (!Number.isFinite(parsed) || parsed <= 0) {
      throw new Error("context_window must be a positive integer");
    }
    payload.context_window = Math.round(parsed);
  } else {
    payload.context_window = null;
  }
  return payload;
}

function parseModelCompatDraft(value: string): Record<string, unknown> | null {
  const text = value.trim();
  if (!text) {
    return {};
  }
  const parsed = JSON.parse(text) as unknown;
  return isPlainObject(parsed) ? parsed : null;
}

export function buildModelDetailsPayload(draft: ModelDetailsDraft): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    strict_compatibility: draft.strict_compatibility,
    streaming: draft.streaming,
    discovery_enabled: draft.discovery_enabled,
  };
  if (draft.transport.trim()) {
    payload.transport = draft.transport.trim();
  }
  if (draft.contract.trim()) {
    payload.contract = draft.contract.trim();
  }
  if (draft.protocol.trim()) {
    payload.protocol = draft.protocol.trim();
  }
  const compat = parseModelCompatDraft(draft.compat);
  if (!compat) {
    throw new Error("compat must be a JSON object");
  }
  if (Object.keys(compat).length) {
    payload.compat = compat;
  }
  if (draft.reasoning_state_field.trim()) {
    payload.reasoning_state_field = draft.reasoning_state_field.trim();
  }
  if (draft.tool_calling_mode.trim()) {
    payload.tool_calling_mode = draft.tool_calling_mode.trim();
  }
  if (draft.prompt_cache_configured || draft.prompt_cache_mode.trim() !== "disabled") {
    payload.prompt_cache = { mode: draft.prompt_cache_mode.trim() };
  }
  if (draft.temperature.trim()) {
    payload.temperature = Number(draft.temperature.trim());
  }
  if (draft.max_output_tokens.trim()) {
    payload.max_output_tokens = Number(draft.max_output_tokens.trim());
  }
  if (draft.timeout.trim()) {
    payload.timeout = Number(draft.timeout.trim());
  }
  if (draft.connect_timeout.trim()) {
    payload.connect_timeout = Number(draft.connect_timeout.trim());
  }
  if (draft.supports_image_input === "supported") {
    payload.supports_image_input = true;
    payload.capability_status = "supported";
    payload.capability_source = "manual";
  } else if (draft.supports_image_input === "unsupported") {
    payload.supports_image_input = false;
    payload.capability_status = "unsupported";
    payload.capability_source = "manual";
  }
  return payload;
}

function splitConfigPath(path: string): string[] {
  return path.split(".").filter(Boolean);
}

export function isPlainObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

export function isConfigObjectListValue(value: unknown, kind: ConfigEditorMeta["kind"] | undefined): value is Record<string, unknown>[] {
  if (!Array.isArray(value)) {
    return false;
  }
  if (kind === "object_list") {
    return true;
  }
  if (kind === "string_list") {
    return false;
  }
  return value.length > 0 && value.every((item) => isPlainObject(item));
}

export function getConfigValueAtPath(root: unknown, path: string): unknown {
  let current = root;
  for (const token of splitConfigPath(path)) {
    if (Array.isArray(current)) {
      current = current[Number(token)];
      continue;
    }
    if (isPlainObject(current)) {
      current = current[token];
      continue;
    }
    return undefined;
  }
  return current;
}

function humanizeConfigToken(token: string): string {
  return token
    .split("_")
    .filter(Boolean)
    .map((part) => (part.toUpperCase() === part ? part : `${part.charAt(0).toUpperCase()}${part.slice(1)}`))
    .join(" ");
}

export function configLabel(metaMap: Record<string, ConfigEditorMeta>, path: string, lang: ConfigLanguage): string {
  return configSectionFieldCopy(path, lang)?.label
    ?? metaMap[path]?.label
    ?? humanizeConfigToken(splitConfigPath(path).at(-1) ?? path);
}

export function configHint(metaMap: Record<string, ConfigEditorMeta>, path: string, lang: ConfigLanguage): string {
  return configSectionFieldCopy(path, lang)?.hint ?? metaMap[path]?.hint ?? "";
}

export function formatConfigDisplayValue(value: unknown, kind: ConfigEditorMeta["kind"] | undefined, copy: ConfigCopy): string {
  if (kind === "secret") {
    return getString(value) ? "******" : copy.emptyValue;
  }
  if (typeof value === "boolean") {
    return value ? copy.yes : copy.no;
  }
  if (Array.isArray(value)) {
    if (value.length === 0) {
      return copy.emptyValue;
    }
    return value
      .map((item) => (typeof item === "string" ? item : JSON.stringify(item)))
      .join(", ");
  }
  if (value == null || value === "") {
    return copy.emptyValue;
  }
  return String(value);
}

/** Map a structured field-editor issue to bilingual copy (codes stay pure in configFieldEditorsModel). */
export function describeJsonIssue(issue: JsonParseIssue, copy: ConfigCopy): string {
  const position = issue.line !== null
    ? `${copy.jsonErrorAt}${issue.line}${copy.jsonErrorLine}${issue.column ?? "?"}${copy.jsonErrorCol}`
    : "";
  return `${copy.jsonInvalidPrefix}${issue.message}${position}`;
}

export function describeNumberIssue(issue: NumberIssue, copy: ConfigCopy): string {
  switch (issue.code) {
    case "numberRequired":
      return copy.numberRequired;
    case "numberInvalid":
      return `${copy.numberInvalidPrefix}「${issue.value}」`;
    case "numberBelowMin":
      return `${issue.exclusive ? copy.numberBelowMinExclusive : copy.numberBelowMinInclusive}${issue.bound}`;
    case "numberAboveMax":
      return `${issue.exclusive ? copy.numberAboveMaxExclusive : copy.numberAboveMaxInclusive}${issue.bound}`;
  }
}

export function describeListIssue(issue: ListIssue, copy: ConfigCopy): string {
  const detail = issue.code === "listInvalidToolName"
    ? copy.listInvalidToolName
    : issue.code === "listDuplicateItem"
      ? copy.listDuplicateItem
      : issue.code === "listBlankLine"
        ? copy.listBlankLineWarning
        : copy.listWhitespaceWarning;
  const value = issue.code === "listWhitespace" || issue.code === "listInvalidToolName" ? `「${issue.value}」` : "";
  return `${copy.listLinePrefix}${issue.line}${copy.listLineMid}${value} ${detail}`.trimEnd();
}

export async function fileToBase64(file: File): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  const chunkSize = 0x8000;
  for (let index = 0; index < bytes.length; index += chunkSize) {
    const chunk = bytes.subarray(index, index + chunkSize);
    binary += String.fromCharCode(...chunk);
  }
  return btoa(binary);
}
