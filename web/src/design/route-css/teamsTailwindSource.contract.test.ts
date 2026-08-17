/**
 * teams.tailwind.css source-coverage contract.
 *
 * The Teams route CSS entry uses `@import "tailwindcss" source(none)`, so only
 * files listed via explicit `@source` directives contribute utilities. A styles
 * file or component under `routes/teams/` that is not covered ships zero of its
 * Tailwind classes to the browser (borders/grid/sizing silently missing).
 *
 * This test walks every non-test `.ts/.tsx` file under `routes/teams/` and
 * requires it to match at least one positive @source glob, and requires test
 * files to stay excluded (a class quoted only in a test must not mask a missing
 * production source).
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, resolve } from "node:path";

import { describe, expect, it } from "vitest";

const routeCssDir = import.meta.dirname;
const srcRoot = resolve(routeCssDir, "../..");
const teamsDir = join(srcRoot, "routes/teams");
const cssPath = join(routeCssDir, "teams.tailwind.css");

function escapeRegExp(text: string) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Convert the repo's simple @source globs (`*`, `**`, `{a,b}`) to a RegExp. */
function globToRegExp(glob: string): RegExp {
  let out = "";
  let i = 0;
  while (i < glob.length) {
    const ch = glob[i];
    if (ch === "*") {
      if (glob[i + 1] === "*") {
        if (glob[i + 2] === "/") {
          out += "(?:.*/)?";
          i += 3;
        } else {
          out += ".*";
          i += 2;
        }
      } else {
        out += "[^/]*";
        i += 1;
      }
    } else if (ch === "{") {
      const close = glob.indexOf("}", i);
      const body = glob
        .slice(i + 1, close)
        .split(",")
        .map(escapeRegExp)
        .join("|");
      out += `(?:${body})`;
      i = close + 1;
    } else {
      out += escapeRegExp(ch);
      i += 1;
    }
  }
  return new RegExp(`^${out}$`);
}

function parseSources(css: string) {
  const positive: RegExp[] = [];
  const negative: RegExp[] = [];
  for (const match of css.matchAll(/@source\s+(not\s+)?"([^"]+)"\s*;/g)) {
    const absolute = resolve(routeCssDir, match[2]).replaceAll("\\", "/");
    const pattern = globToRegExp(absolute);
    if (match[1]) {
      negative.push(pattern);
    } else {
      positive.push(pattern);
    }
  }
  return { positive, negative };
}

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      return walk(full);
    }
    return /\.(ts|tsx)$/.test(entry) ? [full.replaceAll("\\", "/")] : [];
  });
}

describe("teams.tailwind.css source coverage", () => {
  const css = readFileSync(cssPath, "utf8");
  const { positive, negative } = parseSources(css);
  const files = walk(teamsDir);
  const productionFiles = files.filter((file) => !/\.test\.(ts|tsx)$/.test(file));
  const testFiles = files.filter((file) => /\.test\.(ts|tsx)$/.test(file));

  it("covers every production source file under routes/teams", () => {
    const uncovered = productionFiles.filter(
      (file) =>
        !positive.some((pattern) => pattern.test(file)) ||
        negative.some((pattern) => pattern.test(file)),
    );
    expect(uncovered).toEqual([]);
  });

  it("keeps test files out of the scanned sources", () => {
    const leaked = testFiles.filter(
      (file) =>
        positive.some((pattern) => pattern.test(file)) &&
        !negative.some((pattern) => pattern.test(file)),
    );
    expect(leaked).toEqual([]);
  });

  it("actually walks the teams tree (sanity)", () => {
    expect(productionFiles.length).toBeGreaterThan(50);
    expect(testFiles.length).toBeGreaterThan(10);
  });
});
