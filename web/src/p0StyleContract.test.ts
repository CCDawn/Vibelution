import { readdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Repo-wide style contract for the P0 sweep.
 *
 * `components/vui` and `routes` have their own zero-baseline type contracts;
 * this one freezes the remaining debt in the rest of `web/src` so it may only
 * shrink. Type sizes must use the `text-vui-*` ladder (see
 * `components/vui/designs/primitives/type-scale.md`); radius uses the container
 * hierarchy (xl -> lg -> md -> sm, 2xl only for the composer shell and the
 * conversation status panel); spacing should follow the 4px rhythm; colours use
 * semantic tokens rather than white/black alpha utilities.
 */

const srcRoot = resolve(import.meta.dirname);

const BASELINES = {
  builtinText: 0,
  arbitraryText: 1,
  arbitraryRadius: 21,
  fixedRadius: 6,
  alphaUtility: 0,
  arbitrarySpacing: 290,
};

const PATTERNS: Record<keyof typeof BASELINES, RegExp> = {
  builtinText: /\btext-(?:sm|xs|base|lg|xl|2xl|3xl)\b/g,
  arbitraryText: /text-\[[0-9.]+(?:px|rem)\]/g,
  arbitraryRadius: /rounded(?:-[trblxy])?-\[[0-9.]+(?:px|rem)\]/g,
  fixedRadius: /rounded-(?:2xl|3xl)\b/g,
  alphaUtility: /\b(?:text|bg|border|ring|fill|stroke)-(?:white|black)\/[0-9]+/g,
  arbitrarySpacing: /\b(?:p|px|py|pt|pb|pl|pr|m|mx|my|mt|mb|ml|mr|gap|space-x|space-y)-\[[0-9.]+(?:px|rem)\]/g,
};

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
  return collectSourceFiles(srcRoot).reduce((total, file) => {
    const source = readFileSync(file, "utf8");
    return total + [...source.matchAll(pattern)].length;
  }, 0);
}

describe("P0 style contract", () => {
  for (const [name, pattern] of Object.entries(PATTERNS)) {
    it(`keeps ${name} at or below the frozen baseline`, () => {
      expect(countMatches(pattern)).toBeLessThanOrEqual(BASELINES[name as keyof typeof BASELINES]);
    });
  }
});
