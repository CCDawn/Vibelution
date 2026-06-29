export type WorkbenchTheme = "dark" | "light";

export const WORKBENCH_THEME_STORAGE_KEY = "vibelution.workbench.theme";
export const DEFAULT_WORKBENCH_THEME: WorkbenchTheme = "light";

type ThemeStorage = Pick<Storage, "getItem" | "setItem">;

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
  } catch {
  }
}

export function nextWorkbenchTheme(theme: WorkbenchTheme): WorkbenchTheme {
  return theme === "dark" ? "light" : "dark";
}
