export type WorkbenchTheme = "dark" | "light";

export const WORKBENCH_THEME_STORAGE_KEY = "vibelution.workbench.theme";
export const DEFAULT_WORKBENCH_THEME: WorkbenchTheme = "light";
const THEME_CHANGE_EVENT = "vibelution:workbench-theme-change";

type ThemeStorage = Pick<Storage, "getItem" | "setItem">;
type ThemeDocumentTarget = Pick<Document, "documentElement">;

function browserStorage(): ThemeStorage | null {
  if (typeof window === "undefined") {
    return null;
  }
  return window.localStorage;
}

export function normalizeWorkbenchTheme(value: unknown): WorkbenchTheme | null {
  const normalized = String(value ?? "").trim().toLowerCase();
  return normalized === "light" || normalized === "dark" ? normalized : null;
}

export function readStoredWorkbenchTheme(storage: ThemeStorage | null = browserStorage()): WorkbenchTheme {
  if (!storage) {
    return DEFAULT_WORKBENCH_THEME;
  }
  try {
    return normalizeWorkbenchTheme(storage.getItem(WORKBENCH_THEME_STORAGE_KEY)) ?? DEFAULT_WORKBENCH_THEME;
  } catch {
    return DEFAULT_WORKBENCH_THEME;
  }
}

export function writeStoredWorkbenchTheme(theme: WorkbenchTheme, storage: ThemeStorage | null = browserStorage()): void {
  if (!storage) {
    return;
  }
  try {
    storage.setItem(WORKBENCH_THEME_STORAGE_KEY, theme);
    if (typeof window !== "undefined") window.dispatchEvent(new CustomEvent(THEME_CHANGE_EVENT, { detail: theme }));
  } catch {
  }
}

/** Keep shell menu and settings rows in sync, including changes in other windows. */
export function subscribeStoredWorkbenchTheme(listener: (theme: WorkbenchTheme) => void): () => void {
  if (typeof window === "undefined") return () => undefined;
  const local = (event: Event) => {
    const next = normalizeWorkbenchTheme((event as CustomEvent<unknown>).detail);
    if (next) listener(next);
  };
  const remote = (event: StorageEvent) => {
    if (event.key === WORKBENCH_THEME_STORAGE_KEY || event.key === null) listener(readStoredWorkbenchTheme());
  };
  window.addEventListener(THEME_CHANGE_EVENT, local);
  window.addEventListener("storage", remote);
  return () => { window.removeEventListener(THEME_CHANGE_EVENT, local); window.removeEventListener("storage", remote); };
}

export function nextWorkbenchTheme(theme: WorkbenchTheme): WorkbenchTheme {
  return theme === "dark" ? "light" : "dark";
}

export function applyWorkbenchDocumentTheme(targetDocument: ThemeDocumentTarget, theme: WorkbenchTheme): void {
  targetDocument.documentElement.setAttribute("data-theme", theme);
}
