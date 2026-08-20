import { spawn } from "node:child_process";
import process from "node:process";

// tsc -b and vite build read the same sources and write disjoint outputs
// (tsbuildinfo vs dist), so the serial `tsc -b && vite build` wastes the
// shorter leg. Spawn both through node directly (Node >= 20 refuses to spawn
// .cmd shims without a shell); fail the build if either fails.
const steps = [
  { label: "tsc -b", args: ["node_modules/typescript/bin/tsc", "-b"] },
  { label: "vite build", args: ["node_modules/vite/bin/vite.js", "build"] },
];

const children = steps.map((step) => ({
  step,
  child: spawn(process.execPath, step.args, { stdio: "inherit", shell: false }),
}));

let failedLabel = "";
for (const entry of children) {
  const exitCode = await new Promise((resolve) => {
    entry.child.on("exit", (code) => resolve(code === null ? 1 : code));
    entry.child.on("error", () => resolve(1));
  });
  if (exitCode !== 0 && !failedLabel) {
    failedLabel = entry.step.label;
  }
}

if (failedLabel) {
  console.error(`parallel build failed at: ${failedLabel}`);
  process.exit(1);
}
