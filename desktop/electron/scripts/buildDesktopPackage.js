import { spawnSync } from "node:child_process";
import {
  copyFileSync,
  existsSync,
  mkdirSync,
  readFileSync,
  writeFileSync
} from "node:fs";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const electronRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");

export function parseDesktopPackageArgs(argv) {
  const result = { mode: "dir" };
  for (let index = 0; index < argv.length; index += 1) {
    const flag = argv[index];
    if (flag !== "--mode") {
      throw new Error(`Unknown desktop package argument: ${flag}`);
    }
    const value = String(argv[index + 1] ?? "").trim();
    if (!["dir", "staging", "linux-arm64"].includes(value)) {
      throw new Error(`Unsupported desktop package mode: ${value}`);
    }
    result.mode = value;
    index += 1;
  }
  return result;
}

export function createIsolatedBuilderConfig(input) {
  const config = structuredClone(input.baseConfig);
  config.directories = {
    ...config.directories,
    app: resolve(input.appRoot),
    output: resolve(input.outputRoot)
  };
  config.extraResources = [{ from: resolve(input.frontendRoot), to: "web-dist" }];
  if (config.win?.icon) {
    config.win.icon = resolve(input.electronRoot, config.win.icon);
  }
  return config;
}

export function runDesktopPackageBuild(input = {}) {
  const mode = input.mode ?? "dir";
  if (!["dir", "staging", "linux-arm64"].includes(mode)) {
    throw new Error(`Unsupported desktop package mode: ${mode}`);
  }
  const root = resolve(input.workspaceRoot ?? resolve(electronRoot, "..", ".."));
  const packageRoot = resolve(input.electronRoot ?? electronRoot);
  const buildRoot = requireOwnedPackageSession(input, root);
  const appRoot = join(buildRoot, "app");
  const distRoot = join(appRoot, "dist");
  const frontendRoot = join(buildRoot, "package-web-dist");
  const nativeBuildRoot = join(buildRoot, "native-workbench-job");
  const outputRoot = join(buildRoot, "builder-output");
  const generatedConfigPath = join(buildRoot, "electron-builder.generated.json");

  mkdirSync(dirname(buildRoot), { recursive: true });
  mkdirSync(buildRoot);
  mkdirSync(appRoot);
  mkdirSync(distRoot);

  try {
    copyFileSync(join(packageRoot, "package.json"), join(appRoot, "package.json"));
    copyFileSync(join(packageRoot, "desktop-entry-catalog.json"), join(appRoot, "desktop-entry-catalog.json"));

    const environment = {
      ...process.env,
      VIBELUTION_DESKTOP_BUILD_MANAGED: "1",
      VIBELUTION_ELECTRON_DIST: distRoot,
      VIBELUTION_WORKBENCH_JOB_BUILD_ROOT: nativeBuildRoot
    };
    runNode(input, join(packageRoot, "node_modules", "typescript", "bin", "tsc"), [
      "-p", "tsconfig.json", "--outDir", distRoot
    ], packageRoot, environment);
    runNode(input, join(packageRoot, "node_modules", "esbuild", "bin", "esbuild"), [
      "src/preload.ts", "--bundle", "--platform=node", "--format=cjs",
      `--outfile=${join(distRoot, "preload.cjs")}`, "--external:electron"
    ], packageRoot, environment);
    runNode(input, join(packageRoot, "scripts", "buildWorkbenchJob.js"), [], packageRoot, environment);

    const provenanceArgs = [
      "--workspace-root", root,
      "--output", join(appRoot, "package-provenance.json"),
      "--dist-root", distRoot,
      "--frontend-output", frontendRoot
    ];
    runNode(
      input,
      join(distRoot, "scripts", "writePackageProvenance.js"),
      provenanceArgs,
      appRoot,
      { ...environment, VIBELUTION_ELECTRON_DIST: distRoot }
    );

    const builderConfig = createIsolatedBuilderConfig({
      baseConfig: input.baseConfig ?? readJsonFile(join(packageRoot, "electron-builder.json")),
      electronRoot: packageRoot,
      appRoot,
      outputRoot,
      frontendRoot
    });
    writeFileSync(generatedConfigPath, `${JSON.stringify(builderConfig, null, 2)}\n`, "utf8");

    const builderPackage = readJsonFile(join(packageRoot, "node_modules", "electron-builder", "package.json"));
    const builderBin = typeof builderPackage.bin === "string"
      ? builderPackage.bin
      : builderPackage.bin?.["electron-builder"];
    if (!builderBin) {
      throw new Error("electron-builder CLI entrypoint is missing.");
    }
    const builderCli = resolve(packageRoot, "node_modules", "electron-builder", builderBin);
    const builderArgs = ["--config", generatedConfigPath];
    if (mode === "linux-arm64") {
      builderArgs.push("--linux", "dir", "--arm64");
    } else {
      builderArgs.push("--dir");
    }
    runNode(input, builderCli, builderArgs, packageRoot, environment);

    if (mode !== "linux-arm64") {
      validateWindowsBuild(outputRoot);
    } else if (!existsSync(outputRoot)) {
      throw new Error("electron-builder did not produce its isolated output directory.");
    }

    return { buildRoot, appRoot, frontendRoot, outputRoot, generatedConfigPath };
  } catch (error) {
    throw error;
  }
}

