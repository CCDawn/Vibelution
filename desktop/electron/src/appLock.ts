import { join } from "node:path";

export type SingleInstanceDecision =
  | { action: "continue_as_primary" }
  | { action: "focus_existing"; reason: "secondary_launch" };

export type SecondInstanceIntent =
  | { action: "handle_deep_link"; rawUrl: string }
  | { action: "apply_project"; projectRoot: string }
  | { action: "open_workbench" }
  | { action: "focus_existing_shell" };

export type PinSharedDesktopShellUserDataResult = {
  pinned: boolean;
  userDataRoot: string;
};

export const DESKTOP_SHELL_USER_DATA_PRODUCT = "Vibelution";
export const DESKTOP_SHELL_USER_DATA_DIR_NAME = "DesktopShell";

type DesktopAppPathSetter = {
  setPath(name: string, path: string): void;
};

export function singleInstanceDecision(hasLock: boolean): SingleInstanceDecision {
  return hasLock ? { action: "continue_as_primary" } : { action: "focus_existing", reason: "secondary_launch" };
}

export function shouldPinSharedDesktopShellUserData(options: {
  smoke: boolean;
  workbenchCloseCanary?: boolean;
}): boolean {
  return !options.smoke && !options.workbenchCloseCanary;
}

export function resolveDesktopShellUserDataRoot(env: NodeJS.ProcessEnv = process.env): string {
  const localAppData = String(env.LOCALAPPDATA || "").trim();
  const home = String(env.USERPROFILE || env.HOME || "").trim();
  const root = localAppData || (home ? join(home, "AppData", "Local") : "");
  if (!root) {
    return "";
  }
  return join(root, DESKTOP_SHELL_USER_DATA_PRODUCT, DESKTOP_SHELL_USER_DATA_DIR_NAME);
}

export function pinSharedDesktopShellUserData(
  appLike: DesktopAppPathSetter,
  input: { smoke: boolean; workbenchCloseCanary?: boolean; env?: NodeJS.ProcessEnv }
): PinSharedDesktopShellUserDataResult {
  if (!shouldPinSharedDesktopShellUserData({ smoke: input.smoke, workbenchCloseCanary: input.workbenchCloseCanary })) {
    return { pinned: false, userDataRoot: "" };
  }
  const userDataRoot = resolveDesktopShellUserDataRoot(input.env ?? process.env);
  if (!userDataRoot) {
    return { pinned: false, userDataRoot: "" };
  }
  appLike.setPath("userData", userDataRoot);
  return { pinned: true, userDataRoot };
}

export function resolveSecondInstanceIntent(input: {
  deepLinkUrl?: string;
  projectRoot?: string;
  openWorkbench?: boolean;
}): SecondInstanceIntent {
  const deepLinkUrl = String(input.deepLinkUrl || "").trim();
  if (deepLinkUrl) {
    return { action: "handle_deep_link", rawUrl: deepLinkUrl };
  }
  const projectRoot = String(input.projectRoot || "").trim();
  if (projectRoot) {
    return { action: "apply_project", projectRoot };
  }
  if (input.openWorkbench) {
    return { action: "open_workbench" };
  }
  return { action: "focus_existing_shell" };
}
