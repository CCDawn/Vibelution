export type DesktopCliArgs = {
  workspaceRoot: string;
  configPath: string;
  smoke: boolean;
};

export function parseDesktopCliArgs(argv: string[]): DesktopCliArgs {
  const result: DesktopCliArgs = {
    workspaceRoot: "",
    configPath: "",
    smoke: false
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
    }
  }
  return result;
}

export function applyDesktopCliToEnvironment(env: NodeJS.ProcessEnv, args: DesktopCliArgs): NodeJS.ProcessEnv {
  return {
    ...env,
    ...(args.workspaceRoot ? { VIBELUTION_WORKSPACE_ROOT: args.workspaceRoot } : {}),
    ...(args.configPath ? { VIBELUTION_CONFIG_PATH: args.configPath } : {}),
    ...(args.smoke ? { VIBELUTION_ELECTRON_SMOKE: "1" } : {})
  };
}