function requireOwnedPackageSession(input, workspaceRoot) {
  if (String(process.env.VIBELUTION_DESKTOP_BUILD_MANAGED ?? "") !== "1") {
    throw new Error("Desktop package builds require the managed Python build owner.");
  }
  const suppliedRoot = String(process.env.VIBELUTION_DESKTOP_BUILD_ROOT ?? "").trim();
  if (!suppliedRoot) {
    throw new Error("Desktop package builds require an owner-provided session path.");
  }
  const buildRoot = resolve(suppliedRoot);
  if (input.buildRoot && resolve(input.buildRoot) !== buildRoot) {
    throw new Error("Desktop package session does not match the owner-provided path.");
  }
  const expectedParent = resolve(workspaceRoot, "dist");
  if (dirname(buildRoot) !== expectedParent || !basename(buildRoot).startsWith(".desktop-shell-build-")) {
    throw new Error("Desktop package session must be an isolated child of workspace dist.");
  }
  if (existsSync(buildRoot)) {
    throw new Error(`Desktop package build path already exists: ${buildRoot}`);
  }
  return buildRoot;
}

function runNode(input, executable, args, cwd, env) {
  const run = input.run ?? spawnSync;
  const result = run(process.execPath, [executable, ...args], {
    cwd,
    env,
    stdio: "inherit",
    windowsHide: true
  });
  if (result.error) {
    throw result.error;
  }
  if (result.status !== 0) {
    throw new Error(`${executable} failed with exit code ${result.status ?? 1}.`);
  }
}

function validateWindowsBuild(outputRoot) {
  const unpacked = join(outputRoot, "win-unpacked");
  const executable = join(unpacked, "Vibelution.exe");
  const asar = join(unpacked, "resources", "app.asar");
  const provenance = join(unpacked, "resources", "app.asar.unpacked", "package-provenance.json");
  if (!existsSync(executable) || !existsSync(asar) || !existsSync(provenance)) {
    throw new Error("electron-builder output is missing the executable, app.asar, or package provenance.");
  }
}

function readJsonFile(path) {
  return JSON.parse(readFileSync(path, "utf8"));
}

function isDirectRun() {
  const entrypoint = process.argv[1];
  return Boolean(entrypoint) && import.meta.url === pathToFileURL(resolve(entrypoint)).href;
}

if (isDirectRun()) {
  try {
    if (String(process.env.VIBELUTION_DESKTOP_BUILD_MANAGED ?? "") !== "1") {
      throw new Error("Invoke desktop packaging through the Python build owner.");
    }
    const args = parseDesktopPackageArgs(process.argv.slice(2));
    runDesktopPackageBuild(args);
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  }
}
