export type WorkbenchTheme = "dark" | "light";

export const WORKBENCH_THEME_STORAGE_KEY = "vibelution.workbench.theme";
export const DEFAULT_WORKBENCH_THEME: WorkbenchTheme = "light";
const THEME_CHANGE_EVENT = "vibelution:workbench-theme-change";
const MIRRORED_THEME_KEY = "vibelution.workbench.theme.authority-mirror";
const THEME_SYNC_EVENT = "vibelution:workbench-theme-sync";
const THEME_IPC_TIMEOUT_MS = 3000;
type ThemeSyncState = "applied" | "local" | "conflict" | "unknown" | "unavailable";

type ThemeSnapshot = { epoch: string; revision: number; theme: WorkbenchTheme; writeId: string };
type ThemeOutcome = { code: string; snapshot?: ThemeSnapshot };
type ThemeBridge = {
  readThemeAuthority?: () => Promise<ThemeOutcome>;
  setThemeAuthority?: (input: ThemeSnapshot) => Promise<ThemeOutcome>;
  onAssistantThemeChanged?: (handler: (value: unknown) => void) => () => void;
  reportThemeProjection?: (input: { epoch: string; revision: number; state: "applied" | "conflict" }) => Promise<unknown>;
};
let authoritySnapshot: ThemeSnapshot | null = null;
let authorityInitialized = false;
let localOnly = false;
let localRequestSequence = 0;
let themeSyncState: ThemeSyncState = "applied";

async function boundedThemeRequest<T>(request: Promise<T>): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([request, new Promise<never>((_resolve, reject) => {
      timer = setTimeout(() => reject(new Error("theme_ipc_timeout")), THEME_IPC_TIMEOUT_MS);
    })]);
  } finally { clearTimeout(timer); }
}

function announceThemeSync(state: ThemeSyncState): void {
  themeSyncState = state;
  if (typeof window !== "undefined") window.dispatchEvent(new CustomEvent(THEME_SYNC_EVENT, { detail: state }));
}

function themeBridge(): ThemeBridge | undefined {
  const source = globalThis as { vibelutionLauncher?: ThemeBridge; vibelutionLauncherTheme?: ThemeBridge };
  return source.vibelutionLauncher ?? source.vibelutionLauncherTheme;
}

function validSnapshot(value: unknown): value is ThemeSnapshot {
  if (!value || typeof value !== "object") return false;
  const row = value as Record<string, unknown>;
  return typeof row.epoch === "string" && row.epoch.length > 0 && Number.isSafeInteger(row.revision)
    && Number(row.revision) >= 0 && typeof row.writeId === "string" && /^[0-9a-f]{32}$/.test(row.writeId)
    && (row.theme === "light" || row.theme === "dark");
}

/** Project the authority without overwriting an untracked local preference. */
function acceptAuthority(value: unknown, explicit: boolean, handshake: boolean, allowPendingOverride = false): boolean {
  if (!validSnapshot(value)) return false;
  if (authoritySnapshot && value.epoch !== authoritySnapshot.epoch && !handshake) return false;
  if (authoritySnapshot?.epoch === value.epoch && value.revision < authoritySnapshot.revision) return false;
  authoritySnapshot = value;
  const storage = browserStorage();
  if (!storage) return false;
  try {
    const local = normalizeWorkbenchTheme(storage.getItem(WORKBENCH_THEME_STORAGE_KEY));
    const marker = storage.getItem(MIRRORED_THEME_KEY);
    const mirrored = normalizeWorkbenchTheme(marker);
    if (!allowPendingOverride && (marker === "unknown" || marker === "unsynced")) {
      announceThemeSync(marker === "unknown" ? "unknown" : "local");
      return false;
    }
    if (!explicit && local && local !== value.theme && local !== mirrored) {
      announceThemeSync("conflict");
      return false;
    }
    storage.setItem(WORKBENCH_THEME_STORAGE_KEY, value.theme);
    storage.setItem(MIRRORED_THEME_KEY, value.theme);
    if (storage.getItem(WORKBENCH_THEME_STORAGE_KEY) !== value.theme || storage.getItem(MIRRORED_THEME_KEY) !== value.theme) return false;
    if (typeof window !== "undefined") window.dispatchEvent(new CustomEvent(THEME_CHANGE_EVENT, { detail: value.theme }));
    announceThemeSync("applied");
    return true;
  } catch { return false; }
}

