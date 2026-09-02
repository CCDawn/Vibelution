export type DesktopCliArgs = {
  workspaceRoot: string;
  projectRoot: string;
  configPath: string;
  smoke: boolean;
  openWorkbench: boolean;
  workbenchCloseCanary: boolean;
  lifecycleCommand: string;
};

/**
 * Provenance markers emitted by the Runtime Manager when it hands a lifecycle
 * command to the live Electron shell.  These are deliberately kept separate
 * from the ordinary CLI arguments: the latter are operator input by default.
 */
export type DesktopLifecycleLaunchMetadata = {
  command: string;
  source: string;
  reason: string;
  stopManager: boolean;
  explicitlyForwarded: boolean;
};

const LIFECYCLE_COMMANDS = new Set([
  "start",
  "stop",
  "force-stop",
  "restart",
  "rebuild-and-start",
  "toggle",
  "status",
  "open",
  // Window-level workbench close intent forwarded by the Runtime Manager queue
  // (core/runtime_manager/workbench_controller.py maps close_workbench without
  // stopManager onto this token). It must stay parseable so the desktop lane
  // can route it into the workbench close transaction; it is deliberately NOT
  // an app-shell "stop".
  "close-window"
]);

export function parseDesktopCliArgs(argv: string[]): DesktopCliArgs {
  const result: DesktopCliArgs = {
    workspaceRoot: "",
    projectRoot: "",
    configPath: "",
    smoke: false,
    openWorkbench: false,
    workbenchCloseCanary: false,
    lifecycleCommand: ""
  };
  for (let index = 0; index < argv.length; index += 1) {
    const item = argv[index];
    if (item === "--workspace") {
      result.workspaceRoot = String(argv[index + 1] || "").trim();
      index += 1;
      continue;
    }
    if (item === "--project") {
      result.projectRoot = String(argv[index + 1] || "").trim();
      index += 1;
      continue;
    }
    if (item === "--config") {
      result.configPath = String(argv[index + 1] || "").trim();
      index += 1;
      continue;
    }
    if (item === "--smoke") {
      result.smoke = true;
      continue;
    }
    if (item === "--open-workbench") {
      result.openWorkbench = true;
      continue;
    }
    if (item === "--workbench-close-canary") {
      result.workbenchCloseCanary = true;
      continue;
    }
    const lowered = String(item || "").trim().toLowerCase();
    if (
      lowered === "--lifecycle-source"
      || lowered === "--lifecycle-reason"
      || lowered === "--lifecycle-stop-manager"
    ) {
      if (index + 1 < argv.length && !String(argv[index + 1] || "").trim().startsWith("-")) {
        index += 1;
      }
      continue;
    }
    if (
      lowered.startsWith("--lifecycle-source=")
      || lowered.startsWith("--lifecycle-reason=")
      || lowered.startsWith("--lifecycle-stop-manager=")
    ) {
      continue;
    }
    if (!item.startsWith("-") && LIFECYCLE_COMMANDS.has(lowered) && !result.lifecycleCommand) {
      result.lifecycleCommand = lowered;
    }
  }
  return result;
}

/**
 * Read the optional Runtime Manager forwarding markers from argv/environment.
 *
 * Runtime Manager currently appends the argv form, while the environment form
 * is retained for older/alternate launch paths.  Merely having a lifecycle
 * command is not enough to classify it as forwarded; absent an explicit marker
 * it remains an operator command.
 */
