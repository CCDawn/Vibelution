import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * P0-a native slot takeover guard (theme.tailwind.css).
 *
 * The approved preview contract (web/preview/token-takeover, branch
 * codex/zcode-visual-theme-takeover) retargets the Tailwind built-in
 * font-size/radius slots onto the vui ladder inside `@theme inline` so
 * off-system class names (text-sm, rounded-lg, ...) still resolve inside the
 * design system. This gate fails if a future edit silently drops or retargets
 * one of those redefinitions, or if the underlying token values drift away
 * from the approved zero-drift mapping (only text-xl may shift: 20px -> 19px).
 *
 * Mapping (approved):
 *   text-xs -> var(--vui-font-2xs)   12px -> 12px
 *   text-sm -> var(--vui-font-xs)    14px -> 14px
 *   text-base -> var(--vui-font-md)  16px -> 16px
 *   text-lg -> var(--vui-font-lg)    18px -> 18px
 *   text-xl -> var(--vui-font-title) 20px -> 19px (only shift)
 *   rounded-lg -> var(--radius-control)            8px -> 8px
 *   rounded-xl -> var(--vui-radius-panel-soft)    12px -> 12px
 *
 * Value-literal expectations mirror tokens.css; className usage counts are
 * deliberately NOT asserted here — that is the ratchet's job
 * (visualTokenEscalationContract.test.ts), and the takeover intentionally
 * changes parsed values, not class names.
 */

const THEME_PATH = join(import.meta.dirname, "theme.tailwind.css");
const TOKENS_PATH = join(import.meta.dirname, "tokens.css");

/** slot -> the only variable the takeover may point at. */
const FONT_SLOT_TARGETS: Record<string, string> = {
  "--text-xs": "var(--vui-font-2xs)",
  "--text-sm": "var(--vui-font-xs)",
  "--text-base": "var(--vui-font-md)",
  "--text-lg": "var(--vui-font-lg)",
  "--text-xl": "var(--vui-font-title)",
};

const RADIUS_SLOT_TARGETS: Record<string, string> = {
  "--radius-lg": "var(--radius-control)",
  "--radius-xl": "var(--vui-radius-panel-soft)",
};

/** tokens.css literals the zero-drift basis relies on (rem @ 16px root). */
const TOKEN_VALUE_LITERALS: Record<string, string> = {
  "--vui-font-2xs": "0.75rem",
  "--vui-font-xs": "0.875rem",
  "--vui-font-md": "1rem",
  "--vui-font-lg": "1.125rem",
  "--vui-font-title": "1.1875rem",
  "--radius-control": "8px",
};

function readThemeBlock(source: string): string {
  const start = source.indexOf("@theme");
  expect(start).toBeGreaterThanOrEqual(0);
  const open = source.indexOf("{", start);
  const close = source.indexOf("}", open);
  expect(close).toBeGreaterThan(open);
  return source.slice(open, close);
}

function countDefinition(block: string, variable: string): number {
  return [...block.matchAll(new RegExp(`^\\s*${variable}\\s*:`, "gm"))].length;
}

describe("P0-a theme slot takeover contract", () => {
  const themeSource = readFileSync(THEME_PATH, "utf8");
  const tokensSource = readFileSync(TOKENS_PATH, "utf8");
  const themeBlock = readThemeBlock(themeSource);

  it("keeps every approved font-size slot retargeted inside @theme", () => {
    for (const [slot, target] of Object.entries(FONT_SLOT_TARGETS)) {
      expect(countDefinition(themeBlock, slot), `${slot} must be defined in @theme`).toBe(1);
      const definition = themeBlock.match(new RegExp(`${slot}\\s*:\\s*([^;]+);`))?.[1]?.trim();
      expect(definition, `${slot} must resolve through ${target}`).toBe(target);
    }
  });

  it("keeps the zero-drift radius slots retargeted inside @theme", () => {
    for (const [slot, target] of Object.entries(RADIUS_SLOT_TARGETS)) {
      expect(countDefinition(themeBlock, slot), `${slot} must be defined in @theme`).toBe(1);
      const definition = themeBlock.match(new RegExp(`${slot}\\s*:\\s*([^;]+);`))?.[1]?.trim();
      expect(definition, `${slot} must resolve through ${target}`).toBe(target);
    }
  });

  it("keeps the takeover documented with the approved mapping and pattern provenance", () => {
    expect(themeBlock).toContain("P0-a native-slot takeover");
    expect(themeBlock).toContain("zai-org/ZCode");
  });

  it("keeps tokens.css values matching the approved zero-drift basis", () => {
    for (const [token, literal] of Object.entries(TOKEN_VALUE_LITERALS)) {
      const definition = tokensSource.match(new RegExp(`${token}\\s*:\\s*([^;]+);`))?.[1]?.trim();
      expect(definition, `${token} drifted from the approved value`).toBe(literal);
    }
    // The light theme re-declares the panel radius; it must stay 12px too.
    const lightBlock = tokensSource.split('[data-theme="light"]')[1] ?? "";
    expect(lightBlock).toContain("--vui-radius-panel-soft: 12px");
  });

  it("keeps the shell .text-xs compatibility rule that pins live behavior", () => {
    // Discovered during integration: web/src/design/tailwind.css hand-overrides
    // .text-xs (unlayered rule => wins over the layered utility), so live
    // text-xs renders 14px/readable — NOT the Tailwind native 12px the preview
    // mapping assumed. Keeping this rule is what makes the takeover zero-drift
    // for text-xs; the @theme --text-xs retarget stays authoritative for
    // entries without this rule (route-css chunks). It must not be dropped
    // before the vui-type sweep migrates the class names.
    const shell = readFileSync(join(import.meta.dirname, "tailwind.css"), "utf8");
    expect(shell).toMatch(/\.text-xs\s*\{[^}]*font-size:\s*var\(--vui-font-xs\)/);
    expect(shell).toMatch(/\.text-xs\s*\{[^}]*line-height:\s*var\(--vui-line-readable\)/);
  });
});
