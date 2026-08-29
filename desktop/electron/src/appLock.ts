import { join } from "node:path";

export type SingleInstanceDecision =
  | { action: "continue_as_primary" }
  | { action: "focus_existing"; reason: "secondary_launch" };

export type SingleInstanceLifecycleProvenance = "operator" | "forwarded";

export type SingleInstanceLifecycleEnvelope = {
  schemaVersion: 1;
  kind: "vibelution-single-instance";
  lifecycle: {
    command: string;
    provenance: SingleInstanceLifecycleProvenance;
    source?: string;
    reason?: string;
    stopManager?: boolean;
  };
};

export type SingleInstanceLifecycleEnvelopeInput = {
  lifecycleCommand?: string;
  lifecycleSource?: string;
  lifecycleReason?: string;
  lifecycleStopManager?: boolean;
  explicitlyForwarded?: boolean;
};

export type SecondInstanceIntent =
  | { action: "handle_deep_link"; rawUrl: string }
  | { action: "apply_project"; projectRoot: string; lifecycleCommand: string }
  | { action: "lifecycle"; command: string }
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

/**
 * Build the structured payload passed through Electron's single-instance
 * channel. Ordinary CLI launches are operator-originated; only a launch that
 * carries an explicit Runtime Manager marker is classified as forwarded.
 */
export function createSingleInstanceEnvelope(
  input: SingleInstanceLifecycleEnvelopeInput = {}
): SingleInstanceLifecycleEnvelope {
  const command = normalizeSingleInstanceText(input.lifecycleCommand);
  const source = normalizeSingleInstanceText(input.lifecycleSource);
  const reason = normalizeSingleInstanceText(input.lifecycleReason);
  const explicitlyForwarded = input.explicitlyForwarded === true || Boolean(source) || Boolean(reason);
  return {
    schemaVersion: 1,
    kind: "vibelution-single-instance",
    lifecycle: {
      command,
      provenance: explicitlyForwarded ? "forwarded" : "operator",
      ...(explicitlyForwarded && source ? { source } : {}),
      ...(explicitlyForwarded && reason ? { reason } : {}),
      ...(explicitlyForwarded && input.lifecycleStopManager !== undefined
        ? { stopManager: Boolean(input.lifecycleStopManager) }
        : {})
    }
  };
}

/**
 * Decode only our versioned envelope. Older Electron processes and unrelated
 * additionalData values deliberately fall back to operator semantics.
 */
export function resolveSingleInstanceProvenance(value: unknown): SingleInstanceLifecycleProvenance {
  if (!isObjectRecord(value) || value.schemaVersion !== 1 || value.kind !== "vibelution-single-instance") {
    return "operator";
  }
  const lifecycle = value.lifecycle;
  if (!isObjectRecord(lifecycle) || typeof lifecycle.command !== "string") {
    return "operator";
  }
  return lifecycle.provenance === "forwarded" ? "forwarded" : "operator";
}

export function shouldRunDesktopWhenReadyHandlers(input: {
  lockAction: SingleInstanceDecision["action"];
  smoke: boolean;
  workbenchCloseCanary?: boolean;
}): boolean {
  if (input.smoke || input.workbenchCloseCanary) {
    return true;
  }
  return input.lockAction === "continue_as_primary";
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
  lifecycleCommand?: string;
}): SecondInstanceIntent {
  const deepLinkUrl = String(input.deepLinkUrl || "").trim();
  if (deepLinkUrl) {
    return { action: "handle_deep_link", rawUrl: deepLinkUrl };
  }
  const projectRoot = String(input.projectRoot || "").trim();
  const lifecycleCommand = String(input.lifecycleCommand || "").trim().toLowerCase();
  if (projectRoot) {
    return {
      action: "apply_project",
      projectRoot,
      lifecycleCommand: lifecycleCommand === "open" ? "" : lifecycleCommand
    };
  }
  if (lifecycleCommand === "open" || input.openWorkbench) {
    return { action: "open_workbench" };
  }
  if (lifecycleCommand) {
    return { action: "lifecycle", command: lifecycleCommand };
  }
  return { action: "focus_existing_shell" };
}

function normalizeSingleInstanceText(value: unknown): string {
  return String(value || "").trim().replace(/\s+/g, " ").slice(0, 160);
}

function isObjectRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
