/** Pane visibility is separate from width memory: a hidden pane keeps its size. */
export const PANE_VISIBILITY_STORAGE_KEY = "vibelution.pane-visibility.v1";
type PaneVisibility = Record<string, Record<string, boolean>>;

function readVisibility(): PaneVisibility {
  try {
    const value: unknown = JSON.parse(window.localStorage.getItem(PANE_VISIBILITY_STORAGE_KEY) ?? "{}");
    if (!value || typeof value !== "object" || Array.isArray(value)) return {};
    return value as PaneVisibility;
  } catch { return {}; }
}

export function readPaneVisibility(layoutId: string, paneId: string, defaultVisible: boolean): boolean {
  const value = readVisibility()[layoutId]?.[paneId];
  return typeof value === "boolean" ? value : defaultVisible;
}

export function persistPaneVisibility(layoutId: string, paneId: string, visible: boolean): void {
  try {
    const all = readVisibility();
    window.localStorage.setItem(PANE_VISIBILITY_STORAGE_KEY, JSON.stringify({
      ...all, [layoutId]: { ...all[layoutId], [paneId]: visible },
    }));
  } catch { /* Storage may be disabled; in-memory controls remain usable. */ }
}
