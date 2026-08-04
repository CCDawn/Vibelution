/**
 * Pure helpers for Config provider draft actions (pin / quick-setup errors).
 * Network + React state stay on ConfigRoute.
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

export function formatProviderPinBusyMessage(options: {
  modelCount: number;
  firstModelRef?: string;
  completed?: number;
  total?: number;
}): string {
  const { modelCount, firstModelRef, completed, total } = options;
  if (typeof completed === "number" && typeof total === "number" && total > 1) {
    return `正在固定模型…（${completed}/${total}）`;
  }
  if (modelCount === 1 && firstModelRef) {
    return `正在固定 ${firstModelRef}…`;
  }
  return `正在固定 ${modelCount} 个模型…`;
}

export function formatProviderPinSuccessMessage(options: {
  pinnedCount: number;
  skippedTotal: number;
}): string {
  const { pinnedCount, skippedTotal } = options;
  const parts = [
    pinnedCount > 0 ? `新固定 ${pinnedCount} 个` : null,
    skippedTotal > 0 ? `跳过已存在 ${skippedTotal} 个` : null,
  ].filter(Boolean);
  return `${parts.join("，") || "固定完成"}。已切换到「已固定」列表；请点右上角「保存到外部配置」。`;
}

export function formatProviderPinErrorMessage(options: {
  pinnedCount: number;
  errorMessage: string;
}): string {
  const { pinnedCount, errorMessage } = options;
  return pinnedCount > 0
    ? `已固定 ${pinnedCount} 个后失败：${errorMessage}`
    : `固定失败：${errorMessage}`;
}
