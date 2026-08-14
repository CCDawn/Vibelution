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

export function resolveWorkbenchUrl(env: NodeJS.ProcessEnv, workbenchStatusUrl?: string): string {
  const explicit = String(env.VIBELUTION_WORKBENCH_URL || "").trim();
  if (explicit) {
    return assertLocalHttpUrl(explicit, new URL(explicit).origin);
  }
  if (workbenchStatusUrl) {
    return assertLocalHttpUrl(workbenchStatusUrl, new URL(workbenchStatusUrl).origin);
  }
  if (env.NODE_ENV === "test" || env.NODE_ENV === "development") {
    return "http://127.0.0.1:8000/";
  }
  throw new Error("Workbench URL is not resolved; start through existing Launcher status or explicit dev override");
}
