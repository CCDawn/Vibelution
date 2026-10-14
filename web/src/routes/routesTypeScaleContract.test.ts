import { readdirSync, readFileSync } from "node:fs";
import { relative, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import visualBaseline from "../design/visualTokenEscalation.baseline.json";

/**
 * Route-layer type-scale contract.
 *
 * Routes should use the product ladder (`text-vui-*`, including the micro steps)
 * documented in `../components/vui/designs/primitives/type-scale.md`. Built-in
 * and arbitrary sizes already on these pages are frozen at the current debt
 * and may only shrink. This ceiling does not restyle those pages.
 */

const routesRoot = resolve(import.meta.dirname);

// The authoritative no-growth budget is per file, shared with the visual-token
// ratchet. Old aggregate limits predated the Finance/Teams route migration.

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

function grownFiles(pattern: RegExp, baseline: Record<string, number>): string[] {
  return collectSourceFiles(routesRoot).flatMap((file) => {
    const source = readFileSync(file, "utf8");
    const count = [...source.matchAll(pattern)].length;
    const path = relative(resolve(routesRoot, ".."), file).replaceAll("\\", "/");
    const ceiling = baseline[path] ?? 0;
    return count > ceiling ? [`${path}: ${count} > ${ceiling}`] : [];
  });
}

describe("route type scale contract", () => {
  it("does not grow built-in Tailwind text sizes in routes", () => {
    expect(grownFiles(BUILTIN_TEXT_UTILITY, visualBaseline.categories.builtinFontSize.files)).toEqual([]);
  });

  it("does not add arbitrary font sizes in routes", () => {
    expect(grownFiles(ARBITRARY_TEXT_SIZE, visualBaseline.categories.arbitraryTextSize.files)).toEqual([]);
  });
});
