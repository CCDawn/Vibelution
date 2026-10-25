import { join, posix } from "node:path";
import { normalizeLaunchRequestId } from "./lifecycle/launchRequestReceipt.js";

export type SingleInstanceDecision =
  | { action: "continue_as_primary" }
  | { action: "focus_existing"; reason: "secondary_launch" };

export type SingleInstanceLifecycleProvenance = "operator" | "forwarded";

export type SingleInstanceLifecycleEnvelope = {
  assistant?: boolean;
  workspaceRoot?: string;
  schemaVersion: 1;
  kind: "vibelution-single-instance";
  projectRoot: string;
  openWorkbench: boolean;
  /**
   * Hidden presentation for branch instance workbench windows (e2e lanes).
   * Traveling inside the envelope (not env) is what lets an already-running
   * shared shell honor a per-request hidden intent.
   */
  hiddenPresentation: boolean;
  launchRequestId?: string;
  lifecycle: {
    command: string;
    provenance: SingleInstanceLifecycleProvenance;
    source?: string;
    reason?: string;
    stopManager?: boolean;
  };
};

export type SingleInstanceLifecycleEnvelopeInput = {
  assistant?: boolean;
  workspaceRoot?: string;
  launchRequestId?: string;
  projectRoot?: string;
  openWorkbench?: boolean;
  hiddenPresentation?: boolean;
  lifecycleCommand?: string;
  lifecycleSource?: string;
  lifecycleReason?: string;
  lifecycleStopManager?: boolean;
  explicitlyForwarded?: boolean;
};

export type SecondInstanceIntent =
  | { action: "open_assistant"; hiddenPresentation: boolean }
  | { action: "handle_deep_link"; rawUrl: string }
  | { action: "apply_project"; projectRoot: string; lifecycleCommand: string; hiddenPresentation: boolean }
  | { action: "lifecycle"; command: string }
  | { action: "open_workbench" }
  | { action: "focus_existing_shell" };

