import { pathToFileURL } from "node:url";
import {
  createDesktopLaunchProfile,
  writeDesktopLaunchProfile,
  type DesktopLaunchProfileInput
} from "../launch/desktopLaunchProfileWriter.js";

export type WriteLaunchProfileArgs = DesktopLaunchProfileInput & {
  resourcesRoot: string;
};

const ARGUMENTS: Record<string, keyof WriteLaunchProfileArgs> = {
  "--resources-root": "resourcesRoot",
  "--workspace-root": "workspaceRoot",
  "--operator-config": "operatorConfigPath",
  "--python-path": "pythonPath"
};

export function parseWriteLaunchProfileArgs(argv: string[]): WriteLaunchProfileArgs {
  const result: Partial<WriteLaunchProfileArgs> = {};
  for (let index = 0; index < argv.length; index += 1) {
    const flag = argv[index];
    const key = ARGUMENTS[flag];
    if (!key) {
      throw new Error(`Unknown launch profile argument: ${flag}`);
    }
    const value = String(argv[index + 1] || "").trim();
    if (!value) {
      throw new Error(`Missing value for launch profile argument: ${flag}`);
    }
    result[key] = value;
    index += 1;
  }
  for (const [flag, key] of Object.entries(ARGUMENTS)) {
    if (!result[key]) {
      throw new Error(`Missing required launch profile argument: ${flag}`);
    }
  }
  return result as WriteLaunchProfileArgs;
}

export function runWriteLaunchProfileCli(argv: string[] = process.argv.slice(2)): string {
  const args = parseWriteLaunchProfileArgs(argv);
  return writeDesktopLaunchProfile(
    args.resourcesRoot,
    createDesktopLaunchProfile({
      workspaceRoot: args.workspaceRoot,
      operatorConfigPath: args.operatorConfigPath,
      pythonPath: args.pythonPath
    })
  );
}

function isDirectRun(): boolean {
  const entrypoint = process.argv[1];
  return Boolean(entrypoint) && import.meta.url === pathToFileURL(entrypoint).href;
}

if (isDirectRun()) {
  try {
    const profilePath = runWriteLaunchProfileCli();
    console.log(`Wrote desktop launch profile: ${profilePath}`);
  } catch (error: unknown) {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  }
}
