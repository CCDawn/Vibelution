import { isLauncherAppUrl, resolveLauncherAppUrl } from "../protocol/launcherAppProtocol.js";
import { assertLocalHttpUrl } from "../security/urlPolicy.js";

export function resolveLauncherWindowUrl(env: NodeJS.ProcessEnv): string {
  const explicit = String(env.VIBELUTION_LAUNCHER_URL || "").trim();
  if (explicit) {
    if (isLauncherAppUrl(explicit)) {
      return explicit;
    }
    return assertLocalHttpUrl(explicit, new URL(explicit).origin);
  }
  return resolveLauncherAppUrl();
}

/**
 * Resolve the Workbench app entrypoint (origin only) for persisted/restore
 * flows: bootstrap attach, desktop `open_workbench` actions, lifecycle
 * restart/start and the resolve-workbench bridge. A stale state.json can carry
 * a deep path (e.g. /chat?session=...); restoring must land on the app home,
 * never pin that path (SCI-049 window pinning). User navigation inside the
 * live window is remembered separately via localWorkbenchUrl and keeps its
 * full URL.
 */
function localWorkbenchOriginUrl(rawUrl: string): string {
  const origin = new URL(rawUrl).origin;
  return assertLocalHttpUrl(origin, origin);
}

export function resolveWorkbenchUrl(env: NodeJS.ProcessEnv, workbenchStatusUrl?: string): string {
  const explicit = String(env.VIBELUTION_WORKBENCH_URL || "").trim();
  if (explicit) {
    return localWorkbenchOriginUrl(explicit);
  }
  if (workbenchStatusUrl) {
    return localWorkbenchOriginUrl(workbenchStatusUrl);
  }
  if (env.NODE_ENV === "test" || env.NODE_ENV === "development") {
    return "http://127.0.0.1:8000/";
  }
  throw new Error("Workbench URL is not resolved; start through existing Launcher status or explicit dev override");
}
