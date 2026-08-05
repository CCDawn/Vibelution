import {
  forceStopLauncherBundle,
  restartLauncherBundle,
  startLauncherBundle,
  stopLauncherBundle,
} from "../api/launcher";
import type {
  LauncherControlResponse,
  LauncherOperation,
  RuntimeControlBlockedDetail,
} from "../api/types";

/**
 * Surfaces that can submit workbench lifecycle control (start / stop / force-stop / restart).
 * Keep this narrow: both AppShell power menu and Launcher ops strip must share one request path.
 */
export type WorkbenchLifecycleSource = "app_shell" | "launcher_route";

export type WorkbenchLifecycleRequestOptions = {
  source: WorkbenchLifecycleSource;
  /** Optional override for stop / force-stop X-Vibelution-Launcher-Trigger. */
  trigger?: string;
};

const DEFAULT_STOP_TRIGGERS: Record<WorkbenchLifecycleSource, string> = {
  app_shell: "app_shell_shutdown_button",
  launcher_route: "launcher_route_stop_button",
};

const DEFAULT_FORCE_STOP_TRIGGERS: Record<WorkbenchLifecycleSource, string> = {
  app_shell: "app_shell_force_shutdown_button",
  launcher_route: "launcher_route_force_stop_button",
};

/**
 * Resolve the launcher trigger header for stop / force-stop provenance.
 * Start and restart do not send a trigger header today.
 */
export function resolveWorkbenchLifecycleTrigger(
  operation: LauncherOperation,
  source: WorkbenchLifecycleSource,
  triggerOverride?: string,
): string | undefined {
  const override = String(triggerOverride ?? "").trim();
  if (override) {
    return override;
  }
  if (operation === "stop") {
    return DEFAULT_STOP_TRIGGERS[source];
  }
  if (operation === "force-stop") {
    return DEFAULT_FORCE_STOP_TRIGGERS[source];
  }
  return undefined;
}

/**
 * Single action path for workbench lifecycle control.
 * AppShell overlays and Launcher mutations both call this instead of raw launcher helpers.
 */
export async function requestWorkbenchLifecycleOperation(
  operation: LauncherOperation,
  options: WorkbenchLifecycleRequestOptions,
): Promise<LauncherControlResponse> {
  const trigger = resolveWorkbenchLifecycleTrigger(operation, options.source, options.trigger);
  if (operation === "start") {
    return startLauncherBundle();
  }
  if (operation === "stop") {
    return stopLauncherBundle(trigger ?? DEFAULT_STOP_TRIGGERS[options.source]);
  }
  if (operation === "force-stop") {
    return forceStopLauncherBundle(trigger ?? DEFAULT_FORCE_STOP_TRIGGERS[options.source]);
  }
  return restartLauncherBundle();
}

/**
 * Parse active-work / control-blocked detail from fetchJson error payloads.
 * Shared so AppShell overlay copy and any future Launcher handling stay aligned.
 */
export function parseRuntimeControlBlockedDetail(error: unknown): RuntimeControlBlockedDetail | null {
  if (!(error instanceof Error)) {
    return null;
  }
  try {
    const parsed = JSON.parse(error.message) as { detail?: RuntimeControlBlockedDetail };
    const detail = parsed?.detail;
    return detail && typeof detail === "object" ? detail : null;
  } catch {
    return null;
  }
}

export function isActiveWorkStopBlocked(
  detail: RuntimeControlBlockedDetail | null | undefined,
): detail is RuntimeControlBlockedDetail {
  const code = String(detail?.code ?? "").trim();
  return code === "active_work_stop_blocked" || code === "active_work_requires_confirmation";
}

export function isActiveWorkRestartBlocked(
  detail: RuntimeControlBlockedDetail | null | undefined,
): detail is RuntimeControlBlockedDetail {
  const code = String(detail?.code ?? "").trim();
  return code === "active_work_restart_blocked" || code === "active_work_requires_confirmation";
}

/** Human-readable active-work summary for blocked stop/restart messaging (no raw secret data). */
export function formatActiveWorkRunsDetail(
  runs: RuntimeControlBlockedDetail["activeWorkRuns"] | undefined,
): string {
  return (runs ?? [])
    .map((item) => [item?.kind, item?.status, item?.runId || item?.sessionId].filter(Boolean).join(" · "))
    .filter(Boolean)
    .join(" · ");
}
