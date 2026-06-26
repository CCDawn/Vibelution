import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export type DesktopPaths = {
  schemaVersion: 1;
  desktopBundleRoot: string;
  resourcesRoot: string;
  workspaceRoot: string;
  userDataRoot: string;
};

export type DesktopPathInput = {
  importMetaUrl: string;
  resourcesRoot: string;
  userDataRoot: string;
  workspaceRoot: string;
};

export function resolveDesktopBundleRoot(importMetaUrl: string): string {
  return dirname(fileURLToPath(importMetaUrl));
}

export function createDesktopPaths(input: DesktopPathInput): DesktopPaths {
  const workspaceRoot = resolve(input.workspaceRoot);
  return {
    schemaVersion: 1,
    desktopBundleRoot: resolveDesktopBundleRoot(input.importMetaUrl),
    resourcesRoot: resolve(input.resourcesRoot),
    workspaceRoot,
    userDataRoot: resolve(input.userDataRoot)
  };
}

export function resolvePreloadPath(paths: DesktopPaths): string {
  return resolve(paths.desktopBundleRoot, "preload.cjs");
}

export function resolveWorkspaceRuntimeDir(paths: DesktopPaths): string {
  return resolve(paths.workspaceRoot, ".runtime", "launcher");
}

export function resolveWorkspaceIconPath(paths: DesktopPaths): string {
  return resolve(paths.workspaceRoot, "assets", "icons", "vibelution.ico");
}
