import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

const launcherShellSource = readFileSync(new URL("./LauncherShell.tsx", import.meta.url), "utf8");

describe("LauncherShell taskbar identity contract", () => {
  it("sets the document title to Launcher instead of Workbench", () => {
    expect(launcherShellSource).toContain('document.title = "Vibelution Launcher"');
    expect(launcherShellSource).not.toContain('document.title = t("appTitle")');
  });
});
