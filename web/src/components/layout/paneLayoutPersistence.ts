/**
 * Permanent pane-width memory for workbench sidebars.
 * Storage key is shared; each layoutId isolates Chat/Agents/Config/etc.
 */

export const PANE_LAYOUT_STORAGE_KEY = "vibelution.pane-layouts.v1";

export type PaneWidthMap = Record<string, number>;
export type PaneLayoutsMap = Record<string, PaneWidthMap>;

export type PaneSpec = {
  id: string;
  defaultWidth: number;
  minWidth: number;
  maxWidth: number;
};

function isBrowser(): boolean {
  return typeof window !== "undefined" && typeof window.localStorage !== "undefined";
}

export function clampPaneWidth(value: number, minWidth: number, maxWidth: number): number {
  if (!Number.isFinite(value)) {
    return minWidth;
  }
  return Math.round(Math.min(maxWidth, Math.max(minWidth, value)));
}

export function readAllPaneLayouts(): PaneLayoutsMap {
  if (!isBrowser()) {
    return {};
  }
  try {
    const raw = window.localStorage.getItem(PANE_LAYOUT_STORAGE_KEY);
    if (!raw) {
      return {};
    }
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return {};
    }
    const out: PaneLayoutsMap = {};
    for (const [layoutId, widths] of Object.entries(parsed as Record<string, unknown>)) {
      if (!layoutId || !widths || typeof widths !== "object" || Array.isArray(widths)) {
        continue;
      }
      const paneMap: PaneWidthMap = {};
      for (const [paneId, width] of Object.entries(widths as Record<string, unknown>)) {
        const numeric = typeof width === "number" ? width : Number(width);
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

export function writeAllPaneLayouts(layouts: PaneLayoutsMap): void {
  if (!isBrowser()) {
    return;
  }
  try {
    window.localStorage.setItem(PANE_LAYOUT_STORAGE_KEY, JSON.stringify(layouts));
  } catch {
    // Quota / private mode — ignore; in-memory widths still work for the session.
  }
}

export function readPaneLayout(layoutId: string): PaneWidthMap {
  const id = String(layoutId || "").trim();
  if (!id) {
    return {};
  }
  return readAllPaneLayouts()[id] ?? {};
}

export function writePaneLayout(layoutId: string, widths: PaneWidthMap): void {
  const id = String(layoutId || "").trim();
  if (!id) {
    return;
  }
  const all = readAllPaneLayouts();
  all[id] = { ...widths };
  writeAllPaneLayouts(all);
}

export function resolvePaneWidths(
  layoutId: string,
  panes: readonly PaneSpec[],
): PaneWidthMap {
  const stored = readPaneLayout(layoutId);
  const resolved: PaneWidthMap = {};
  for (const pane of panes) {
    const raw = stored[pane.id];
    resolved[pane.id] = clampPaneWidth(
      typeof raw === "number" ? raw : pane.defaultWidth,
      pane.minWidth,
      pane.maxWidth,
    );
  }
  return resolved;
}
