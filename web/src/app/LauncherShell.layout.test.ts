import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

const launcherShellSource = readFileSync(new URL("./LauncherShell.tsx", import.meta.url), "utf8");
const shellI18nSource = readFileSync(new URL("../i18n/useShellI18n.ts", import.meta.url), "utf8");
const launcherRouteSource = readFileSync(new URL("../routes/LauncherRoute.tsx", import.meta.url), "utf8");

describe("LauncherShell taskbar identity contract", () => {
  it("sets the document title to Launcher instead of Workbench", () => {
    expect(launcherShellSource).toContain('document.title = "Vibelution Launcher"');
    expect(launcherShellSource).not.toContain('document.title = t("appTitle")');
  });

  it("keeps shell language local so Launcher does not request workbench config", () => {
    expect(shellI18nSource).toContain("configEnabled");
    expect(shellI18nSource).toContain("enabled: configEnabled");
    expect(launcherShellSource).toContain("useShellI18n({ configEnabled: false })");
    expect(launcherRouteSource).toContain("useShellI18n({ configEnabled: false })");
  });
});
