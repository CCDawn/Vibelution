import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const sourceRoot = resolve(import.meta.dirname, "../..");
const mainSource = readFileSync(resolve(sourceRoot, "main.tsx"), "utf8");
const appShellSource = readFileSync(resolve(sourceRoot, "app", "AppShell.tsx"), "utf8");
const launcherShellSource = readFileSync(resolve(sourceRoot, "app", "LauncherShell.tsx"), "utf8");
const bridgeSource = readFileSync(resolve(sourceRoot, "design", "vui-legacy-bridge.css"), "utf8");

describe("VUI legacy bridge", () => {
  it("loads the legacy bridge after semantic tokens and scopes it to application shells", () => {
    expect(mainSource).toContain("./design/tokens.css");
    expect(mainSource).toContain("./design/vui-legacy-bridge.css");
    expect(mainSource.indexOf("./design/tokens.css")).toBeLessThan(
      mainSource.indexOf("./design/vui-legacy-bridge.css"),
    );

    expect(appShellSource).toContain('data-vui-app="workbench"');
    expect(launcherShellSource).toContain('data-vui-app="launcher"');
  });

  it("keeps legacy controls thin, quiet, and token-driven while pages migrate to VUI primitives", () => {
    for (const token of [
      "--vui-legacy-control-height",
      "--vui-legacy-control-radius",
      "--vui-legacy-control-border-width",
      "--vui-legacy-control-border",
      "--vui-legacy-control-bg",
      "--vui-legacy-control-bg-hover",
      "--vui-legacy-control-fg",
      "--vui-legacy-field-bg",
      "--vui-legacy-field-bg-hover",
      "--vui-legacy-field-fg",
      "--vui-legacy-field-placeholder",
      "--vui-legacy-control-gap",
      "--vui-legacy-control-font-size",
      "--vui-legacy-field-font-size",
      "--vui-legacy-focus-ring",
    ]) {
      expect(bridgeSource).toContain(token);
    }

    expect(bridgeSource).toContain("[data-vui-app]");
    expect(bridgeSource).toContain(':is(button, [role="button"], input, select, textarea)');
    expect(bridgeSource).toContain('[class*="Button"]');
    expect(bridgeSource).toContain('[class*="Action"]');
    expect(bridgeSource).toContain('[class*="Toggle"]');
    expect(bridgeSource).toContain('[class*="Tab"]');
    expect(bridgeSource).toContain('[class*="Icon"]');
    expect(bridgeSource).toContain("display: inline-flex");
    expect(bridgeSource).toContain("padding-inline: var(--vui-legacy-control-padding-x)");
    expect(bridgeSource).toContain("--vui-legacy-control-font-size: var(--font-size-caption)");
    expect(bridgeSource).toContain("--vui-legacy-field-font-size: var(--font-size-small)");
    expect(bridgeSource).toContain('input:not([type="checkbox"]):not([type="radio"]):not([type="range"])');
    expect(bridgeSource).toContain('input[type="checkbox"]');
    expect(bridgeSource).toContain("accent-color: var(--accent-cool)");
    expect(bridgeSource).toContain("select");
    expect(bridgeSource).toContain("textarea");
    expect(bridgeSource).toContain("box-shadow: none");
    expect(bridgeSource).not.toContain("border-width: 2px");
    expect(bridgeSource).not.toContain("width: 100%");
  });

  it("keeps the legacy bridge free of raw color fallbacks outside the token source", () => {
    expect(bridgeSource).not.toMatch(/#[0-9a-fA-F]{3,8}/);
    expect(bridgeSource).not.toMatch(/rgba?\(/);
  });
});
