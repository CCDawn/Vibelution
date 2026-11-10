import { spawnSync } from "node:child_process";
import { copyFileSync, cpSync, existsSync, mkdirSync, readdirSync, rmSync } from "node:fs";
import { basename, dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const electronRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");

export function buildWorkbenchJob(input = {}) {
  const root = resolve(input.electronRoot ?? electronRoot);
  const managedPaths = requireOwnedNativeBuildPaths(input, root);
  const platform = input.platform ?? process.platform;
  if (platform !== "win32") {
    return null;
  }

  const outputRoot = managedPaths.outputRoot;
  const sourceRoot = join(root, "native", "workbench-job");
  const buildRoot = managedPaths.nativeBuildRoot;
  const run = input.run ?? spawnSync;
  const env = input.env ?? process.env;
  // node-gyp downloads the running node's headers on a cache miss. On a machine
  // without direct access to nodejs.org that turns every patch upgrade of node
  // (24.15.0 -> 24.18.0) into a hard packaging failure. Prefer the headers
  // already cached locally for this major version: the addon is Node-API, so
  // any headers within the major produce a compatible binary.
  const cachedHeaders = input.headersDir ?? resolveLocalNodeHeaders({ env, exists: input.exists ?? existsSync });
  const stagedHeaders = cachedHeaders
    ? stageNodeHeaders({
        source: cachedHeaders,
        destination: input.headersStageRoot
          ? join(input.headersStageRoot, basename(cachedHeaders))
          : join(resolve(root, "..", ".."), "dist", ".node-headers", basename(cachedHeaders)),
        env,
        platform,
        exists: input.exists ?? existsSync
      })
    : "";
  const headersDir = stagedHeaders || cachedHeaders;
  let ownsBuildRoot = false;
  try {
    mkdirSync(buildRoot, { recursive: false });
    ownsBuildRoot = true;
    for (const entry of readdirSync(sourceRoot, { withFileTypes: true })) {
      if (!entry.isFile() || !["binding.gyp", "job_object.c", "job_object_stub.c"].includes(entry.name)) {
        continue;
      }
      copyFileSync(join(sourceRoot, entry.name), join(buildRoot, entry.name));
    }

    const nodeGypArgs = [join(root, "node_modules", "node-gyp", "bin", "node-gyp.js"), "rebuild"];
    if (headersDir) {
      nodeGypArgs.push(`--nodedir=${headersDir}`);
    }
    const result = run(
      process.execPath,
      nodeGypArgs,
      {
        cwd: buildRoot,
        stdio: "inherit",
        shell: false,
        windowsHide: true,
        env: resolveNativeBuildEnvironment({ env, run, exists: input.exists ?? existsSync })
      }
    );
    if (result.error) {
      throw result.error;
    }
    if (result.status !== 0) {
      throw new Error(`node-gyp rebuild failed with exit code ${result.status ?? 1}.`);
    }

    const built = join(buildRoot, "build", "Release", "workbench_job.node");
    const outputDir = join(outputRoot, "native");
    mkdirSync(outputDir, { recursive: true });
    const output = join(outputDir, "workbench_job.node");
    copyFileSync(built, output);
    return output;
  } finally {
    if (ownsBuildRoot) {
      rmSync(buildRoot, { recursive: true, force: true });
    }
  }
}

/**
 * Mirror cached node headers into the layout node-gyp's MSBuild link step wants.
 *
 * A node-gyp cache installed from the Windows headers tarball keeps the import
 * library at ``<cache>/<arch>/node.lib``, while ``addon.gypi`` links from
 * ``<(node_root_dir)/$(ConfigurationName)`` — i.e. ``Release/node.lib``. Pointing
 * ``--nodedir`` straight at the cache therefore compiles and then fails to link.
 *
 * The staged copy is ~63 MB of headers, so it is written once per node version
 * into a gitignored build-cache directory and reused by later builds rather
 * than copied and deleted on every package.
 */
export function stageNodeHeaders({
  source,
  destination,
  arch = process.arch,
  env = process.env,
  platform = process.platform,
  exists = existsSync,
  copy = cpSync
} = {}) {
  if (!source || !destination) {
    return "";
  }
  if (nodeHeadersAreStaged({ destination, arch, exists })) {
    return destination;
  }
  if (!exists(join(source, "include", "node", "node_api.h"))) {
    return "";
  }
  const importLibrary = findNodeImportLibrary({ source, arch, env, platform, exists });
  if (!importLibrary) {
    return "";
  }
  mkdirSync(destination, { recursive: true });
  copy(join(source, "include"), join(destination, "include"), { recursive: true });
  for (const folder of ["Release", arch]) {
    mkdirSync(join(destination, folder), { recursive: true });
    copyFileSync(importLibrary, join(destination, folder, "node.lib"));
  }
  return destination;
}

export function nodeHeadersAreStaged({ destination, arch = process.arch, exists = existsSync } = {}) {
  if (!destination) {
    return false;
  }
  return exists(join(destination, "include", "node", "node_api.h"))
    && exists(join(destination, "Release", "node.lib"))
    && exists(join(destination, arch, "node.lib"));
}

export function findNodeImportLibrary({ source, arch = process.arch, platform = process.platform, exists = existsSync } = {}) {
  if (platform !== "win32") {
    return "";
  }
  for (const folder of [arch, "Release", "Debug"]) {
    const candidate = join(source, folder, "node.lib");
    if (exists(candidate)) {
      return candidate;
    }
  }
  return "";
}

/**
 * Locate node headers node-gyp can compile against without a download.
 *
 * node-gyp fetches headers whenever the running node's exact version is not
 * cached, which fails outright on a host that cannot reach nodejs.org. The
 * addon is Node-API, so headers from another patch release of the same major
 * version build a fully compatible binary.
 */
export function resolveLocalNodeHeaders({
  version = process.versions.node,
  env = process.env,
  platform = process.platform,
  exists = existsSync,
  readDirectory = readdirSync
} = {}) {
  const major = String(version || "").trim().split(".")[0];
  const cacheRoot = nodeGypCacheRoot({ env, platform });
  if (!/^\d+$/.test(major) || !cacheRoot || !exists(cacheRoot)) {
    return "";
  }
  let entries;
  try {
    entries = readDirectory(cacheRoot, { withFileTypes: true });
  } catch {
    return "";
  }
  const candidates = entries
    .filter((entry) => entry.isDirectory() && /^\d+\.\d+\.\d+$/.test(entry.name))
    .map((entry) => entry.name)
    .filter((name) => name.split(".")[0] === major)
    .sort((left, right) => compareVersionDesc(left, right));
  for (const name of candidates) {
    const candidate = join(cacheRoot, name);
    if (exists(join(candidate, "include", "node", "node_api.h"))) {
      return candidate;
    }
  }
  return "";
}

export function nodeGypCacheRoot({ env = process.env, platform = process.platform } = {}) {
  const localAppData = String(env.LOCALAPPDATA || "").trim();
  if (platform === "win32") {
    return localAppData ? join(localAppData, "node-gyp", "Cache") : "";
  }
  const home = String(env.HOME || env.USERPROFILE || "").trim();
  return home ? join(home, ".cache", "node-gyp") : "";
}

function compareVersionDesc(left, right) {
  const leftParts = left.split(".").map(Number);
  const rightParts = right.split(".").map(Number);
  for (let index = 0; index < 3; index += 1) {
    const delta = (rightParts[index] ?? 0) - (leftParts[index] ?? 0);
    if (delta !== 0) {
      return delta;
    }
  }
  return 0;
}

// node-gyp can use a Developer Command Prompt location directly, avoiding its
// PowerShell discovery. Keep this environment local to the native build.
export function resolveNativeBuildEnvironment({ env = process.env, run = spawnSync, exists = existsSync } = {}) {
  const value = (name) => Object.entries(env).find(([key]) => key.toLowerCase() === name.toLowerCase())?.[1];
  if (value("VCINSTALLDIR") || value("VSCMD_VER") || value("npm_config_msvs_version")) {
    return env;
  }
  const programFiles = value("ProgramFiles(x86)");
  if (!programFiles) return env;
  const vswhere = join(programFiles, "Microsoft Visual Studio", "Installer", "vswhere.exe");
  if (!exists(vswhere)) return env;

  try {
    // Service contexts omit ProgramData, but vswhere reads its instance index
    // from %ProgramData%\Microsoft\VisualStudio and silently returns an empty
    // list without it, which would drop this whole vswhere path.
    const programData = value("ProgramData") ?? join(value("SystemDrive") ?? "C:", "ProgramData");
    const vswhereEnv = value("ProgramData") ? env : { ...env, ProgramData: programData };
    const result = run(vswhere, [
      "-sort", "-products", "*", "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
      "-format", "json", "-utf8", "-include", "packages"
    ], { encoding: "utf8", maxBuffer: 8 * 1024 * 1024, shell: false, windowsHide: true, env: vswhereEnv });
    if (result.error || result.status !== 0) return env;
    const instances = JSON.parse(String(result.stdout).replace(/^\uFEFF/, ""));
    if (!Array.isArray(instances)) return env;
    for (const instance of instances) {
      const { installationPath, installationVersion, packages } = instance;
      if (typeof installationPath !== "string" || !installationPath ||
          typeof installationVersion !== "string" || !/^(16|17|18)\.\d+/.test(installationVersion) ||
          !Array.isArray(packages)) continue;
      const sdkBuilds = packages.map((pkg) => /^Microsoft\.VisualStudio\.Component\.Windows(?:10|11)SDK\.(\d+)(?:\.Desktop)?$/i.exec(pkg?.id ?? ""))
        .filter(Boolean).map((match) => Number(match[1]));
      const sdk = value("WindowsSDKVersion") || (sdkBuilds.length ? `10.0.${Math.max(...sdkBuilds)}.0` : "");
      const vc = join(installationPath, "VC");
      if (!sdk || !exists(vc) || !exists(join(installationPath, "MSBuild", "Current", "Bin", "MSBuild.exe"))) continue;
      return { ...env, VCINSTALLDIR: vc, VSCMD_VER: installationVersion, ...(!value("WindowsSDKVersion") && { WindowsSDKVersion: sdk }) };
    }
  } catch {
    // Fall back to node-gyp's own discovery and error output.
  }
  return env;
}

function requireOwnedNativeBuildPaths(input, electronRootPath) {
  if (String(process.env.VIBELUTION_DESKTOP_BUILD_MANAGED ?? "") !== "1") {
    throw new Error("Native builds require the managed Python build owner.");
  }
  const suppliedSession = String(process.env.VIBELUTION_DESKTOP_BUILD_ROOT ?? "").trim();
  const suppliedOutput = String(process.env.VIBELUTION_ELECTRON_DIST ?? "").trim();
  const suppliedNativeRoot = String(process.env.VIBELUTION_WORKBENCH_JOB_BUILD_ROOT ?? "").trim();
  if (!suppliedSession || !suppliedOutput || !suppliedNativeRoot) {
    throw new Error("Native builds require owner-provided session and output paths.");
  }

  const sessionRoot = resolve(suppliedSession);
  const workspaceRoot = resolve(electronRootPath, "..", "..");
  const packagedParent = resolve(workspaceRoot, "dist");
  const packagedSession = dirname(sessionRoot) === packagedParent
    && basename(sessionRoot).startsWith(".desktop-shell-build-");
  const unpackagedSession = dirname(sessionRoot) === electronRootPath
    && basename(sessionRoot).startsWith(".build-stage-");
  if (!packagedSession && !unpackagedSession) {
    throw new Error("Native build session must be an isolated package or unpackaged build directory.");
  }
  if (!existsSync(sessionRoot)) {
    throw new Error("Owner-provided native build session does not exist.");
  }

  const outputRoot = resolve(suppliedOutput);
  const nativeBuildRoot = resolve(suppliedNativeRoot);
  if (input.outputRoot && resolve(input.outputRoot) !== outputRoot) {
    throw new Error("Native output path does not match the owner-provided path.");
  }
  if (input.nativeBuildRoot && resolve(input.nativeBuildRoot) !== nativeBuildRoot) {
    throw new Error("Native build path does not match the owner-provided path.");
  }
  if (!isContained(sessionRoot, outputRoot) || !isContained(sessionRoot, nativeBuildRoot)) {
    throw new Error("Native build inputs and outputs must stay inside the owner session.");
  }
  if (!existsSync(outputRoot)) {
    throw new Error("Owner-provided native output directory does not exist.");
  }
  if (dirname(nativeBuildRoot) !== sessionRoot || existsSync(nativeBuildRoot)) {
    throw new Error("Native compilation must use a fresh isolated directory inside the owner session.");
  }
  return { outputRoot, nativeBuildRoot };
}

function isContained(parent, candidate) {
  const path = relative(parent, candidate);
  return path === "" || (path !== ".." && !path.startsWith(`..${sep}`) && !isAbsolute(path));
}

function isDirectRun() {
  const entrypoint = process.argv[1];
  return Boolean(entrypoint) && import.meta.url === pathToFileURL(resolve(entrypoint)).href;
}

if (isDirectRun()) {
  try {
    if (process.env.VIBELUTION_DESKTOP_BUILD_MANAGED !== "1") {
      throw new Error("Invoke native builds through the Python build owner.");
    }
    buildWorkbenchJob();
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  }
}
