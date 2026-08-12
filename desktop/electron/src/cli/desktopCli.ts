export type DesktopCliArgs = {
  workspaceRoot: string;
  configPath: string;
  smoke: boolean;
  openWorkbench: boolean;
  workbenchCloseCanary: boolean;
};

export function parseDesktopCliArgs(argv: string[]): DesktopCliArgs {
  const result: DesktopCliArgs = {
    workspaceRoot: "",
    configPath: "",
    smoke: false,
    openWorkbench: false,
    workbenchCloseCanary: false
  };
  for (let index = 0; index < argv.length; index += 1) {
    const item = argv[index];
    if (item === "--workspace") {
      result.workspaceRoot = String(argv[index + 1] || "").trim();
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
    }
  }
  return result;
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
