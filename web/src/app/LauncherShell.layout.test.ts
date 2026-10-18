import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

const launcherShellSource = readFileSync(new URL("./LauncherShell.tsx", import.meta.url), "utf8");
const launcherLanguageSource = readFileSync(new URL("../i18n/useLauncherLanguage.ts", import.meta.url), "utf8");
const launcherRouteSource = readFileSync(new URL("../routes/LauncherRoute.tsx", import.meta.url), "utf8");

describe("LauncherShell taskbar identity contract", () => {
  it("sets the document title to Launcher instead of Workbench", () => {
    expect(launcherShellSource).toContain("document.title = launcherWindowTitle");
    expect(launcherShellSource).toContain("currentInstanceWindowTitle(\"launcher\"");
    expect(launcherShellSource).not.toContain('document.title = t("appTitle")');
    expect(launcherShellSource).not.toContain('document.title = "Vibelution Launcher"');
  });

  it("keeps shell language local so Launcher does not request workbench config", () => {
    expect(launcherLanguageSource).toContain("queryKeys.launcherStatus()");
    expect(launcherLanguageSource).toContain("queryFn: getLauncherStatus");
    expect(launcherLanguageSource).not.toContain("fetchPublicConfig");
    expect(launcherShellSource).toContain("useLauncherLanguage()");
    expect(launcherRouteSource).toContain("useLauncherLanguage()");
  });
});
