/**
 * agents.tailwind.css source-coverage contract for nested Agent panels.
 *
 * The route stylesheet uses `source(none)`, so every production file that owns
 * utility classes must be covered by an explicit @source glob. This catches
 * nested Agent panels whose styles would otherwise silently ship unstyled.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, resolve } from "node:path";

import { describe, expect, it } from "vitest";

const routeCssDir = import.meta.dirname;
const srcRoot = resolve(routeCssDir, "../..");
const perceptionDir = join(srcRoot, "routes/agentPerception");
const cssPath = join(routeCssDir, "agents.tailwind.css");
const routePath = join(srcRoot, "routes/AgentsRoute.tsx");

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
    if (match[1]) negative.push(pattern);
    else positive.push(pattern);
  }
  return { positive, negative };
}

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) return walk(full);
    return /\.(ts|tsx)$/.test(entry) ? [full.replaceAll("\\", "/")] : [];
  });
}

describe("agents.tailwind.css perception source coverage", () => {
  const css = readFileSync(cssPath, "utf8");
  const { positive, negative } = parseSources(css);
  const files = walk(perceptionDir);
  const productionFiles = files.filter((file) => !/\.test\.(ts|tsx)$/.test(file));
  const testFiles = files.filter((file) => /\.test\.(ts|tsx)$/.test(file));

  it("loads the route-scoped stylesheet from the Agent control center", () => {
    expect(readFileSync(routePath, "utf8")).toContain('import "../design/route-css/agents.tailwind.css";');
  });

  it("covers every production source file under routes/agentPerception", () => {
    const uncovered = productionFiles.filter(
      (file) =>
        !positive.some((pattern) => pattern.test(file)) ||
        negative.some((pattern) => pattern.test(file)),
    );
    expect(uncovered).toEqual([]);
  });

  it("keeps perception tests out of the scanned route sources", () => {
    const leaked = testFiles.filter(
      (file) =>
        positive.some((pattern) => pattern.test(file)) &&
        !negative.some((pattern) => pattern.test(file)),
    );
    expect(leaked).toEqual([]);
  });

  it("actually walks the perception panel source tree (sanity)", () => {
    expect(productionFiles.length).toBeGreaterThan(3);
    expect(testFiles.length).toBeGreaterThan(0);
  });
});
