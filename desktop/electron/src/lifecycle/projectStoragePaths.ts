import { existsSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";

const FNV32_OFFSET = 2166136261;
const FNV32_PRIME = 16777619;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function normalizeInstanceKey(projectRoot: string): string {
  const resolved = resolve(projectRoot.trim());
  return process.platform === "win32" ? resolved.toLowerCase() : resolved;
}

export function instanceIdForProject(projectRoot: string): string {
  const bytes = Buffer.from(normalizeInstanceKey(projectRoot), "utf8");
  let digest = FNV32_OFFSET;
  for (const byte of bytes) {
    digest ^= byte;
    digest = Math.imul(digest, FNV32_PRIME) >>> 0;
  }
  return digest.toString(16).padStart(8, "0");
}

export function readProjectId(projectRoot: string): string {
  const identityPath = join(projectRoot, ".vibelution", "project.json");
  try {
    const payload = JSON.parse(readFileSync(identityPath, "utf8")) as unknown;
    if (!isRecord(payload)) {
      return "";
    }
    return typeof payload.projectId === "string" ? payload.projectId.trim().toLowerCase() : "";
  } catch {
    return "";
  }
}

export function resolveProjectsHome(): string {
  const override = String(process.env.VIBELUTION_PROJECTS_HOME || "").trim();
  if (override) {
    return resolve(override);
  }
  const localAppData = String(process.env.LOCALAPPDATA || "").trim();
  const root = localAppData ? resolve(localAppData) : join(resolve(process.env.USERPROFILE || ""), "AppData", "Local");
  return join(root, "Vibelution", "projects");
}

export function resolveRuntimeManagerDir(workspaceRoot: string): string {
  const checkoutDir = join(resolve(workspaceRoot), ".runtime", "runtime-manager");
  const projectId = readProjectId(workspaceRoot);
  if (!projectId) {
    return checkoutDir;
  }
  const instanceId = instanceIdForProject(workspaceRoot);
  const migratedDir = join(resolveProjectsHome(), projectId, "instances", instanceId, "runtime", "runtime-manager");
  const migratedState = join(migratedDir, "state.json");
  const checkoutState = join(checkoutDir, "state.json");
  if (existsSync(migratedState)) {
    return migratedDir;
  }
  if (existsSync(checkoutState)) {
    return checkoutDir;
  }
  return existsSync(migratedDir) ? migratedDir : checkoutDir;
}

export const DESKTOP_SHELL_OWNER_FILE = "desktop_shell_owner.json";

export function resolveCanonicalRuntimeHome(workspaceRoot: string): string | null {
  const projectId = readProjectId(workspaceRoot);
  if (!projectId) {
    return null;
  }
  return join(resolveProjectsHome(), projectId, "instances", instanceIdForProject(workspaceRoot), "runtime");
}

export function resolveLocalAppDataRoot(): string {
  const localAppData = String(process.env.LOCALAPPDATA || "").trim();
  return localAppData
    ? resolve(localAppData)
    : join(resolve(process.env.USERPROFILE || ""), "AppData", "Local");
}

export function resolveConfigHome(): string {
  const override = String(process.env.VIBELUTION_CONFIG_HOME || "").trim();
  if (override) {
    return resolve(override);
  }
  return join(resolve(process.env.USERPROFILE || ""), "Documents", "Vibelution", "config");
}

export function resolveDataHomeForProject(projectRoot: string): string {
  const projectId = readProjectId(projectRoot);
  const instanceId = instanceIdForProject(projectRoot);
  if (projectId) {
    return join(resolveProjectsHome(), projectId, "instances", instanceId, "data");
  }
  return join(resolveLocalAppDataRoot(), "Vibelution", "slots", instanceId, "data");
}

export function resolveCheckoutRuntimeHome(workspaceRoot: string): string {
  return join(resolve(workspaceRoot), ".runtime");
}

export function resolveLauncherRuntimeDir(workspaceRoot: string): string {
  const checkoutDir = join(resolveCheckoutRuntimeHome(workspaceRoot), "launcher");
  const canonicalHome = resolveCanonicalRuntimeHome(workspaceRoot);
  if (!canonicalHome) {
    return checkoutDir;
  }
  const migratedDir = join(canonicalHome, "launcher");
  const migratedState = join(migratedDir, "state.json");
  const checkoutState = join(checkoutDir, "state.json");
  if (existsSync(migratedState)) {
    return migratedDir;
  }
  if (existsSync(checkoutState)) {
    return checkoutDir;
  }
  return existsSync(migratedDir) ? migratedDir : checkoutDir;
}

export function resolveDesktopShellOwnerPaths(workspaceRoot: string): {
  canonical: string | null;
  checkout: string;
} {
  const canonicalHome = resolveCanonicalRuntimeHome(workspaceRoot);
  return {
    canonical: canonicalHome ? join(canonicalHome, "launcher", DESKTOP_SHELL_OWNER_FILE) : null,
    checkout: join(resolveCheckoutRuntimeHome(workspaceRoot), "launcher", DESKTOP_SHELL_OWNER_FILE),
  };
}
