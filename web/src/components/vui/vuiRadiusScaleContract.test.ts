import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

/**
 * VUI radius-scale contract.
 *
 * `--vui-radius-soft` is the registered 10px radius (see `design/tokens.css`).
 * A raw `rounded-[10px]` is the same value spelled as a literal, so it is a
 * design-system defect rather than a deliberate size; use the token instead.
 *
 * Scope: the directories this contract owns (`components/vui`, `routes`).
 * `components/conversation` carries its own reading-hierarchy contract.
 */
const SRC = fileURLToPath(new URL("../..", import.meta.url));
const SCOPES = ["components/vui", "routes"];

// Split literal: the scan must not match its own source text.
const RAW_SOFT_RADIUS = "rounded-" + "[10px]";
const ARBITRARY_SOFT_RADIUS = "[var(--vui-radius-" + "soft)]";

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      if (entry === "node_modules" || entry === "dist") continue;
      walk(full, out);
      continue;
    }
    if (!/\.tsx?$/.test(entry) || entry.includes(".test.")) continue;
    out.push(full);
  }
  return out;
}

describe("VUI radius scale contract", () => {
  it("keeps the 10px corner on the registered radius token", () => {
    const offenders: string[] = [];
    for (const scope of SCOPES) {
      for (const file of walk(join(SRC, scope))) {
        if (readFileSync(file, "utf8").includes(RAW_SOFT_RADIUS)) {
          offenders.push(relative(SRC, file).replace(/\\/g, "/"));
        }
      }
    }
    expect(offenders).toEqual([]);
  });

  it("uses the rounded-vui-soft utility instead of the arbitrary-value form", () => {
    const offenders: string[] = [];
    // `routes` still carries active sibling work; widen this scope once it lands.
    for (const scope of ["components/vui"]) {
      for (const file of walk(join(SRC, scope))) {
        if (readFileSync(file, "utf8").includes(ARBITRARY_SOFT_RADIUS)) {
          offenders.push(relative(SRC, file).replace(/\\/g, "/"));
        }
      }
    }
    expect(offenders).toEqual([]);
  });

  it("exposes the soft radius as a Tailwind utility in the shared theme", () => {
    const theme = readFileSync(join(SRC, "design", "theme.tailwind.css"), "utf8");
    expect(theme).toContain("--radius-vui-soft: var(--vui-radius-soft);");
  });
});
