import { readFileSync } from "node:fs";
import { join } from "node:path";
import type { DesktopCliArgs } from "../cli/desktopCli.js";

export const DESKTOP_LAUNCH_PROFILE_FILE = "vibelution-launch-profile.json";

export type DesktopLaunchSettings = {
  schemaVersion: 1;
  workspaceRoot: string;
  configPath: string;
  pythonPath: string;
  profilePath: string;
  profileError: string;
  searchedProfilePaths: string[];
};

type DesktopLaunchProfile = {
  schemaVersion?: unknown;
  workspaceRoot?: unknown;
  configPath?: unknown;
  operatorConfigPath?: unknown;
  pythonPath?: unknown;
};

export type DesktopLaunchSettingsInput = {
  env: NodeJS.ProcessEnv;
  cliArgs: DesktopCliArgs;
  userDataRoot: string;
  resourcesRoot: string;
  readTextFile?: (path: string) => string | null;
};

type LoadedLaunchProfile = {
  profile: DesktopLaunchProfile | null;
  path: string;
  error: string;
};

export function resolveDesktopLaunchSettings(input: DesktopLaunchSettingsInput): DesktopLaunchSettings {
  const searchedProfilePaths = launchProfilePaths(input.userDataRoot, input.resourcesRoot);
  const loadedProfile = loadFirstReadableLaunchProfile(searchedProfilePaths, input.readTextFile ?? readTextFileIfPresent);
  const profile = loadedProfile.profile;

  const profileWorkspaceRoot = readProfileString(profile?.workspaceRoot);
  const profileConfigPath = readProfileString(profile?.operatorConfigPath) || readProfileString(profile?.configPath);
  const profilePythonPath = readProfileString(profile?.pythonPath);

  return {
    schemaVersion: 1,
    workspaceRoot: firstString(input.cliArgs.workspaceRoot, input.env.VIBELUTION_WORKSPACE_ROOT, profileWorkspaceRoot),
    configPath: firstString(input.cliArgs.configPath, input.env.VIBELUTION_CONFIG_PATH, profileConfigPath),
    pythonPath: firstString(input.env.VIBELUTION_PYTHON_PATH, input.env.PYTHON, profilePythonPath),
    profilePath: loadedProfile.path,
    profileError: loadedProfile.error,
    searchedProfilePaths
  };
}

export function applyDesktopLaunchSettingsToEnvironment(
  env: NodeJS.ProcessEnv,
  settings: DesktopLaunchSettings
): NodeJS.ProcessEnv {
  const nextEnv: NodeJS.ProcessEnv = { ...env };
  if (settings.workspaceRoot) {
    nextEnv.VIBELUTION_WORKSPACE_ROOT = settings.workspaceRoot;
  }
  if (settings.configPath) {
    nextEnv.VIBELUTION_CONFIG_PATH = settings.configPath;
  }
  if (settings.pythonPath) {
    nextEnv.VIBELUTION_PYTHON_PATH = settings.pythonPath;
    if (!nextEnv.PYTHON) {
      nextEnv.PYTHON = settings.pythonPath;
    }
  }
  return nextEnv;
}

function launchProfilePaths(userDataRoot: string, resourcesRoot: string): string[] {
  return [join(userDataRoot, DESKTOP_LAUNCH_PROFILE_FILE), join(resourcesRoot, DESKTOP_LAUNCH_PROFILE_FILE)];
}

function loadFirstReadableLaunchProfile(
  profilePaths: string[],
  readTextFile: (path: string) => string | null
): LoadedLaunchProfile {
  let firstError = "";
  for (const profilePath of profilePaths) {
    const text = safeReadTextFile(profilePath, readTextFile);
    if (text === null) {
      continue;
    }
    if (text.error) {
      firstError ||= text.error;
      continue;
    }
    try {
      const parsed = JSON.parse(stripJsonBom(text.content)) as unknown;
      if (!isObjectRecord(parsed)) {
        firstError ||= "invalid_launch_profile_shape";
        continue;
      }
      return {
        profile: parsed,
        path: profilePath,
        error: firstError
      };
    } catch {
      firstError ||= "invalid_launch_profile_json";
    }
  }
  return {
    profile: null,
    path: "",
    error: firstError
  };
}

function safeReadTextFile(
  path: string,
  readTextFile: (path: string) => string | null
): { content: string; error: "" } | { content: ""; error: string } | null {
  try {
    const content = readTextFile(path);
    return content === null ? null : { content, error: "" };
  } catch {
    return { content: "", error: "launch_profile_read_failed" };
  }
}

function readTextFileIfPresent(path: string): string | null {
  try {
    return readFileSync(path, "utf-8");
  } catch (error: unknown) {
    const code = isObjectRecord(error) ? readProfileString(error.code) : "";
    if (code === "ENOENT" || code === "ENOTDIR") {
      return null;
    }
    throw error;
  }
}

function stripJsonBom(content: string): string {
  return content.charCodeAt(0) === 0xfeff ? content.slice(1) : content;
}

function isObjectRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function readProfileString(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function firstString(...values: Array<string | undefined>): string {
  for (const value of values) {
    const normalized = readProfileString(value);
    if (normalized) {
      return normalized;
    }
  }
  return "";
}
