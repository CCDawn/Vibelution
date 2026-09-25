import { readdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Route-layer type-scale contract.
 *
 * Routes must use the product ladder (`text-vui-*`, including the micro steps)
 * documented in `../components/vui/designs/primitives/type-scale.md`. Built-in
 * Tailwind sizes are forbidden outright; arbitrary sizes are frozen at the one
 * remaining page-title outlier and may only shrink.
 */

const routesRoot = resolve(import.meta.dirname);

// One measured outlier: a 2rem page title with no matching step above 22px.
const ARBITRARY_TEXT_SIZE_BASELINE = 1;

const BUILTIN_TEXT_UTILITY = /\btext-(?:sm|xs|base|lg|xl|2xl|3xl)\b/g;
const ARBITRARY_TEXT_SIZE = /text-\[[0-9.]+(?:px|rem)\]/g;

function collectSourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = resolve(dir, entry.name);
    if (entry.isDirectory()) {
      return entry.name === "node_modules" ? [] : collectSourceFiles(full);
    }
    if (!/\.(ts|tsx)$/.test(entry.name) || /\.test\./.test(entry.name)) {
      return [];
    }
    return [full];
  });
}

function countMatches(pattern: RegExp): number {
  return collectSourceFiles(routesRoot).reduce((total, file) => {
    const source = readFileSync(file, "utf8");
    return total + [...source.matchAll(pattern)].length;
  }, 0);
}

describe("route type scale contract", () => {
  it("does not use built-in Tailwind text sizes in routes", () => {
    expect(countMatches(BUILTIN_TEXT_UTILITY)).toBe(0);
  });

  it("does not add arbitrary font sizes in routes", () => {
    expect(countMatches(ARBITRARY_TEXT_SIZE)).toBeLessThanOrEqual(
      ARBITRARY_TEXT_SIZE_BASELINE,
    );
  });
});
