export const MAX_FINANCE_SCREEN_PRESETS = 20;

export type FinanceScreenPresetFilters = {
  minPrice: string;
  maxPrice: string;
  minChangePercent: string;
  maxChangePercent: string;
  minPe: string;
  maxPe: string;
  minPb: string;
  maxPb: string;
  minVolumeLots: string;
  minTurnoverYi: string;
  maxTurnoverYi: string;
  sortBy: "changePercent" | "turnoverYuan" | "volumeLots" | "price" | "peRatio" | "pbRatio";
  direction: "asc" | "desc";
};

export type FinanceScreenPreset = {
  id: string;
  name: string;
  filters: FinanceScreenPresetFilters;
};

type StorageLike = Pick<Storage, "getItem" | "setItem">;

const numericFilterKeys = [
  "minPrice", "maxPrice", "minChangePercent", "maxChangePercent",
  "minPe", "maxPe", "minPb", "maxPb", "minVolumeLots",
  "minTurnoverYi", "maxTurnoverYi",
] as const;
const sortFields = new Set<FinanceScreenPresetFilters["sortBy"]>([
  "changePercent", "turnoverYuan", "volumeLots", "price", "peRatio",
  "pbRatio",
]);

export const EMPTY_FINANCE_SCREEN_PRESET_FILTERS: FinanceScreenPresetFilters = {
  minPrice: "", maxPrice: "", minChangePercent: "", maxChangePercent: "",
  minPe: "", maxPe: "", minPb: "", maxPb: "", minVolumeLots: "",
  minTurnoverYi: "", maxTurnoverYi: "", sortBy: "changePercent", direction: "desc",
};

export function financeScreenPresetStorageKey(agentId: string): string {
  return `vibelution.finance-screen-presets.v1:${encodeURIComponent(agentId.trim())}`;
}

function browserStorage(): StorageLike | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

function normalizeFilters(value: unknown): FinanceScreenPresetFilters | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const raw = value as Record<string, unknown>;
  const filters = { ...EMPTY_FINANCE_SCREEN_PRESET_FILTERS };
  for (const key of numericFilterKeys) {
    const candidate = raw[key];
    if (typeof candidate !== "string" || candidate.length > 32) continue;
    if (!candidate.trim()) continue;
    const parsed = Number(candidate);
    if (Number.isFinite(parsed)) filters[key] = String(parsed);
  }
  if (typeof raw.sortBy === "string" && sortFields.has(raw.sortBy as FinanceScreenPresetFilters["sortBy"])) {
    filters.sortBy = raw.sortBy as FinanceScreenPresetFilters["sortBy"];
  }
  if (raw.direction === "asc" || raw.direction === "desc") filters.direction = raw.direction;
  return filters;
}

function normalizePresets(value: unknown): FinanceScreenPreset[] {
  if (!Array.isArray(value)) return [];
  const result: FinanceScreenPreset[] = [];
  const ids = new Set<string>();
  for (const candidate of value) {
    if (!candidate || typeof candidate !== "object" || Array.isArray(candidate)) continue;
    const raw = candidate as Record<string, unknown>;
    if (typeof raw.id !== "string" || !raw.id || ids.has(raw.id)) continue;
    if (typeof raw.name !== "string" || !raw.name.trim()) continue;
    const filters = normalizeFilters(raw.filters);
    if (!filters) continue;
    ids.add(raw.id);
    result.push({ id: raw.id.slice(0, 80), name: raw.name.trim().slice(0, 40), filters });
    if (result.length === MAX_FINANCE_SCREEN_PRESETS) break;
  }
  return result;
}

export function readFinanceScreenPresets(agentId: string, storage: StorageLike | null = browserStorage()): FinanceScreenPreset[] {
  if (!agentId.trim() || !storage) return [];
  try {
    return normalizePresets(JSON.parse(storage.getItem(financeScreenPresetStorageKey(agentId)) ?? "null"));
  } catch {
    return [];
  }
}

export function writeFinanceScreenPresets(
  agentId: string,
  presets: readonly FinanceScreenPreset[],
  storage: StorageLike | null = browserStorage(),
): boolean {
  if (!agentId.trim() || !storage) return false;
  try {
    storage.setItem(financeScreenPresetStorageKey(agentId), JSON.stringify(normalizePresets(presets)));
    return true;
  } catch {
    return false;
  }
}
