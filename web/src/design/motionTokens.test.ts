import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Wave 5B motion token guard.
 *
 * Locks the tokens.css Motion section (sanctioned durations + emphasis curve),
 * the composed --vui-transition shorthand, the Tailwind v4 --ease-* theme
 * slots that generate ease-vui / ease-vui-out, and the global
 * prefers-reduced-motion fallback in base.css. Read-only file assertions in
 * the same style as themeSlotTakeoverContract.test.ts; the P0-a slot takeover
 * locks are intentionally NOT re-asserted here (they have their own guard).
 */

const TOKENS_PATH = join(import.meta.dirname, "tokens.css");
const THEME_PATH = join(import.meta.dirname, "theme.tailwind.css");
const BASE_PATH = join(import.meta.dirname, "base.css");

/** Motion section tokens -> the exact value literals the system relies on. */
const MOTION_TOKEN_LITERALS: Record<string, string> = {
  "--vui-motion-duration-fast": "120ms",
  "--vui-motion-duration-base": "150ms",
  "--vui-motion-duration-slow": "240ms",
  "--vui-ease-out-quart": "cubic-bezier(0.23, 1, 0.32, 1)",
};

function readDefinition(source: string, variable: string): string | null {
  const match = source.match(new RegExp(`^\\s*${variable}\\s*:\\s*([^;]+);`, "m"));
  return match?.[1]?.trim() ?? null;
}

describe("motion tokens (Wave 5B)", () => {
  it("declares the sanctioned duration ladder and emphasis curve in tokens.css", () => {
    const source = readFileSync(TOKENS_PATH, "utf-8");
    for (const [variable, literal] of Object.entries(MOTION_TOKEN_LITERALS)) {
      expect(readDefinition(source, variable), variable).toBe(literal);
    }
  });

  it("composes --vui-transition from the base duration and the base ease", () => {
    const source = readFileSync(TOKENS_PATH, "utf-8");
    expect(readDefinition(source, "--vui-transition")).toBe(
      "var(--vui-motion-duration-base) var(--vui-ease)",
    );
  });

  it("exposes exactly two ease slots in the Tailwind theme", () => {
    const source = readFileSync(THEME_PATH, "utf-8");
    const themeStart = source.indexOf("@theme");
    expect(themeStart).toBeGreaterThanOrEqual(0);
    const themeBlock = source.slice(themeStart, source.indexOf("}", themeStart));
    expect(readDefinition(themeBlock, "--ease-vui")).toBe("var(--vui-ease)");
    expect(readDefinition(themeBlock, "--ease-vui-out")).toBe("var(--vui-ease-out-quart)");
    // No other ease slots — the motion surface stays intentionally small.
    expect([...themeBlock.matchAll(/^\s*--ease-/gm)]).toHaveLength(2);
  });

  it("keeps the global prefers-reduced-motion fallback in base.css", () => {
    const source = readFileSync(BASE_PATH, "utf-8");
    const blockStart = source.indexOf("@media (prefers-reduced-motion: reduce)");
    expect(blockStart).toBeGreaterThanOrEqual(0);
    const block = source.slice(blockStart, source.indexOf("}", blockStart));
    expect(block).toContain("animation-duration: 0.01ms");
    expect(block).toContain("animation-iteration-count: 1");
    expect(block).toContain("transition-duration: 0.01ms");
    expect(block).toContain("scroll-behavior: auto");
  });
});
