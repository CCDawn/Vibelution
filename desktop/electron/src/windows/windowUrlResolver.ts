import { assertLocalHttpUrl } from "../security/urlPolicy.js";

export function resolveLauncherUrl(env: NodeJS.ProcessEnv, launcherStatusUrl?: string): string {
  const explicit = String(env.VIBELUTION_LAUNCHER_URL || "").trim();
  if (explicit) {
    return assertLocalHttpUrl(explicit, new URL(explicit).origin);
  }
  if (launcherStatusUrl) {
    return assertLocalHttpUrl(launcherStatusUrl, new URL(launcherStatusUrl).origin);
  }
  if (env.NODE_ENV === "test" || env.NODE_ENV === "development") {
    return "http://127.0.0.1:8765/launcher";
  }
  throw new Error("Launcher URL is not resolved; start through existing Launcher status or explicit dev override");
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
