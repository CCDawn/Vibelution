import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

import {
  classifyVuiSurfaceColorMix,
  extractColorMixCalls,
  isStyleMapPath,
  scanSourceForVuiSurfaceAlpha,
} from "./vuiSurfaceAlphaPolicy";

const srcRoot = join(import.meta.dirname, "..");

function walkFiles(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    const st = statSync(full);
    if (st.isDirectory()) {
      if (name === "node_modules" || name === "dist") continue;
      walkFiles(full, out);
      continue;
    }
    if (!/\.(ts|tsx|css)$/.test(name)) continue;
    if (/\.test\.(ts|tsx)$/.test(name)) continue;
    if (name.startsWith("migrate_vui_surface")) continue;
    out.push(full);
  }
  return out;
}

describe("vuiSurfaceAlphaPolicy", () => {
  it("classifies accent+surface mixes as allowed state-tint", () => {
    const hit = classifyVuiSurfaceColorMix(
      "color-mix(in srgb, var(--accent-cool) 10%, var(--vui-surface-row))",
      "routes/AgentsRoute.styles.ts",
      "",
    );
    expect(hit.role).toBe("state-tint");
    expect(hit.allowed).toBe(true);
  });

  it("classifies surface+transparent as forbidden structure wash", () => {
    const hit = classifyVuiSurfaceColorMix(
      "color-mix(in_srgb,var(--vui-surface-panel)_58%,transparent)",
      "routes/ResearchRoute.styles.ts",
      "panel: \"bg-[color-mix(...)]\"",
    );
    expect(hit.role).toBe("forbidden-structure-wash");
    expect(hit.allowed).toBe(false);
  });

  it("allows Chat centerSurface soft layer", () => {
    const source = 'centerSurface: "bg-[color-mix(in_srgb,var(--vui-surface-panel)_6%,transparent)]"';
    const hit = classifyVuiSurfaceColorMix(
      "color-mix(in_srgb,var(--vui-surface-panel)_6%,transparent)",
      "routes/ChatCodingRoute.styles.ts",
      source,
    );
    expect(hit.role).toBe("chat-soft-layer");
    expect(hit.allowed).toBe(true);
  });

  it("allows glass overlay mixes", () => {
    const hit = classifyVuiSurfaceColorMix(
      "color-mix(in_srgb,var(--vui-surface-glass)_58%,transparent)",
      "components/layout/PaneCollapseHandle.styles.ts",
      "",
    );
    expect(hit.role).toBe("glass-overlay");
    expect(hit.allowed).toBe(true);
  });

  it("extracts nested color-mix calls without truncating", () => {
    const source =
      "a color-mix(in srgb, var(--accent-cool) 10%, var(--vui-surface-row)) b color-mix(in srgb, var(--vui-surface-panel) 70%, transparent) c";
    const mixes = extractColorMixCalls(source).filter((m) => m.includes("vui-surface"));
    expect(mixes).toHaveLength(2);
  });

  it("forbids structural surface+transparent washes in production style maps", () => {
    const files = walkFiles(srcRoot);
    const violations: string[] = [];

    for (const full of files) {
      const rel = relative(srcRoot, full).replace(/\\/g, "/");
      // Page style maps are the enforcement surface; VUI primitives own soft materials.
      if (!isStyleMapPath(rel)) continue;

      const source = readFileSync(full, "utf8");
      const hits = scanSourceForVuiSurfaceAlpha(source, rel);
      for (const hit of hits) {
        if (!hit.allowed) {
          violations.push(`${hit.file}: ${hit.role} :: ${hit.mix}`);
        }
      }
    }

    expect(violations, violations.slice(0, 40).join("\n")).toEqual([]);
  });
});
