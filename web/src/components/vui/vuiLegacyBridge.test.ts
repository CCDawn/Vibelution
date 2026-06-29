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
      "--vui-legacy-focus-ring",
    ]) {
      expect(bridgeSource).toContain(token);
    }

    expect(bridgeSource).toContain("[data-vui-app]");
    expect(bridgeSource).toContain(':where(button, [role="button"])');
    expect(bridgeSource).toContain('[class*="Button"]');
    expect(bridgeSource).toContain("box-shadow: none");
    expect(bridgeSource).not.toContain("border-width: 2px");
    expect(bridgeSource).not.toContain("width: 100%");
  });
});
