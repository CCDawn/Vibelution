import { spawnSync } from "node:child_process";
import {
  copyFileSync,
  existsSync,
  mkdirSync,
  lstatSync,
  readFileSync,
  readdirSync,
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
  Object.assign(config, input.electronDistribution ?? {});
  config.directories = {
    ...config.directories,
    app: resolve(input.appRoot),
    output: resolve(input.outputRoot)
  };
  if (!input.assistantRoot) throw new Error("Desktop packages require the owner-built assistant payload.");
  config.extraResources = [
    { from: resolve(input.frontendRoot), to: "web-dist" },
    { from: resolve(input.assistantRoot), to: "launcher-assistant" }
  ];
  if (config.win?.icon) {
    config.win.icon = resolve(input.electronRoot, config.win.icon);
  }
  return config;
}

export function resolveInstalledElectronDistribution(packageRoot, mode, platform = process.platform) {
  // A cross-build must download its target runtime, not copy the host runtime.
  if (mode === "linux-arm64") return {};
  const installed = join(packageRoot, "node_modules", "electron");
  const metadata = readJsonFile(join(installed, "package.json"));
  const electronDist = join(installed, "dist");
  const version = readFileSync(join(electronDist, "version"), "utf8").trim();
  const executable = platform === "win32" ? "electron.exe"
    : platform === "darwin" ? "Electron.app/Contents/MacOS/Electron" : "electron";
  if (!version || version !== metadata.version || !existsSync(join(electronDist, executable))) {
    throw new Error("Installed Electron distribution is incomplete or its version does not match its package.");
  }
  // electron-builder supports an unpacked distribution. Copying it avoids a
  // second download/extraction and Windows EPERM on win-unpacked.tmp rename.
  return { electronDist, electronVersion: version };
}

export function runDesktopPackageBuild(input = {}) {
  const mode = input.mode ?? "dir";
  if (!["dir", "staging", "linux-arm64"].includes(mode)) {
    throw new Error(`Unsupported desktop package mode: ${mode}`);
  }
  if (mode === "linux-arm64" || process.platform !== "win32") {
    throw new Error("Launcher assistant packages currently require a native Windows build.");
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
  const assistantRoot = join(buildRoot, "launcher-assistant");

  mkdirSync(dirname(buildRoot), { recursive: true });
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
      "--frontend-output", frontendRoot,
      "--assistant-payload-root", assistantRoot,
      "--assistant-manifest-sha256", process.env.VIBELUTION_ASSISTANT_MANIFEST_SHA256
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
      electronDistribution: resolveInstalledElectronDistribution(packageRoot, mode),
      electronRoot: packageRoot,
      appRoot,
      outputRoot,
      frontendRoot,
      assistantRoot
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

    return { buildRoot, appRoot, frontendRoot, assistantRoot, outputRoot, generatedConfigPath };
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
  const assistantRoot = join(buildRoot, "launcher-assistant");
  if (resolve(String(process.env.VIBELUTION_ASSISTANT_PAYLOAD_ROOT ?? "")) !== assistantRoot
    || !/^[0-9a-f]{64}$/.test(String(process.env.VIBELUTION_ASSISTANT_MANIFEST_SHA256 ?? ""))
    || !existsSync(buildRoot) || lstatSync(buildRoot).isSymbolicLink() || !lstatSync(buildRoot).isDirectory()
    || readdirSync(buildRoot).length !== 1 || readdirSync(buildRoot)[0] !== "launcher-assistant"
    || lstatSync(assistantRoot).isSymbolicLink() || !lstatSync(assistantRoot).isDirectory()
    || !existsSync(join(assistantRoot, "manifest.json"))) {
    throw new Error("Desktop package session must contain only its owner-built assistant payload.");
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
  const assistant = join(unpacked, "resources", "launcher-assistant");
  if (!existsSync(executable) || !existsSync(asar) || !existsSync(provenance)
    || !existsSync(join(assistant, "manifest.json")) || !existsSync(join(assistant, "python", "pythonw.exe"))
    || !existsSync(join(assistant, "source", "scripts", "assistant_host.py")) || !readJsonFile(provenance).assistant) {
    throw new Error("electron-builder output is missing the executable, provenance, or assistant payload.");
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
