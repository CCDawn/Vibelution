import type { LauncherComponentState, LauncherOperation, LauncherStatus } from "../api/types";
import type { BrowserTelemetryEventInput } from "./browserTelemetry";

type ProjectCloseGuardSurface = "launcher" | "workbench";

type ProjectCloseGuardOptions = {
  lifecycleOperationInFlight?: boolean;
};

type WorkbenchCloseGuardOptions = {
  shutdownRequested: boolean;
  restartRequested: boolean;
  runtimeControllerState: string;
  frontendRefreshRequested?: boolean;
  controlledLifecycleOperationInFlight?: boolean;
};

type CookieLikeDocument = {
  cookie: string;
};

type DesktopShellLike = {
  vibelutionLauncher?: unknown;
};

const CONTROLLED_LIFECYCLE_COOKIE = "vibelution_lifecycle_operation";
const CONTROLLED_LIFECYCLE_WINDOW_MS = 120_000;
/**
 * Synchronous unload pass for intentional frontend refresh / recovery reloads.
 * React state (`frontendRefreshRequested`) is too late for the event handler.
 * Also: the beforeunload *listener* must stay mounted (ref-backed decision), not
 * re-bound every poll — otherwise Edge shows "重新加载应用?" then tears the
 * listener down mid-dialog and the prompt flashes away before the user can click.
 *
 * sessionStorage mirrors the in-memory flag so a late module re-eval or a second
 * listener still sees the one-shot pass within the expire window.
 */
let allowNextWorkbenchUnload = false;
let allowNextWorkbenchUnloadToken = 0;
const ALLOW_NEXT_UNLOAD_EXPIRE_MS = 5_000;
const ALLOW_NEXT_UNLOAD_STORAGE_KEY = "vibelution.allow_next_window_unload";

function writeAllowNextUnloadStorage(armedAtMs: number) {
  try {
    if (typeof sessionStorage === "undefined") {
      return;
    }
    sessionStorage.setItem(ALLOW_NEXT_UNLOAD_STORAGE_KEY, String(Math.max(0, Math.round(armedAtMs))));
  } catch {
    // Private mode / blocked storage — memory flag still works in the same document.
  }
}

function clearAllowNextUnloadStorage() {
  try {
    if (typeof sessionStorage === "undefined") {
      return;
    }
    sessionStorage.removeItem(ALLOW_NEXT_UNLOAD_STORAGE_KEY);
  } catch {
    // ignore
  }
}

function readAllowNextUnloadStorageActive(nowMs = Date.now()) {
  try {
    if (typeof sessionStorage === "undefined") {
      return false;
    }
    const raw = sessionStorage.getItem(ALLOW_NEXT_UNLOAD_STORAGE_KEY);
    const armedAt = Number(raw);
    return Number.isFinite(armedAt) && armedAt > 0 && nowMs >= armedAt && nowMs - armedAt <= ALLOW_NEXT_UNLOAD_EXPIRE_MS;
  } catch {
    return false;
  }
}

function isUnloadAllowanceActive(nowMs = Date.now()) {
  return allowNextWorkbenchUnload || readAllowNextUnloadStorageActive(nowMs);
}
const OPEN_PROJECT_STATES = new Set(["ready", "open", "partial", "starting", "running", "restarting", "opening"]);
const OPEN_PHASE_TOKENS = ["start", "open", "restart", "queue", "processing"];
const RUNTIME_COMPONENT_STATES = new Set([
  "alive",
  "healthy",
  "listening",
  "open",
  "ready",
  "running",
  "starting",
  "verified",
]);

function normalizeState(value: unknown) {
  return String(value ?? "").trim().toLowerCase();
}

function includesLifecycleToken(value: string, tokens: string[]) {
  return tokens.some((token) => value.includes(token));
}

function isRunningComponent(component: LauncherComponentState | undefined) {
  if (!component) {
    return false;
  }
  const state = normalizeState(component.state);
  return Boolean(component.ok || component.pid > 0 || RUNTIME_COMPONENT_STATES.has(state));
}

function componentById(status: LauncherStatus | undefined | null, id: string) {
  return (status?.projectBundle?.components ?? []).find((component) => component.id === id);
}

function cookieDocument(documentLike?: CookieLikeDocument): CookieLikeDocument | null {
  if (documentLike) {
    return documentLike;
  }
  if (typeof document === "undefined") {
    return null;
  }
  return document;
}

