import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import {
  createDesktopPackageProvenance,
  type DesktopPackageProvenance
} from "../packaging/packageProvenance.js";

export type WritePackageProvenanceArgs = {
  workspaceRoot: string;
  outputPath: string;
};

const ARGUMENTS: Record<string, keyof WritePackageProvenanceArgs> = {
  "--workspace-root": "workspaceRoot",
  "--output": "outputPath"
};

export function parseWritePackageProvenanceArgs(argv: string[]): WritePackageProvenanceArgs {
  const result: Partial<WritePackageProvenanceArgs> = {};
  for (let index = 0; index < argv.length; index += 1) {
    const flag = argv[index];
    const key = ARGUMENTS[flag];
    if (!key) {
      throw new Error(`Unknown package provenance argument: ${flag}`);
    }
    const value = String(argv[index + 1] || "").trim();
    if (!value) {
      throw new Error(`Missing required package provenance argument: ${flag}`);
    }
    result[key] = value;
    index += 1;
  }
  for (const [flag, key] of Object.entries(ARGUMENTS)) {
    if (!result[key]) {
      throw new Error(`Missing required package provenance argument: ${flag}`);
    }
  }
  return result as WritePackageProvenanceArgs;
}

export function runWritePackageProvenanceCli(argv: string[] = process.argv.slice(2)): string {
  const args = parseWritePackageProvenanceArgs(argv);
  const workspaceRoot = resolve(args.workspaceRoot);
  const outputPath = resolve(args.outputPath);
  const provenance = createDesktopPackageProvenance({
    sourceCommit: runGit(workspaceRoot, ["rev-parse", "HEAD"]),
    electronTreeHash: runGit(workspaceRoot, ["rev-parse", "HEAD:desktop/electron"]),
    frontendTreeHash: runGit(workspaceRoot, ["rev-parse", "HEAD:web"]),
    mainBundleSha256: sha256File(resolve("dist", "main.js")),
    preloadBundleSha256: sha256File(resolve("dist", "preload.cjs")),
    builtAt: new Date().toISOString()
  });
  writeDesktopPackageProvenance(outputPath, provenance);
  return outputPath;
}

export function writeDesktopPackageProvenance(outputPath: string, provenance: DesktopPackageProvenance): void {
  mkdirSync(dirname(outputPath), { recursive: true });
  writeFileSync(outputPath, `${JSON.stringify(provenance, null, 2)}\n`, "utf8");
}

function runGit(workspaceRoot: string, args: string[]): string {
  return execFileSync("git", args, {
    cwd: workspaceRoot,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
    windowsHide: true
  }).trim();
}

function sha256File(path: string): string {
  return createHash("sha256").update(readFileSync(path)).digest("hex");
}

function isDirectRun(): boolean {
  const entrypoint = process.argv[1];
  return Boolean(entrypoint) && import.meta.url === pathToFileURL(entrypoint).href;
}

if (isDirectRun()) {
  try {
    const outputPath = runWritePackageProvenanceCli();
    console.log(`Wrote desktop package provenance: ${outputPath}`);
  } catch (error: unknown) {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  }
}
