import { spawn } from "node:child_process";
import process from "node:process";

// tsc -b and vite build read the same sources and write disjoint outputs
// (tsbuildinfo vs dist), so the serial `tsc -b && vite build` wastes the
// shorter leg. Spawn both through node directly (Node >= 20 refuses to spawn
// .cmd shims without a shell); fail the build if either fails.
const steps = [
  { label: "tsc -b", args: ["node_modules/typescript/bin/tsc", "-b"] },
  { label: "vite build", args: ["node_modules/vite/bin/vite.js", "build", "--config", "vite.config.ts"] },
];

const children = steps.map((step) => {
  const child = spawn(process.execPath, step.args, { stdio: "inherit", shell: false });
  const completion = new Promise((resolve) => {
    child.on("exit", (code) => resolve(code === null ? 1 : code));
    child.on("error", () => resolve(1));
  });
  return { step, completion };
});

let failedLabel = "";
for (const entry of children) {
  const exitCode = await entry.completion;
  if (exitCode !== 0 && !failedLabel) {
    failedLabel = entry.step.label;
  }
}

if (failedLabel) {
  console.error(`parallel build failed at: ${failedLabel}`);
  process.exit(1);
}

// web/dist is the legacy compatibility tree. It feeds the installers, release
// packaging, the E2E build helper and the bundle-budget gate, but the running
// workbench serves an atomically published release under web/.vibelution-builds.
// A green build here therefore does not change the served page; name that out
// loud instead of letting a successful exit read as "the fix is live".
console.log("");
console.log("frontend build ok -> web/dist (legacy compatibility tree)");
console.log("  consumed by: installer, release packaging, E2E build helper, check:bundle");
console.log("  served at runtime: web/.vibelution-builds/release-* via the active pointer");
console.log("  apply this change to the running workbench: Launcher restart");
console.log("  inspect the served bytes: python -m core.launcher.frontend_build status");
