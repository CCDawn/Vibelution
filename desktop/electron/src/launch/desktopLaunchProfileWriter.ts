import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { DESKTOP_LAUNCH_PROFILE_FILE } from "./desktopLaunchSettings.js";

export type DesktopLaunchProfile = {
  schemaVersion: 1;
  workspaceRoot: string;
  operatorConfigPath: string;
  pythonPath: string;
};

export type DesktopLaunchProfileInput = {
  workspaceRoot: string;
  operatorConfigPath: string;
  pythonPath: string;
};

export function createDesktopLaunchProfile(input: DesktopLaunchProfileInput): DesktopLaunchProfile {
  return {
    schemaVersion: 1,
    workspaceRoot: input.workspaceRoot.trim(),
    operatorConfigPath: input.operatorConfigPath.trim(),
    pythonPath: input.pythonPath.trim()
  };
}

export function serializeDesktopLaunchProfile(profile: DesktopLaunchProfile): string {
  return `${JSON.stringify(profile, null, 2)}\n`;
}

export function desktopLaunchProfilePath(resourcesRoot: string): string {
  return join(resourcesRoot, DESKTOP_LAUNCH_PROFILE_FILE);
}

export function writeDesktopLaunchProfile(resourcesRoot: string, profile: DesktopLaunchProfile): string {
  const profilePath = desktopLaunchProfilePath(resourcesRoot);
  mkdirSync(resourcesRoot, { recursive: true });
  writeFileSync(profilePath, serializeDesktopLaunchProfile(profile), { encoding: "utf8" });
  return profilePath;
}
