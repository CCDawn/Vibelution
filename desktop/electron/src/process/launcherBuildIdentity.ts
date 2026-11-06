import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { resolve } from "node:path";
import { sha256DirectoryTree } from "../packaging/frontendBundle.js";

export type LauncherBuild = Readonly<{
  kind: "packaged" | "unpackaged";
  id: string;
  electronTree: string;
  sourceCommit?: string;
  builtAt?: string;
}>;

const objectHash = /^(?:[0-9a-f]{40}|[0-9a-f]{64})$/;
const sha256 = /^[0-9a-f]{64}$/;

export function parseLauncherBuild(value: unknown, kind: LauncherBuild["kind"]): LauncherBuild | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const build = value as Record<string, unknown>;
  if (build.kind !== kind || typeof build.id !== "string" || !sha256.test(build.id)
    || typeof build.electronTree !== "string" || !objectHash.test(build.electronTree)) return null;
  return Object.freeze({ kind, id: build.id, electronTree: build.electronTree,
    ...(typeof build.sourceCommit === "string" && objectHash.test(build.sourceCommit) ? { sourceCommit: build.sourceCommit } : {}),
    ...(typeof build.builtAt === "string" && Number.isFinite(Date.parse(build.builtAt)) ? { builtAt: build.builtAt } : {}),
  });
}

/** Capture once, before bootstrap. A later disk promotion cannot rewrite the running identity. */
export function captureRunningLauncherBuild(input: {
  packaged: boolean;
  desktopBundleRoot: string;
  resourcesRoot: string;
}): LauncherBuild | null {
  try {
    const kind = input.packaged ? "packaged" : "unpackaged";
    const provenance = JSON.parse(readFileSync(input.packaged
      ? resolve(input.resourcesRoot, "app.asar.unpacked", "package-provenance.json")
      : resolve(input.desktopBundleRoot, "unpackaged-provenance.json"), "utf8"));
    let id: string;
    if (input.packaged) {
      const parts = [provenance.electronTreeHash, provenance.mainBundleSha256, provenance.preloadBundleSha256,
        provenance.frontendContentSha256, provenance.assistant?.contentSha256];
      if (!objectHash.test(parts[0] ?? "") || !parts.slice(1).every((part) => typeof part === "string" && sha256.test(part))) return null;
      // Electron's patched fs treats app.asar as a directory. Read the actual
      // archive so changes in imported modules are included in the build ID.
      const rawRead = process.versions.electron
        ? (createRequire(import.meta.url)("original-fs") as typeof import("node:fs")).readFileSync : readFileSync;
      const archiveHash = createHash("sha256").update(rawRead(resolve(input.resourcesRoot, "app.asar"))).digest("hex");
      id = createHash("sha256").update(JSON.stringify([kind, ...parts, archiveHash]), "utf8").digest("hex");
    } else {
      // The source tree alone cannot distinguish two builds made from dirty sources.
      readFileSync(resolve(input.desktopBundleRoot, "main.js"));
      readFileSync(resolve(input.desktopBundleRoot, "preload.cjs"));
      id = sha256DirectoryTree(input.desktopBundleRoot);
    }
    return parseLauncherBuild({ kind, id, electronTree: provenance.electronTreeHash,
      sourceCommit: provenance.sourceCommit, builtAt: provenance.builtAt }, kind);
  } catch {
    // Legacy or incomplete metadata must never be replaced with the current checkout HEAD.
    return null;
  }
}