function encodeControlledLifecycleValue(operation: LauncherOperation, atMs: number) {
  return `${operation}:${Math.max(0, Math.round(atMs))}`;
}

function readCookieValue(cookieText: string, name: string) {
  const prefix = `${name}=`;
  return cookieText
    .split(";")
    .map((item) => item.trim())
    .find((item) => item.startsWith(prefix))
    ?.slice(prefix.length) ?? "";
}

export function shouldBlockProjectWindowClose(
  status: LauncherStatus | undefined | null,
  options: ProjectCloseGuardOptions = {},
) {
  if (options.lifecycleOperationInFlight || !status) {
    return false;
  }

  const bundle = status.projectBundle;
  const proof = status.lifecycleProof;
  const desiredState = normalizeState(bundle?.desiredState || proof?.desiredState);
  const observedState = normalizeState(bundle?.observedState || proof?.observedState);
  const overallState = normalizeState(proof?.overallState || bundle?.overallState);
  const phase = normalizeState(bundle?.phase || proof?.phase || status.launcher?.phase);
  const backendComponent = componentById(status, "backend");
  const browserComponent = componentById(status, "browser");
  const backendRunning = Boolean(
    bundle?.backend?.alive
      || bundle?.backend?.healthy
      || bundle?.backend?.portListening
      || isRunningComponent(backendComponent),
  );
  const browserRunning = Boolean(bundle?.browser?.alive || isRunningComponent(browserComponent));

  if (backendRunning || browserRunning) {
    return true;
  }

  if (
    OPEN_PROJECT_STATES.has(overallState)
      || observedState === "open"
      || (desiredState === "open" && observedState !== "closed" && overallState !== "failed")
  ) {
    return true;
  }

  return includesLifecycleToken(phase, OPEN_PHASE_TOKENS);
}

export function shouldBlockWorkbenchWindowClose(options: WorkbenchCloseGuardOptions) {
  if (
    options.frontendRefreshRequested
      || isUnloadAllowanceActive()
      || options.shutdownRequested
      || options.restartRequested
      || options.controlledLifecycleOperationInFlight
  ) {
    return false;
  }
  return normalizeState(options.runtimeControllerState) !== "closing";
}

/** Arm a one-shot pass so the next navigation/reload skips the project-close guard. */
export function allowNextWorkbenchWindowUnload() {
  allowNextWorkbenchUnload = true;
  const token = ++allowNextWorkbenchUnloadToken;
  const armedAtMs = Date.now();
  writeAllowNextUnloadStorage(armedAtMs);
  if (typeof globalThis.setTimeout === "function") {
    globalThis.setTimeout(() => {
      if (token === allowNextWorkbenchUnloadToken) {
        allowNextWorkbenchUnload = false;
        clearAllowNextUnloadStorage();
      }
    }, ALLOW_NEXT_UNLOAD_EXPIRE_MS);
  }
}

/** True if a one-shot unload pass is armed (does not consume). */
export function isNextWorkbenchWindowUnloadAllowed() {
  return isUnloadAllowanceActive();
}

/**
 * Consume the one-shot unload pass inside `beforeunload`.
 * Returns true when this unload should proceed without the project-close prompt.
 */
export function consumeNextWorkbenchWindowUnloadAllowance() {
  if (!isUnloadAllowanceActive()) {
    return false;
  }
  allowNextWorkbenchUnload = false;
  allowNextWorkbenchUnloadToken += 1;
  clearAllowNextUnloadStorage();
  return true;
}

/** Test / recovery helper: clear any pending one-shot unload pass. */
export function clearNextWorkbenchWindowUnloadAllowance() {
  allowNextWorkbenchUnload = false;
  allowNextWorkbenchUnloadToken += 1;
  clearAllowNextUnloadStorage();
}

export function isElectronDesktopShell(globalLike: DesktopShellLike = globalThis as DesktopShellLike) {
  return typeof globalLike.vibelutionLauncher === "object" && globalLike.vibelutionLauncher !== null;
}

export function shouldArmBrowserProjectCloseGuard(options: {
  closeBlocked: boolean;
  electronDesktopShell?: boolean;
}) {
  return options.closeBlocked && !options.electronDesktopShell;
}

