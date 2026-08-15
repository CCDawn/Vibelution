import { fetchJson } from "./client";
import type {
  ConfigLlmTestResult,
  ConfigMigrationPreview,
  ConfigMigrationPreviewRequest,
  ConfigModelDiscoveryResult,
  ConfigProviderMergePreview,
  ConfigProviderMergeResult,
  ConfigSummary,
  ConfigWorkspace,
} from "./types";

export type ConfigDraftEnvelope = {
  publicConfig?: unknown;
  draftMeta?: unknown;
  baseHash?: string;
  [key: string]: unknown;
};

export type ConfigProviderIdSuggestion = {
  suggestedProviderId: string;
};

export type ConfigProviderRoutePreview = {
  providerId: string;
  routeChanged: boolean;
  routePreviewToken: string;
  modelRefs: string[];
  impactedRefs: Array<{
    modelRef?: string;
    liveReferenceCount?: number;
    historicalReferenceCount?: number;
  }>;
};

function postConfigJson<T>(url: string, body?: unknown, method = "POST"): Promise<T> {
  return fetchJson<T>(url, {
    method,
    headers: {
      "Content-Type": "application/json",
    },
    body: body == null ? undefined : JSON.stringify(body),
  });
}

export function fetchPublicConfig(options?: {
  signal?: AbortSignal;
}): Promise<ConfigSummary> {
  return fetchJson<ConfigSummary>("/api/config/public", {
    signal: options?.signal,
  });
}

export function fetchConfigWorkspace(options?: {
  signal?: AbortSignal;
}): Promise<ConfigWorkspace> {
  return fetchJson<ConfigWorkspace>("/api/config/workspace", {
    signal: options?.signal,
  });
}

export function previewConfigDraft(body: ConfigDraftEnvelope): Promise<ConfigWorkspace> {
  return postConfigJson<ConfigWorkspace>("/api/config/draft/preview", body);
}

export function suggestDraftProviderId(
  body: ConfigDraftEnvelope,
): Promise<ConfigProviderIdSuggestion> {
  return postConfigJson<ConfigProviderIdSuggestion>(
    "/api/config/draft/providers/id-suggestion",
    body,
  );
}

export function addDraftProvider(body: ConfigDraftEnvelope): Promise<ConfigWorkspace> {
  return postConfigJson<ConfigWorkspace>("/api/config/draft/providers", body);
}

export function updateDraftProvider(
  providerId: string,
  body: ConfigDraftEnvelope,
): Promise<ConfigWorkspace> {
  return postConfigJson<ConfigWorkspace>(
    `/api/config/draft/providers/${encodeURIComponent(providerId)}`,
    body,
    "PUT",
  );
}

export function deleteDraftProvider(
  providerId: string,
  body: ConfigDraftEnvelope,
): Promise<ConfigWorkspace> {
  return postConfigJson<ConfigWorkspace>(
    `/api/config/draft/providers/${encodeURIComponent(providerId)}`,
    body,
    "DELETE",
  );
}

export function previewDraftProviderRoute(
  providerId: string,
  body: ConfigDraftEnvelope,
): Promise<ConfigProviderRoutePreview> {
  return postConfigJson<ConfigProviderRoutePreview>(
    `/api/config/draft/providers/${encodeURIComponent(providerId)}/route-preview`,
    body,
  );
}

export function discoverDraftProvider(
  providerId: string,
  body: ConfigDraftEnvelope,
): Promise<ConfigWorkspace> {
  return postConfigJson<ConfigWorkspace>(
    `/api/config/draft/providers/${encodeURIComponent(providerId)}/discover`,
    body,
  );
}

export function pinDraftProviderModel(
  providerId: string,
  body: ConfigDraftEnvelope,
): Promise<ConfigWorkspace> {
  return postConfigJson<ConfigWorkspace>(
    `/api/config/draft/providers/${encodeURIComponent(providerId)}/models`,
    body,
  );
}

export function unpinDraftProviderModel(
  providerId: string,
  modelKey: string,
  body: ConfigDraftEnvelope,
): Promise<ConfigWorkspace> {
  return postConfigJson<ConfigWorkspace>(
    `/api/config/draft/providers/${encodeURIComponent(providerId)}/models/${encodeURIComponent(modelKey)}`,
    body,
    "DELETE",
  );
}