async function readAuthority(isCurrent: () => boolean = () => true): Promise<boolean> {
  const bridge = themeBridge();
  if (!bridge?.readThemeAuthority) return false;
  try {
    const result = await boundedThemeRequest(bridge.readThemeAuthority());
    if (!isCurrent()) return false;
    if (result.code === "local") { localOnly = true; return true; }
    if (result.code === "uninitialized") { authoritySnapshot = null; authorityInitialized = true; return true; }
    if (result.code !== "read" || !validSnapshot(result.snapshot)) return false;
    authorityInitialized = true;
    acceptAuthority(result.snapshot, false, true);
    return true;
  } catch { return false; }
}

/** A desktop choice commits at the Launcher authority before projecting locally. */
export async function requestWorkbenchTheme(theme: WorkbenchTheme): Promise<"applied" | "local" | "unknown" | "unavailable" | "superseded"> {
  const requestSequence = ++localRequestSequence;
  const current = () => requestSequence === localRequestSequence;
  const bridge = themeBridge();
  if (!bridge?.readThemeAuthority || !bridge.setThemeAuthority || localOnly) return writeStoredWorkbenchTheme(theme) ? "applied" : "unavailable";
  const localFallback = (uncertain = false): "local" | "unavailable" | "superseded" => {
    if (!current()) return "superseded";
    const storage = browserStorage();
    if (!storage) return "unavailable";
    try { storage.setItem(MIRRORED_THEME_KEY, uncertain ? "unknown" : "unsynced"); } catch { return "unavailable"; }
    if (!writeStoredWorkbenchTheme(theme)) return "unavailable";
    announceThemeSync(uncertain ? "unknown" : "local");
    return "local";
  };
  if (!authorityInitialized && !await readAuthority(current)) return localFallback();
  if (!current()) return "superseded";
  if (localOnly) return writeStoredWorkbenchTheme(theme) ? "applied" : "unavailable";
  try {
    const storage = browserStorage();
    if (!storage) return "unavailable";
    const beforeValue = storage.getItem(WORKBENCH_THEME_STORAGE_KEY);
    const beforeMirror = storage.getItem(MIRRORED_THEME_KEY);
    const writeId = crypto.randomUUID().replaceAll("-", "");
    let result: ThemeOutcome;
    try { result = await boundedThemeRequest(bridge.setThemeAuthority({ epoch: authoritySnapshot?.epoch ?? "", revision: authoritySnapshot?.revision ?? 0, theme, writeId })); }
    catch { result = { code: "unknown" }; }
    if (!current()) return "superseded";
    if (result.code === "unknown") {
      try {
        const readback = await boundedThemeRequest(bridge.readThemeAuthority());
        if (!current()) return "superseded";
        if (readback.code === "read" && validSnapshot(readback.snapshot) && readback.snapshot.writeId === writeId)
          result = { code: "applied", snapshot: readback.snapshot };
      } catch { /* Never retry an unconfirmed write. */ }
      if (result.code === "unknown") { const fallback = localFallback(true); return fallback === "superseded" ? fallback : "unknown"; }
    }
    if (result.code === "conflict" && result.snapshot) acceptAuthority(result.snapshot, false, true);
    if (result.code !== "applied") return localFallback();
    const currentValue = storage.getItem(WORKBENCH_THEME_STORAGE_KEY);
    const currentMirror = storage.getItem(MIRRORED_THEME_KEY);
    if ((currentValue !== beforeValue || currentMirror !== beforeMirror)
        && (currentValue !== result.snapshot?.theme || currentMirror !== result.snapshot?.theme)) return "local";
    return acceptAuthority(result.snapshot, true, true, true) ? "applied" : "unavailable";
  } catch { return localFallback(); }
}

