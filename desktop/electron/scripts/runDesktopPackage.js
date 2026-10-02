import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const electronRoot = resolve(fileURLToPath(new URL("..", import.meta.url)));

export function resolveBuildPython(workspaceRoot) {
  const configured = [
    process.env.VIBELUTION_PYTHON_PATH,
    process.env.PYTHON,
    resolve(workspaceRoot, process.platform === "win32" ? ".venv/Scripts/python.exe" : ".venv/bin/python"),
    process.platform === "win32" ? "python.exe" : "python3"
  ].map((value) => String(value ?? "").trim()).filter(Boolean);
  for (const candidate of configured) {
    if (process.platform === "win32" && candidate.toLowerCase().endsWith("pythonw.exe")) {
      const consolePython = `${candidate.slice(0, -"pythonw.exe".length)}python.exe`;
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
  throw new Error("No Python interpreter is available for the desktop package owner.");
}

export function runDesktopPackageOwner(argv = process.argv.slice(2)) {
  if (argv.length !== 2 || argv[0] !== "--mode" || !["dir", "staging", "linux-arm64", "unpackaged"].includes(argv[1])) {
    throw new Error("Usage: runDesktopPackage.js --mode <dir|staging|linux-arm64|unpackaged>");
  }
  const workspaceRoot = resolve(electronRoot, "..", "..");
  const python = resolveBuildPython(workspaceRoot);
  const runner = resolve(workspaceRoot, "scripts", "build_desktop_shell_package.py");
  const result = spawnSync(python, [runner, "--mode", argv[1]], {
    cwd: workspaceRoot,
    stdio: "inherit",
    windowsHide: true
  });
  if (result.error) {
    throw result.error;
  }
  if (result.status !== 0) {
    throw new Error(`Desktop package owner exited with code ${result.status ?? 1}.`);
  }
}

function isDirectRun() {
  const entrypoint = process.argv[1];
  return Boolean(entrypoint) && import.meta.url === pathToFileURL(resolve(entrypoint)).href;
}

if (isDirectRun()) {
  try {
    runDesktopPackageOwner();
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  }
}
