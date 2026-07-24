/**
 * Wave 3C contract — Reference Lab semantic roles stay pinned to production tokens.
 *
 * Lab is preview-only; production consumes tokens.css + recipes. This test freezes
 * the Lab → token wiring so Lab CSS cannot silently drift off the approved map.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const designRoot = resolve(import.meta.dirname);
const webRoot = resolve(import.meta.dirname, "../..");
const docsRoot = resolve(import.meta.dirname, "../../../docs/superpowers/plans");

const labCss = readFileSync(resolve(designRoot, "vui-reference-lab.css"), "utf8");
const mapDoc = readFileSync(
  resolve(docsRoot, "2026-07-24-vui-wave3c-reference-lab-token-map.md"),
  "utf8",
);
const surfaceRecipes = readFileSync(resolve(designRoot, "vuiSurfaceRecipes.ts"), "utf8");
const chromeRecipes = readFileSync(resolve(designRoot, "vuiChromeRecipes.ts"), "utf8");
const tokensCss = readFileSync(resolve(designRoot, "tokens.css"), "utf8");
const labHtml = readFileSync(resolve(webRoot, "vui-reference-lab.html"), "utf8");

/** Lab role → production token (must appear in Lab :root aliases). */
const LAB_SURFACE_MAP: Record<string, string> = {
  "--lab-workspace": "--vui-surface-base",
  "--lab-region": "--vui-surface-rail",
  "--lab-card": "--vui-surface-panel",
  "--lab-inset": "--vui-surface-row",
  "--lab-control": "--vui-control-muted",
  "--lab-popover": "--vui-surface-glass",
  "--lab-line": "--vui-border-subtle",
  "--lab-line-strong": "--vui-border-strong",
  "--lab-ink": "--fg-primary",
  "--lab-muted": "--fg-secondary",
  "--lab-soft": "--fg-tertiary",
  "--lab-accent": "--accent-cool",
  "--lab-danger": "--state-error",
};

describe("Wave 3C Reference Lab ↔ token map", () => {
  it("keeps Lab surface aliases pinned to production tokens", () => {
    for (const [labVar, token] of Object.entries(LAB_SURFACE_MAP)) {
      const pattern = new RegExp(
        `${labVar.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*:\\s*var\\(${token.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\)`,
      );
      expect(labCss, `${labVar} must map to ${token}`).toMatch(pattern);
      expect(tokensCss, `token ${token} must exist in tokens.css`).toContain(token);
    }
  });

  it("exposes production recipes for each Lab surface role", () => {
    const requiredRecipes = [
      "vuiWorkspaceFillClass",
      "vuiRailFillClass",
      "vuiOpaquePanelClass",
      "vuiDenseRowClass",
      "vuiGlassPanelClass",
      "vuiChatFillClass",
      "vuiControlQuietClass",
      "vuiControlIconSmClass",
      "vuiControlPillClass",
    ];
    for (const name of requiredRecipes) {
      const source = name.startsWith("vuiControl") ? chromeRecipes : surfaceRecipes;
      expect(source, `${name} must be exported`).toContain(`export const ${name}`);
    }
  });

  it("documents Lab roles and page recipes in the Wave 3C map", () => {
    expect(mapDoc).toContain("Reference Lab");
    expect(mapDoc).toContain("--lab-workspace");
    expect(mapDoc).toContain("--vui-surface-panel");
    expect(mapDoc).toContain("vuiOpaquePanelClass");
    expect(mapDoc).toContain("vuiGlassPanelClass");
    expect(mapDoc).toContain("chat-session-workbench");
    expect(mapDoc).toContain("settings-form-page");
    expect(mapDoc).toContain("list-detail-page");
    expect(mapDoc).toContain("dense-ops-page");
    expect(mapDoc).toMatch(/\*\*Status:\*\*\s*complete/);
  });

  it("keeps Reference Lab isolated from the production router", () => {
    expect(labHtml).toContain("未接入生产");
    expect(labCss).toContain("Do not import from production routes");
    // Lab must not be a React route module under src/routes.
    expect(labHtml).not.toContain("from \"react-router");
  });

  it("pins control density tokens used by chrome recipes", () => {
    expect(tokensCss).toContain("--vui-control-height-sm");
    expect(tokensCss).toContain("--vui-control-height-md");
    expect(chromeRecipes).toContain("var(--vui-control-height-sm)");
    expect(chromeRecipes).toContain("var(--radius-control)");
  });
});
