import { describe, expect, it } from "vitest";
import appShellSource from "./AppShell.tsx?raw";

describe("AppShell lazy chunk recovery source contract", () => {
  it("wires the grace promise into the lazy settings menu loader", () => {
    expect(appShellSource).toContain("createReloadGracePromise");
    expect(appShellSource).toContain("browser.appshell_settings_menu_recovery.reload_vetoed");
    // The eternal pending placeholder for vetoed reloads must stay gone.
    expect(appShellSource).not.toContain("new Promise<{ default:");
  });
});
