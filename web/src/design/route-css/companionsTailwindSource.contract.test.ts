/**
 * companions.tailwind.css source-coverage contract.
 *
 * The companion surfaces keep their Tailwind class maps in route-local files.
 * Because the route entry opts into `source(none)`, every production file in
 * routes/companions must be covered explicitly or its utilities disappear in
 * the lobby and native Chat rails.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, resolve } from "node:path";

import { describe, expect, it } from "vitest";

const routeCssDir = import.meta.dirname;
const srcRoot = resolve(routeCssDir, "../..");
const companionsDir = join(srcRoot, "routes/companions");
const cssPath = join(routeCssDir, "companions.tailwind.css");

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

describe("companions.tailwind.css source coverage", () => {
  const css = readFileSync(cssPath, "utf8");
  const { positive, negative } = parseSources(css);
  const files = walk(companionsDir);
  const productionFiles = files.filter((file) => !/\.test\.(ts|tsx)$/.test(file));
  const testFiles = files.filter((file) => /\.test\.(ts|tsx)$/.test(file));

  it("covers every production source file under routes/companions", () => {
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

  it("loads the same entry for the lobby and native Chat portrait", () => {
    expect(css).toContain('@source "../../routes/companions/**/*.{ts,tsx}";');
    expect(css).toContain('@source not "../../routes/companions/**/*.test.{ts,tsx}";');
    expect(css).toContain('[data-chat-responsive-mode="wide"]');
    expect(css).toContain("minmax(280px, max(280px");
    expect(readFileSync(resolve(srcRoot, "routes/CompanionsRoute.tsx"), "utf8")).toContain(
      'import "../design/route-css/companions.tailwind.css";',
    );
    expect(readFileSync(resolve(companionsDir, "CompanionPortrait.tsx"), "utf8")).toContain(
      'import "../../design/route-css/companions.tailwind.css";',
    );
  });
});