export function subscribeWorkbenchThemeSync(listener: (state: ThemeSyncState) => void): () => void {
  if (typeof window === "undefined") return () => undefined;
  try {
    const marker = browserStorage()?.getItem(MIRRORED_THEME_KEY);
    if (marker === "unknown") themeSyncState = "unknown";
    else if (marker === "unsynced") themeSyncState = "local";
  } catch { /* Keep the last observed state. */ }
  listener(themeSyncState);
  const handler = (event: Event) => { const state = (event as CustomEvent<unknown>).detail; if (["applied", "local", "conflict", "unknown", "unavailable"].includes(String(state))) listener(state as ThemeSyncState); };
  window.addEventListener(THEME_SYNC_EVENT, handler);
  return () => window.removeEventListener(THEME_SYNC_EVENT, handler);
}

/** The user explicitly chose the currently observed global value. */
export function useAuthorityTheme(): Promise<"applied" | "local" | "unknown" | "unavailable" | "superseded"> {
  return authoritySnapshot ? requestWorkbenchTheme(authoritySnapshot.theme) : Promise.resolve("unavailable");
}

type ThemeStorage = Pick<Storage, "getItem" | "setItem">;
type ThemeDocumentTarget = Pick<Document, "documentElement">;

function browserStorage(): ThemeStorage | null {
  if (typeof window === "undefined") {
    return null;
  }
  try { return window.localStorage; } catch { return null; }
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

export function writeStoredWorkbenchTheme(theme: WorkbenchTheme, storage: ThemeStorage | null = browserStorage()): boolean {
  if (!storage) {
    return false;
  }
  try {
    storage.setItem(WORKBENCH_THEME_STORAGE_KEY, theme);
    if (storage.getItem(WORKBENCH_THEME_STORAGE_KEY) !== theme) return false;
    if (typeof window !== "undefined") window.dispatchEvent(new CustomEvent(THEME_CHANGE_EVENT, { detail: theme }));
    return true;
  } catch {
    return false;
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
  const bridge = themeBridge();
  let unsubscribeBridge: (() => void) | undefined;
  let stopped = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    unsubscribeBridge = bridge?.onAssistantThemeChanged?.((value) => {
      if (!value || typeof value !== "object") return;
      const event = value as { snapshot?: unknown; explicit?: unknown };
      const applied = acceptAuthority(event.snapshot, event.explicit === true, false);
      if (validSnapshot(event.snapshot) && bridge.reportThemeProjection) {
        try { void bridge.reportThemeProjection({ epoch: event.snapshot.epoch, revision: event.snapshot.revision, state: applied ? "applied" : "conflict" }).catch(() => undefined); } catch { /* Readback remains unknown. */ }
      }
    });
    if (bridge?.readThemeAuthority) {
      const refresh = async () => { if (!await readAuthority() && !stopped) timer = setTimeout(() => { void refresh(); }, 1000); };
      void refresh();
    }
  } catch { /* Browser and older desktop shells have no bridge. */ }
  return () => { stopped = true; clearTimeout(timer); window.removeEventListener(THEME_CHANGE_EVENT, local); window.removeEventListener("storage", remote); unsubscribeBridge?.(); };
}

export function nextWorkbenchTheme(theme: WorkbenchTheme): WorkbenchTheme {
  return theme === "dark" ? "light" : "dark";
}

export function applyWorkbenchDocumentTheme(targetDocument: ThemeDocumentTarget, theme: WorkbenchTheme): void {
  targetDocument.documentElement.setAttribute("data-theme", theme);
}
