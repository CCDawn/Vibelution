import { spawnSync } from "node:child_process";
import { copyFileSync, existsSync, mkdirSync, readdirSync, rmSync } from "node:fs";
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

    const result = run(
      process.execPath,
      [join(root, "node_modules", "node-gyp", "bin", "node-gyp.js"), "rebuild"],
      {
        cwd: buildRoot,
        stdio: "inherit",
        shell: false,
        windowsHide: true,
        env: resolveNativeBuildEnvironment({ env: input.env ?? process.env, run, exists: input.exists ?? existsSync })
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
    const result = run(vswhere, [
      "-sort", "-products", "*", "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
      "-format", "json", "-utf8", "-include", "packages"
    ], { encoding: "utf8", maxBuffer: 8 * 1024 * 1024, shell: false, windowsHide: true, env });
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
