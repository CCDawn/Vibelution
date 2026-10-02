import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import {
  cpSync,
  existsSync,
  lstatSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  rmSync,
  writeFileSync
} from "node:fs";
import { basename, isAbsolute, relative, resolve, sep } from "node:path";

const FRONTEND_RELEASES_RELATIVE = ["web", ".vibelution-builds"] as const;
const FRONTEND_ACTIVE_POINTER = "active.json";
const FRONTEND_BUILD_METADATA = ".vibelution-build.json";
const GIT_OBJECT_HASH = /^[0-9a-f]{40,64}$/i;

export type EnsureFrontendBuildResult = {
  ok: boolean;
  release: string;
  buildKey: string;
};

export type PackagedFrontendEvidence = {
  path: string;
  frontendTreeHash: string;
  frontendContentSha256: string;
  frontendBuildKey: string;
  frontendSourceCommit: string;
};

type ActiveReleasePointer = {
  release?: unknown;
  buildKey?: unknown;
};

type FrontendBuildMetadata = {
  schemaVersion?: unknown;
  buildKey?: unknown;
  frontendTree?: unknown;
  sourceCommit?: unknown;
};

export function preparePackagedFrontend(input: {
  workspaceRoot: string;
  packageInputRoot: string;
  ensureBuild?: (workspaceRoot: string) => EnsureFrontendBuildResult;
}): PackagedFrontendEvidence {
  const workspaceRoot = resolve(input.workspaceRoot);
  const packageInputRoot = resolve(input.packageInputRoot);
  assertIsolatedPackageInput(workspaceRoot, packageInputRoot);
  const build = (input.ensureBuild ?? ensureCurrentFrontendBuild)(workspaceRoot);
  if (!build.ok || !build.buildKey.trim()) {
    throw new Error("Frontend build did not return verified active-release metadata.");
  }

  const releasesRoot = resolve(workspaceRoot, ...FRONTEND_RELEASES_RELATIVE);
  const pointerPath = resolve(releasesRoot, FRONTEND_ACTIVE_POINTER);
  const pointer = readJsonFile<ActiveReleasePointer>(pointerPath);
  const releaseName = String(pointer.release ?? "").trim();
  const pointerBuildKey = String(pointer.buildKey ?? "").trim();
  if (!releaseName || basename(releaseName) !== releaseName || !releaseName.startsWith("release-")) {
    throw new Error("Active frontend release pointer is missing or invalid.");
  }
  const activeRelease = resolve(releasesRoot, releaseName);
  assertContainedPath(releasesRoot, activeRelease, "active frontend release");
  if (!sameResolvedPath(build.release, activeRelease) || build.buildKey !== pointerBuildKey) {
    throw new Error("Frontend active release changed while preparing the desktop package.");
  }

  const metadata = readJsonFile<FrontendBuildMetadata>(resolve(activeRelease, FRONTEND_BUILD_METADATA));
  const frontendTreeHash = String(metadata.frontendTree ?? "").trim();
  const frontendBuildKey = String(metadata.buildKey ?? "").trim();
  const frontendSourceCommit = String(metadata.sourceCommit ?? "").trim();
  if (
    Number(metadata.schemaVersion) !== 2
    || frontendBuildKey !== pointerBuildKey
    || frontendBuildKey !== build.buildKey
    || !GIT_OBJECT_HASH.test(frontendTreeHash)
    || !GIT_OBJECT_HASH.test(frontendSourceCommit)
  ) {
    throw new Error("Active frontend release has incomplete or inconsistent build provenance.");
  }

  const frontendContentSha256 = sha256DirectoryTree(activeRelease);
  if (existsSync(packageInputRoot)) {
    throw new Error("Desktop package frontend input must use a fresh, isolated build path.");
  }

  mkdirSync(packageInputRoot, { recursive: true });
  try {
    cpSync(activeRelease, packageInputRoot, { recursive: true, errorOnExist: true, force: false });
    if (sha256DirectoryTree(packageInputRoot) !== frontendContentSha256) {
      throw new Error("Copied frontend package input does not match the verified active release.");
    }
    assertFrontendReleaseStillCurrent({
      workspaceRoot,
      releasesRoot,
      activeRelease,
      buildKey: frontendBuildKey,
      ensureBuild: input.ensureBuild ?? ensureCurrentFrontendBuild
    });
  } catch (error: unknown) {
    rmSync(packageInputRoot, { recursive: true, force: true });
    throw error;
  }

  return {
    path: packageInputRoot,
    frontendTreeHash,
    frontendContentSha256,
    frontendBuildKey,
    frontendSourceCommit
  };
}

function assertIsolatedPackageInput(workspaceRoot: string, packageInputRoot: string): void {
  const sharedNodeModules = resolve(workspaceRoot, "desktop", "electron", "node_modules");
  const relativePath = relative(sharedNodeModules, packageInputRoot);
  if (!relativePath || (!relativePath.startsWith("..") && !isAbsolute(relativePath))) {
    throw new Error("Desktop package frontend input cannot be written below shared electron/node_modules.");
  }
}

