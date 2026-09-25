/**
 * Pure helpers for Config provider draft actions (pin / quick-setup errors).
 * Network + React state stay on ConfigRoute.
 * Wave 4: user-facing pin messages are template-driven; zh/en strings live in
 * configCopy.ts and are passed in as `labels`.
 */

export function isProviderModelAlreadyPinnedErrorMessage(message: string): boolean {
  return /already exists|already pinned|已存在|已固定/i.test(String(message || ""));
}

export type ProviderQuickSetupErrorKind = "auth" | "endpoint" | "discovery";

export function classifyProviderQuickSetupErrorKind(message: string): ProviderQuickSetupErrorKind {
  const normalized = String(message || "").toLowerCase();
  if (
    normalized.includes("auth")
    || normalized.includes("credential")
    || normalized.includes("api key")
    || normalized.includes("401")
    || normalized.includes("403")
  ) {
    return "auth";
  }
  if (
    normalized.includes("endpoint")
    || normalized.includes("base_url")
    || normalized.includes("target")
    || normalized.includes("connect")
  ) {
    return "endpoint";
  }
  return "discovery";
}

/** Copy templates used by the provider pin message formatters (subset of ConfigCopy). */
export type ProviderPinCopyLabels = {
  pinBusyProgressTemplate: string;
  pinBusyOneTemplate: string;
  pinBusyManyTemplate: string;
  pinSuccessNewTemplate: string;
  pinSuccessSkippedTemplate: string;
  pinSuccessFallback: string;
  pinSuccessListJoiner: string;
  pinSuccessSuffix: string;
  pinErrorPartialTemplate: string;
  pinErrorTemplate: string;
};

function fillTemplate(template: string, vars: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (match, key: string) =>
    Object.prototype.hasOwnProperty.call(vars, key) ? String(vars[key]) : match,
  );
}

export function formatProviderPinBusyMessage(options: {
  modelCount: number;
  firstModelRef?: string;
  completed?: number;
  total?: number;
  labels: ProviderPinCopyLabels;
}): string {
  const { modelCount, firstModelRef, completed, total, labels } = options;
  if (typeof completed === "number" && typeof total === "number" && total > 1) {
    return fillTemplate(labels.pinBusyProgressTemplate, { completed, total });
  }
  if (modelCount === 1 && firstModelRef) {
    return fillTemplate(labels.pinBusyOneTemplate, { ref: firstModelRef });
  }
  return fillTemplate(labels.pinBusyManyTemplate, { count: modelCount });
}

export function formatProviderPinSuccessMessage(options: {
  pinnedCount: number;
  skippedTotal: number;
  labels: ProviderPinCopyLabels;
}): string {
  const { pinnedCount, skippedTotal, labels } = options;
  const parts = [
    pinnedCount > 0 ? fillTemplate(labels.pinSuccessNewTemplate, { count: pinnedCount }) : null,
    skippedTotal > 0 ? fillTemplate(labels.pinSuccessSkippedTemplate, { count: skippedTotal }) : null,
  ].filter(Boolean);
  return `${parts.join(labels.pinSuccessListJoiner) || labels.pinSuccessFallback}${labels.pinSuccessSuffix}`;
}

export function formatProviderPinErrorMessage(options: {
  pinnedCount: number;
  errorMessage: string;
  labels: ProviderPinCopyLabels;
}): string {
  const { pinnedCount, errorMessage, labels } = options;
  return pinnedCount > 0
    ? fillTemplate(labels.pinErrorPartialTemplate, { count: pinnedCount, message: errorMessage })
    : fillTemplate(labels.pinErrorTemplate, { message: errorMessage });
}
