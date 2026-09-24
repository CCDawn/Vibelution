import { readdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * VUI type-scale contract.
 *
 * The product type ladder is `text-vui-*`, registered in
 * `design/theme.tailwind.css` from the `--vui-font-*` values in `design/tokens.css`
 * (see `designs/primitives/type-scale.md`). Built-in Tailwind text sizes
 * (`text-sm`, `text-xs`, ...) and arbitrary sizes (`text-[13px]`) are design-system
 * defects: new ones must not appear, and existing ones may only shrink.
 */

const vuiRoot = resolve(import.meta.dirname);
const themeCssPath = resolve(import.meta.dirname, "../../design/theme.tailwind.css");

// Measured debt at the time the contract landed; these are ceilings, not targets.
const BUILTIN_TEXT_UTILITY_BASELINE = 17;
const ARBITRARY_TEXT_SIZE_BASELINE = 45;

const BUILTIN_TEXT_UTILITY = /\btext-(?:sm|xs|base|lg|xl|2xl|3xl)\b/g;
const ARBITRARY_TEXT_SIZE = /text-\[[0-9.]+(?:px|rem)\]/g;

function collectSourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = resolve(dir, entry.name);
    if (entry.isDirectory()) {
      return entry.name === "node_modules" || entry.name === "designs"
        ? []
        : collectSourceFiles(full);
    }
    if (!/\.(ts|tsx)$/.test(entry.name) || /\.test\./.test(entry.name)) {
      return [];
    }
    return [full];
  });
}

function countMatches(pattern: RegExp): number {
  return collectSourceFiles(vuiRoot).reduce((total, file) => {
    const source = readFileSync(file, "utf8");
    return total + [...source.matchAll(pattern)].length;
  }, 0);
}

describe("VUI type scale contract", () => {
  it("exposes the product type ladder as text-vui-* utilities", () => {
    const themeCss = readFileSync(themeCssPath, "utf8");
    for (const token of [
      "--text-vui-2xs",
      "--text-vui-xs",
      "--text-vui-sm",
      "--text-vui-md",
      "--text-vui-chat",
      "--text-vui-lg",
      "--text-vui-title",
      "--text-vui-xl",
    ]) {
      expect(themeCss).toContain(token);
    }
    // The ladder must stay sourced from tokens.css, not hard-coded values.
    expect(themeCss).toContain("--text-vui-md: var(--vui-font-md);");
  });

  it("does not add built-in Tailwind text sizes under components/vui", () => {
    expect(countMatches(BUILTIN_TEXT_UTILITY)).toBeLessThanOrEqual(
      BUILTIN_TEXT_UTILITY_BASELINE,
    );
  });

  it("does not add arbitrary font sizes under components/vui", () => {
    expect(countMatches(ARBITRARY_TEXT_SIZE)).toBeLessThanOrEqual(
      ARBITRARY_TEXT_SIZE_BASELINE,
    );
  });
});