function assertFrontendReleaseStillCurrent(input: {
  workspaceRoot: string;
  releasesRoot: string;
  activeRelease: string;
  buildKey: string;
  ensureBuild: (workspaceRoot: string) => EnsureFrontendBuildResult;
}): void {
  const build = input.ensureBuild(input.workspaceRoot);
  const pointer = readJsonFile<ActiveReleasePointer>(resolve(input.releasesRoot, FRONTEND_ACTIVE_POINTER));
  const releaseName = String(pointer.release ?? "").trim();
  const activeRelease = resolve(input.releasesRoot, releaseName);
  if (
    !build.ok
    || build.buildKey !== input.buildKey
    || String(pointer.buildKey ?? "") !== input.buildKey
    || !releaseName.startsWith("release-")
    || basename(releaseName) !== releaseName
    || !sameResolvedPath(build.release, input.activeRelease)
    || !sameResolvedPath(activeRelease, input.activeRelease)
  ) {
    throw new Error("Frontend active release changed while preparing the desktop package.");
  }
}

export function sha256DirectoryTree(root: string): string {
  const absoluteRoot = resolve(root);
  const entries: Array<{ absolutePath: string; relativePath: string }> = [];
  const visit = (directory: string): void => {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const absolutePath = resolve(directory, entry.name);
      if (entry.isSymbolicLink()) {
        throw new Error(`Frontend package contains a symbolic link: ${relative(absoluteRoot, absolutePath)}`);
      }
      if (entry.isDirectory()) {
        visit(absolutePath);
      } else if (entry.isFile()) {
        entries.push({
          absolutePath,
          relativePath: relative(absoluteRoot, absolutePath).split(sep).join("/")
        });
      }
    }
  };
  if (!existsSync(absoluteRoot) || !lstatSync(absoluteRoot).isDirectory()) {
    throw new Error(`Frontend package directory is missing: ${absoluteRoot}`);
  }
  visit(absoluteRoot);
  entries.sort((left, right) => Buffer.compare(Buffer.from(left.relativePath, "utf8"), Buffer.from(right.relativePath, "utf8")));

  const hash = createHash("sha256");
  for (const entry of entries) {
    const pathBytes = Buffer.from(entry.relativePath, "utf8");
    const contentBytes = readFileSync(entry.absolutePath);
    const pathLength = Buffer.alloc(4);
    pathLength.writeUInt32BE(pathBytes.byteLength);
    const contentLength = Buffer.alloc(8);
    contentLength.writeBigUInt64BE(BigInt(contentBytes.byteLength));
    hash.update(pathLength);
    hash.update(pathBytes);
    hash.update(contentLength);
    hash.update(contentBytes);
  }
  return hash.digest("hex");
}

function ensureCurrentFrontendBuild(workspaceRoot: string): EnsureFrontendBuildResult {
  const bridge = resolve(workspaceRoot, "scripts", "vibelution_desktop_entry.py");
  const python = resolvePython(workspaceRoot);
  const output = execFileSync(
    python,
    [bridge, "--action", "ensure-frontend-build", "--output", "json", "--workspace", workspaceRoot],
    {
      cwd: workspaceRoot,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
      windowsHide: true,
      env: process.env
    }
  ).trim();
  let payload: unknown;
  try {
    payload = JSON.parse(output);
  } catch {
    throw new Error("Frontend build bridge returned invalid JSON.");
  }
  if (!payload || typeof payload !== "object") {
    throw new Error("Frontend build bridge returned an invalid result.");
  }
  const record = payload as Record<string, unknown>;
  return {
    ok: record.ok === true,
    release: String(record.release ?? ""),
    buildKey: String(record.buildKey ?? "")
  };
}

function resolvePython(workspaceRoot: string): string {
  const configured = [
    process.env.VIBELUTION_PYTHON_PATH,
    process.env.PYTHON,
    resolve(workspaceRoot, process.platform === "win32" ? ".venv/Scripts/python.exe" : ".venv/bin/python"),
    process.platform === "win32" ? "python.exe" : "python3"
  ].map((value) => String(value ?? "").trim()).filter(Boolean);
  for (const candidate of configured) {
    if (process.platform === "win32" && candidate.toLowerCase().endsWith("pythonw.exe")) {
      const consolePython = candidate.slice(0, -"pythonw.exe".length) + "python.exe";
      if (existsSync(consolePython)) {
        return consolePython;
      }
      continue;
    }
    if (candidate.includes("/") || candidate.includes("\\")) {
      if (existsSync(candidate)) {
        return candidate;
      }
      continue;
    }
    return candidate;
  }
  throw new Error("No Python interpreter is available to verify the active frontend release.");
}

function readJsonFile<T>(path: string): T {
  return JSON.parse(readFileSync(path, "utf8")) as T;
}

function assertContainedPath(parent: string, candidate: string, label: string): void {
  const absoluteParent = resolve(parent);
  const absoluteCandidate = resolve(candidate);
  const relativePath = relative(absoluteParent, absoluteCandidate);
  if (
    !relativePath
    || relativePath === ".."
    || relativePath.startsWith(`..${sep}`)
    || isAbsolute(relativePath)
    || !sameResolvedPath(resolve(absoluteParent, relativePath), absoluteCandidate)
  ) {
    throw new Error(`${label} must resolve below its owning directory.`);
  }
}

function sameResolvedPath(left: string, right: string): boolean {
  const first = resolve(left);
  const second = resolve(right);
  return process.platform === "win32"
    ? first.toLowerCase() === second.toLowerCase()
    : first === second;
}
