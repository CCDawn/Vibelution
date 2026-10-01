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
});
