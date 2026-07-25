/**
 * Permanent pane-height memory for workbench splitters (vertical rails).
 * Parallel to pane-layouts.v1 widths; same layoutId namespace isolation.
 */

export const PANE_HEIGHT_STORAGE_KEY = "vibelution.pane-heights.v1";

export type PaneHeightMap = Record<string, number>;
export type PaneHeightsMap = Record<string, PaneHeightMap>;

export type PaneHeightSpec = {
  id: string;
  defaultHeight: number;
  minHeight: number;
  maxHeight: number;
};

function isBrowser(): boolean {
  return typeof window !== "undefined" && typeof window.localStorage !== "undefined";
}

export function clampPaneHeight(value: number, minHeight: number, maxHeight: number): number {
  if (!Number.isFinite(value)) {
    return minHeight;
  }
  return Math.round(Math.min(maxHeight, Math.max(minHeight, value)));
}

export function readAllPaneHeights(): PaneHeightsMap {
  if (!isBrowser()) {
    return {};
  }
  try {
    const raw = window.localStorage.getItem(PANE_HEIGHT_STORAGE_KEY);
    if (!raw) {
      return {};
    }
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return {};
    }
    const out: PaneHeightsMap = {};
    for (const [layoutId, heights] of Object.entries(parsed as Record<string, unknown>)) {
      if (!layoutId || !heights || typeof heights !== "object" || Array.isArray(heights)) {
        continue;
      }
      const paneMap: PaneHeightMap = {};
      for (const [paneId, height] of Object.entries(heights as Record<string, unknown>)) {
        const numeric = typeof height === "number" ? height : Number(height);
        if (paneId && Number.isFinite(numeric) && numeric > 0) {
          paneMap[paneId] = Math.round(numeric);
        }
      }
      if (Object.keys(paneMap).length) {
        out[layoutId] = paneMap;
      }
    }
    return out;
  } catch {
    return {};
  }
}

export function writeAllPaneHeights(layouts: PaneHeightsMap): void {
  if (!isBrowser()) {
    return;
  }
  try {
    window.localStorage.setItem(PANE_HEIGHT_STORAGE_KEY, JSON.stringify(layouts));
  } catch {
    // Quota / private mode
  }
}

export function readPaneHeights(layoutId: string): PaneHeightMap {
  const id = String(layoutId || "").trim();
  if (!id) {
    return {};
  }
  return readAllPaneHeights()[id] ?? {};
}

export function writePaneHeights(layoutId: string, heights: PaneHeightMap): void {
  const id = String(layoutId || "").trim();
  if (!id) {
    return;
  }
  const all = readAllPaneHeights();
  all[id] = { ...heights };
  writeAllPaneHeights(all);
}

export function migrateLegacyNumericHeight(
  layoutId: string,
  paneId: string,
  legacyStorageKey: string,
): void {
  const id = String(layoutId || "").trim();
  const pane = String(paneId || "").trim();
  const legacyKey = String(legacyStorageKey || "").trim();
  if (!id || !pane || !legacyKey || !isBrowser()) {
    return;
  }
  try {
    const existing = readPaneHeights(id);
    if (typeof existing[pane] === "number" && existing[pane] > 0) {
      return;
    }
    const raw = window.localStorage.getItem(legacyKey);
    if (!raw) {
      return;
    }
    const numeric = Number(raw);
    if (!Number.isFinite(numeric) || numeric <= 0) {
      return;
    }
    writePaneHeights(id, { ...existing, [pane]: Math.round(numeric) });
  } catch {
    // ignore
  }
}

export function resolveStoredPaneHeight(
  layoutId: string,
  paneId: string,
  defaultHeight: number,
  minHeight: number,
  maxHeight: number,
  legacyStorageKey?: string,
): number {
  if (legacyStorageKey) {
    migrateLegacyNumericHeight(layoutId, paneId, legacyStorageKey);
  }
  const stored = readPaneHeights(layoutId)[paneId];
  return clampPaneHeight(
    typeof stored === "number" ? stored : defaultHeight,
    minHeight,
    maxHeight,
  );
}

export function persistPaneHeight(
  layoutId: string,
  paneId: string,
  height: number,
): void {
  const id = String(layoutId || "").trim();
  const pane = String(paneId || "").trim();
  if (!id || !pane || !Number.isFinite(height) || height <= 0) {
    return;
  }
  const existing = readPaneHeights(id);
  writePaneHeights(id, { ...existing, [pane]: Math.round(height) });
}