export function parseDesktopLifecycleLaunchMetadata(
  argv: string[],
  env: NodeJS.ProcessEnv = process.env
): DesktopLifecycleLaunchMetadata {
  let source = "";
  let reason = "";
  let stopManager = false;
  let explicitlyForwarded = false;
  let sourceMarkerSeen = false;
  let reasonMarkerSeen = false;
  let stopManagerMarkerSeen = false;

  for (let index = 0; index < argv.length; index += 1) {
    const raw = String(argv[index] || "").trim();
    const lowered = raw.toLowerCase();
    if (lowered === "--lifecycle-source" || lowered.startsWith("--lifecycle-source=")) {
      sourceMarkerSeen = true;
      const inline = raw.slice(raw.indexOf("=") + 1);
      if (lowered === "--lifecycle-source" && index + 1 < argv.length && !String(argv[index + 1] || "").startsWith("-")) {
        source = normalizeLifecycleMarker(argv[index + 1]);
        index += 1;
      } else if (lowered.startsWith("--lifecycle-source=")) {
        source = normalizeLifecycleMarker(inline);
      }
      continue;
    }
    if (lowered === "--lifecycle-reason" || lowered.startsWith("--lifecycle-reason=")) {
      reasonMarkerSeen = true;
      const inline = raw.slice(raw.indexOf("=") + 1);
      if (lowered === "--lifecycle-reason" && index + 1 < argv.length && !String(argv[index + 1] || "").startsWith("-")) {
        reason = normalizeLifecycleMarker(argv[index + 1]);
        index += 1;
      } else if (lowered.startsWith("--lifecycle-reason=")) {
        reason = normalizeLifecycleMarker(inline);
      }
      continue;
    }
    if (lowered === "--lifecycle-stop-manager" || lowered.startsWith("--lifecycle-stop-manager=")) {
      stopManagerMarkerSeen = true;
      explicitlyForwarded = true;
      const inline = raw.slice(raw.indexOf("=") + 1);
      if (lowered === "--lifecycle-stop-manager" && index + 1 < argv.length && !String(argv[index + 1] || "").startsWith("-")) {
        stopManager = parseBooleanLifecycleMarker(argv[index + 1]);
        index += 1;
      } else if (lowered.startsWith("--lifecycle-stop-manager=")) {
        stopManager = parseBooleanLifecycleMarker(inline);
      } else {
        stopManager = true;
      }
    }
  }

  const environmentSource = normalizeLifecycleMarker(env.VIBELUTION_LIFECYCLE_SOURCE);
  const environmentReason = normalizeLifecycleMarker(env.VIBELUTION_LIFECYCLE_REASON);
  const environmentStopManager = env.VIBELUTION_LIFECYCLE_STOP_MANAGER;
  const environmentStopManagerSeen =
    Object.prototype.hasOwnProperty.call(env, "VIBELUTION_LIFECYCLE_STOP_MANAGER")
    && String(environmentStopManager || "").trim().length > 0;
  if (!source && environmentSource) {
    source = environmentSource;
  }
  if (!reason && environmentReason) {
    reason = environmentReason;
  }
  if (!sourceMarkerSeen && !reasonMarkerSeen && !stopManagerMarkerSeen && environmentStopManager !== undefined) {
    stopManager = parseBooleanLifecycleMarker(environmentStopManager);
  }
  explicitlyForwarded ||= Boolean(
    source
    || reason
    || stopManagerMarkerSeen
    || environmentStopManagerSeen
  );

  return {
    command: parseDesktopCliArgs(argv).lifecycleCommand,
    source,
    reason,
    stopManager,
    explicitlyForwarded
  };
}

export function applyDesktopCliToEnvironment(env: NodeJS.ProcessEnv, args: DesktopCliArgs): NodeJS.ProcessEnv {
  return {
    ...env,
    ...(args.workspaceRoot ? { VIBELUTION_WORKSPACE_ROOT: args.workspaceRoot } : {}),
    ...(args.configPath ? { VIBELUTION_CONFIG_PATH: args.configPath } : {}),
    ...(args.smoke ? { VIBELUTION_ELECTRON_SMOKE: "1" } : {}),
    ...(args.workbenchCloseCanary ? { VIBELUTION_ELECTRON_WORKBENCH_CLOSE_CANARY: "1" } : {})
  };
}

function normalizeLifecycleMarker(value: unknown): string {
  return String(value || "").trim().replace(/\s+/g, " ").slice(0, 160);
}

function parseBooleanLifecycleMarker(value: unknown): boolean {
  const normalized = String(value || "").trim().toLowerCase();
  return normalized === "1" || normalized === "true" || normalized === "yes";
}