export type SingleInstanceCliIntent = {
  assistant?: boolean;
  workspaceRoot?: string;
  launchRequestId?: string;
  projectRoot: string;
  openWorkbench: boolean;
  hiddenPresentation: boolean;
  lifecycleCommand: string;
};

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
  if (input.assistant && (input.workspaceRoot || String(input.projectRoot || "").trim() || input.openWorkbench || command)) {
    throw new Error("ASSISTANT_MODE_CONFLICT");
  }
  const workspaceRoot = input.workspaceRoot === undefined ? "" : validateSingleInstanceWorkspaceRoot(input.workspaceRoot);
  const source = normalizeSingleInstanceText(input.lifecycleSource);
  const reason = normalizeSingleInstanceText(input.lifecycleReason);
  const explicitlyForwarded = input.explicitlyForwarded === true || Boolean(source) || Boolean(reason);
  return {
    schemaVersion: 1,
    kind: "vibelution-single-instance",
    ...(input.assistant === true ? { assistant: true } : {}),
    ...(workspaceRoot ? { workspaceRoot } : {}),
    projectRoot: String(input.projectRoot || "").trim(),
    openWorkbench: input.openWorkbench === true,
    hiddenPresentation: input.hiddenPresentation === true,
    ...(normalizeLaunchRequestId(input.launchRequestId) ? { launchRequestId: input.launchRequestId } : {}),
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
 * Recover the CLI intent from Electron's structured single-instance payload.
 * Windows may reorder unknown argv switches before emitting second-instance,
 * so argv is not authoritative for project-scoped lifecycle commands.
 */
export function resolveSingleInstanceCliIntent(value: unknown): SingleInstanceCliIntent {
  if (!isSingleInstanceEnvelope(value)) {
    return { projectRoot: "", openWorkbench: false, hiddenPresentation: false, lifecycleCommand: "" };
  }
  if (value.assistant !== undefined && typeof value.assistant !== "boolean") {
    throw new Error("ASSISTANT_MODE_CONFLICT");
  }
  if (value.assistant && (value.workspaceRoot || String(value.projectRoot || "").trim() || value.openWorkbench || value.lifecycle.command.trim())) {
    throw new Error("ASSISTANT_MODE_CONFLICT");
  }
  const workspace = Object.hasOwn(value, "workspaceRoot")
    ? { workspaceRoot: validateSingleInstanceWorkspaceRoot(value.workspaceRoot) }
    : {};
  return {
    ...(value.assistant === true ? { assistant: true } : {}),
    ...workspace,
    projectRoot: typeof value.projectRoot === "string" ? value.projectRoot.trim() : "",
    openWorkbench: value.openWorkbench === true,
    hiddenPresentation: value.hiddenPresentation === true,
    ...(normalizeLaunchRequestId(value.launchRequestId) ? { launchRequestId: value.launchRequestId } : {}),
    lifecycleCommand: value.lifecycle.command.trim().toLowerCase()
  };
}

/**
 * Decode only our versioned envelope. Older Electron processes and unrelated
 * additionalData values deliberately fall back to operator semantics.
 */
export function resolveSingleInstanceProvenance(value: unknown): SingleInstanceLifecycleProvenance {
  if (!isSingleInstanceEnvelope(value)) {
    return "operator";
  }
  return value.lifecycle.provenance === "forwarded" ? "forwarded" : "operator";
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
  assistant?: boolean;
  deepLinkUrl?: string;
  projectRoot?: string;
  openWorkbench?: boolean;
  hiddenPresentation?: boolean;
  lifecycleCommand?: string;
}): SecondInstanceIntent {
  const deepLinkUrl = String(input.deepLinkUrl || "").trim();
  if (input.assistant) {
    if (deepLinkUrl || String(input.projectRoot || "").trim() || input.openWorkbench || String(input.lifecycleCommand || "").trim()) {
      throw new Error("ASSISTANT_MODE_CONFLICT");
    }
    return { action: "open_assistant", hiddenPresentation: input.hiddenPresentation === true };
  }
  if (deepLinkUrl) {
    return { action: "handle_deep_link", rawUrl: deepLinkUrl };
  }
  const projectRoot = String(input.projectRoot || "").trim();
  const lifecycleCommand = String(input.lifecycleCommand || "").trim().toLowerCase();
  if (projectRoot) {
    return {
      action: "apply_project",
      projectRoot,
      lifecycleCommand: lifecycleCommand === "open" ? "" : lifecycleCommand,
      hiddenPresentation: input.hiddenPresentation === true
    };
  }
  if (lifecycleCommand === "open") {
    return { action: "open_workbench" };
  }
  if (lifecycleCommand) {
    return { action: "lifecycle", command: lifecycleCommand };
  }
  if (input.openWorkbench) {
    return { action: "open_workbench" };
  }
  return { action: "focus_existing_shell" };
}

function validateSingleInstanceWorkspaceRoot(value: unknown): string {
  // A Windows drive-relative/root-relative path is not an explicit workspace.
  // Accept POSIX roots and Windows drive/UNC roots regardless of host platform.
  if (typeof value !== "string" || value !== value.trim() || value.includes("\0") ||
      (value !== "" && !posix.isAbsolute(value) && !/^(?:[A-Za-z]:[\\/]|\\\\[^\\]+\\[^\\]+(?:\\|$))/.test(value))) {
    throw new Error("INVALID_WORKSPACE_ROOT");
  }
  return value;
}

function normalizeSingleInstanceText(value: unknown): string {
  return String(value || "").trim().replace(/\s+/g, " ").slice(0, 160);
}

function isObjectRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isSingleInstanceEnvelope(value: unknown): value is SingleInstanceLifecycleEnvelope {
  if (!isObjectRecord(value) || value.schemaVersion !== 1 || value.kind !== "vibelution-single-instance") {
    return false;
  }
  return isObjectRecord(value.lifecycle) && typeof value.lifecycle.command === "string";
}
