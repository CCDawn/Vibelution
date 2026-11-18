import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import process from "node:process";

// `npm run build` writes web/dist, which nothing serves at runtime. This entry
// runs the Launcher's own build instead, so a manual build publishes the very
// release the workbench loads: same lock, same BuildKey, same atomic pointer
// swap. The interpreter is resolved here rather than through the shell so the
// script stays quiet on Windows and works from any cwd.
const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const projectRoot = resolve(webRoot, "..");

function venvPythonUnder(root) {
  return process.platform === "win32"
    ? join(root, ".venv", "Scripts", "python.exe")
    : join(root, ".venv", "bin", "python");
}

// A task worktree has no .venv of its own; the interpreter lives in the main
// checkout that shares this .git directory. Resolve it through git instead of
// guessing a parent depth, so `npm run build:release` works in both trees.
function mainCheckoutRoot() {
  const completed = spawnSync(
    "git",
    ["rev-parse", "--path-format=absolute", "--git-common-dir"],
    { cwd: projectRoot, encoding: "utf8", shell: false },
  );
  if (completed.status !== 0 || !completed.stdout) {
    return "";
  }
  const commonDir = resolve(completed.stdout.trim());
  return dirname(commonDir);
}

function resolveInterpreter() {
  const override = process.env.VIBELUTION_PYTHON;
  if (override) {
    return override;
  }
  const roots = [projectRoot];
  const shared = mainCheckoutRoot();
  if (shared && shared !== projectRoot) {
    roots.push(shared);
  }
  for (const root of roots) {
    const candidate = venvPythonUnder(root);
    if (existsSync(candidate)) {
      return candidate;
    }
  }
  return process.platform === "win32" ? "python" : "python3";
}

const args = ["-m", "core.launcher.frontend_build", "build", "--project-root", projectRoot];
const completed = spawnSync(resolveInterpreter(), args, {
  cwd: projectRoot,
  stdio: "inherit",
  shell: false,
});
if (completed.error) {
  console.error(`frontend release build failed to start: ${completed.error.message}`);
  process.exit(1);
}
process.exit(completed.status ?? 1);