export function addDraftModel(body: ConfigDraftEnvelope): Promise<ConfigWorkspace> {
  return postConfigJson<ConfigWorkspace>("/api/config/draft/add-model", body);
}

export function updateDraftModel(body: ConfigDraftEnvelope): Promise<ConfigWorkspace> {
  return postConfigJson<ConfigWorkspace>("/api/config/draft/update-model", body);
}

export function deleteDraftModel(body: ConfigDraftEnvelope): Promise<ConfigWorkspace> {
  return postConfigJson<ConfigWorkspace>("/api/config/draft/delete-model", body);
}

export function testConfigLlm(body: ConfigDraftEnvelope): Promise<ConfigLlmTestResult> {
  return postConfigJson<ConfigLlmTestResult>("/api/config/test-llm", body);
}

export function checkDraftModelCapabilities(
  body: ConfigDraftEnvelope,
): Promise<ConfigWorkspace> {
  return postConfigJson<ConfigWorkspace>("/api/config/draft/check-model-capabilities", body);
}

export function discoverConfigModels(
  body: ConfigDraftEnvelope,
): Promise<ConfigModelDiscoveryResult> {
  return postConfigJson<ConfigModelDiscoveryResult>("/api/config/discover-models", body);
}

export function previewLlmV2Migration(
  body: ConfigMigrationPreviewRequest = {},
): Promise<ConfigMigrationPreview> {
  return postConfigJson<ConfigMigrationPreview>("/api/config/migration/llm-v2/preview", body);
}

export function applyLlmV2Migration(body: {
  previewId: string;
  baseHash: string;
}): Promise<{ migrationId: string; updatedReferenceCount?: number }> {
  return postConfigJson("/api/config/migration/llm-v2/apply", body);
}

export function rollbackLlmV2Migration(
  migrationId: string,
  body: { migrationId: string; baseHash: string },
): Promise<{ migrationId: string }> {
  return postConfigJson(
    `/api/config/migration/llm-v2/${encodeURIComponent(migrationId)}/rollback`,
    body,
  );
}

export function previewProviderMerge(body: {
  canonicalProviderId: string;
  duplicateProviderIds: string[];
  credentialDecisions?: Record<string, string>;
}): Promise<ConfigProviderMergePreview> {
  return postConfigJson<ConfigProviderMergePreview>(
    "/api/config/migration/providers/merge/preview",
    body,
  );
}

export function applyProviderMerge(body: {
  previewId: string;
  baseHash: string;
  confirmed: boolean;
}): Promise<ConfigProviderMergeResult> {
  return postConfigJson<ConfigProviderMergeResult>(
    "/api/config/migration/providers/merge/apply",
    body,
  );
}

export function rollbackProviderMerge(
  migrationId: string,
  body: { migrationId: string; baseHash: string },
): Promise<ConfigProviderMergeResult> {
  return postConfigJson<ConfigProviderMergeResult>(
    `/api/config/migration/providers/merge/${encodeURIComponent(migrationId)}/rollback`,
    body,
  );
}

export type ConfigImageUploadResult = {
  path: string;
  url: string;
  contentType: string;
  sizeBytes: number;
};

export function applyConfigWorkspace(body: ConfigDraftEnvelope): Promise<ConfigWorkspace> {
  return postConfigJson<ConfigWorkspace>("/api/config/apply", body, "PUT");
}

export function openConfigEnvironment(): Promise<{ opened: boolean }> {
  return postConfigJson<{ opened: boolean }>("/api/config/open-environment", {});
}

export function uploadConfigAvatarImage(body: {
  filename: string;
  contentType: string;
  dataBase64: string;
}): Promise<ConfigImageUploadResult> {
  return postConfigJson<ConfigImageUploadResult>("/api/config/avatar-image", body);
}

export function uploadConfigThemeBackgroundImage(body: {
  filename: string;
  contentType: string;
  dataBase64: string;
}): Promise<ConfigImageUploadResult> {
  return postConfigJson<ConfigImageUploadResult>("/api/config/theme-background-image", body);
}

export function updateIntakeMode(
  intakeMode: "manual_review" | "auto",
): Promise<ConfigSummary> {
  return postConfigJson<ConfigSummary>("/api/config/intake-mode", { intakeMode }, "PUT");
}

export function updateConfigLanguage(language: "zh" | "en"): Promise<ConfigSummary> {
  return postConfigJson<ConfigSummary>("/api/config/language", { language }, "PUT");
}
