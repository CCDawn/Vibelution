import { spawnSync } from "node:child_process";
import { copyFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const electronRoot = join(dirname(fileURLToPath(import.meta.url)), "..");

if (process.platform !== "win32") {
  process.exit(0);
}

const rebuild = spawnSync(
  process.execPath,
  [
    join(electronRoot, "node_modules", "node-gyp", "bin", "node-gyp.js"),
    "rebuild",
    "--directory",
    join(electronRoot, "native", "workbench-job")
  ],
  { cwd: electronRoot, stdio: "inherit" }
);
if (rebuild.status !== 0) {
  process.exit(rebuild.status ?? 1);
}

const built = join(electronRoot, "native", "workbench-job", "build", "Release", "workbench_job.node");
const outputDir = join(electronRoot, "dist", "native");
mkdirSync(outputDir, { recursive: true });
copyFileSync(built, join(outputDir, "workbench_job.node"));