export function markControlledProjectLifecycleOperation(
  operation: LauncherOperation,
  documentLike?: CookieLikeDocument,
  atMs = Date.now(),
) {
  if (operation !== "stop" && operation !== "restart") {
    return;
  }
  const target = cookieDocument(documentLike);
  if (!target) {
    return;
  }
  target.cookie = `${CONTROLLED_LIFECYCLE_COOKIE}=${encodeURIComponent(encodeControlledLifecycleValue(operation, atMs))}; Max-Age=120; Path=/; SameSite=Lax`;
}

export function clearControlledProjectLifecycleOperation(documentLike?: CookieLikeDocument) {
  const target = cookieDocument(documentLike);
  if (!target) {
    return;
  }
  target.cookie = `${CONTROLLED_LIFECYCLE_COOKIE}=; Max-Age=0; Path=/; SameSite=Lax`;
}

export function hasRecentControlledProjectLifecycleOperation(
  documentLike?: CookieLikeDocument,
  nowMs = Date.now(),
) {
  const target = cookieDocument(documentLike);
  if (!target) {
    return false;
  }
  const raw = decodeURIComponent(readCookieValue(target.cookie, CONTROLLED_LIFECYCLE_COOKIE));
  const [operation, timestampText] = raw.split(":");
  if (operation !== "stop" && operation !== "restart") {
    return false;
  }
  const timestamp = Number(timestampText);
  return Number.isFinite(timestamp) && timestamp > 0 && nowMs >= timestamp && nowMs - timestamp <= CONTROLLED_LIFECYCLE_WINDOW_MS;
}

export function projectWindowCloseGuardMessage(lang: "zh" | "en" | string, surface: ProjectCloseGuardSurface) {
  if (lang === "en") {
    return surface === "launcher"
      ? "The project is still running. Stop the workbench first, then close the Launcher."
      : "The project is still running. Use the workbench power menu to stop it before closing this window.";
  }
  return surface === "launcher"
    ? "项目仍在运行，不能直接关闭 Launcher。请先点击「停止」，等待项目关闭后再关闭窗口。"
    : "项目仍在运行，不能直接关闭工作台窗口。请先通过电源菜单停止工作台。";
}

export function applyBeforeUnloadProjectCloseGuard(event: BeforeUnloadEvent, message: string) {
  event.preventDefault();
  event.returnValue = message;
  return message;
}

/**
 * Shared beforeunload decision for workbench surfaces.
 * Intentional refresh/recovery must call {@link allowNextWorkbenchWindowUnload} first.
 */
export function handleWorkbenchBeforeUnload(
  event: BeforeUnloadEvent,
  options: {
    message: string;
    controlledLifecycleOperationInFlight?: boolean;
    closeBlocked: boolean;
  },
): boolean {
  if (consumeNextWorkbenchWindowUnloadAllowance()) {
    return false;
  }
  if (options.controlledLifecycleOperationInFlight || !options.closeBlocked) {
    return false;
  }
  applyBeforeUnloadProjectCloseGuard(event, options.message);
  return true;
}

export function buildProjectWindowCloseBlockedTelemetry(options: {
  surface: ProjectCloseGuardSurface;
  status?: LauncherStatus | null;
  runtimeControllerState?: string;
}): BrowserTelemetryEventInput {
  const bundle = options.status?.projectBundle;
  const proof = options.status?.lifecycleProof;
  return {
    phase: "lifecycle",
    eventCode: options.surface === "launcher"
      ? "launcher.window_close.blocked_project_running"
      : "browser.window_close.blocked_project_running",
    message: options.surface === "launcher"
      ? "Launcher window close was blocked because the managed project is still running."
      : "Workbench window close was blocked because the managed project is still running.",
    level: "warning",
    fields: {
      guard: "project_running_close_guard",
      surface: options.surface,
      overallState: proof?.overallState ?? bundle?.overallState ?? "",
      desiredState: bundle?.desiredState ?? proof?.desiredState ?? "",
      observedState: bundle?.observedState ?? proof?.observedState ?? "",
      phase: bundle?.phase ?? proof?.phase ?? "",
      backendAlive: Boolean(bundle?.backend?.alive),
      backendHealthy: Boolean(bundle?.backend?.healthy),
      backendPortListening: Boolean(bundle?.backend?.portListening),
      browserAlive: Boolean(bundle?.browser?.alive),
      runtimeControllerState: options.runtimeControllerState ?? "",
    },
  };
}
