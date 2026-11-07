import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

type DesktopEntryCatalog = {
  schemaVersion: number;
  publicProductEntries: Array<{
    id: string;
    label: string;
    pathBase: string;
    path: string;
    arguments: string[];
    target: string;
    windowProvider: string;
    shortcutAllowed: boolean;
    publicProductEntry: boolean;
  }>;
  operatorEntries: Array<{
    id: string;
    path: string;
    publicProductEntry: boolean;
  }>;
  fallbackProviders: Array<{
    id: string;
    provider: string;
    publicProductEntry: boolean;
  }>;
  forbiddenProductEntries: Array<{
    id: string;
    target: string;
  }>;
  deepLinks: Array<{
    route: string;
    publicProductEntry: boolean;
  }>;
};

const catalogPath = fileURLToPath(new URL("../desktop-entry-catalog.json", import.meta.url));
const helperScriptPath = fileURLToPath(new URL("../../../scripts/desktop_entry_catalog.ps1", import.meta.url));

function readCatalog(): DesktopEntryCatalog {
  return JSON.parse(readFileSync(catalogPath, "utf8")) as DesktopEntryCatalog;
}

describe("desktop entry catalog", () => {
  it("declares the managed native assistant as the only public product entry", () => {
    const catalog = readCatalog();

    expect(catalog.schemaVersion).toBe(1);
    expect(catalog.publicProductEntries).toHaveLength(1);
    expect(catalog.publicProductEntries[0]).toMatchObject({
      id: "vibelution-desktop-package",
      label: "Vibelution",
      pathBase: "localAppData",
      path: "Vibelution/Launcher/VibelutionLauncher.exe",
      arguments: ["--assistant"],
      target: "launcher",
      windowProvider: "electron",
      shortcutAllowed: true,
      publicProductEntry: true
    });
  });

  it("keeps operator scripts and fallback providers outside the public product surface", () => {
    const catalog = readCatalog();

    expect(catalog.operatorEntries).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          id: "desktop-package-artifact",
          pathBase: "project",
          path: "dist/desktop/win-unpacked/Vibelution.exe",
          shortcutAllowed: false,
          publicProductEntry: false
        }),
        expect.objectContaining({ path: "scripts/vibelution_launcher.ps1", publicProductEntry: false }),
        expect.objectContaining({ path: "scripts/vibelution_launcher.py", publicProductEntry: false })
      ])
    );
    expect(catalog.fallbackProviders).toEqual(
      expect.arrayContaining([expect.objectContaining({ provider: "edge_app", publicProductEntry: false })])
    );
    expect(catalog.forbiddenProductEntries).toEqual(
      expect.arrayContaining([expect.objectContaining({ id: "direct-workbench-shortcut", target: "workbench" })])
    );
  });

  it("keeps only launcher focus as a public deep link in version 1", () => {
    const catalog = readCatalog();

    expect(catalog.deepLinks).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ route: "vibelution://launcher/focus", publicProductEntry: true }),
        expect.objectContaining({ route: "vibelution://workbench/open", publicProductEntry: false })
      ])
    );
  });

  it("exposes a shared PowerShell bridge for verifier scripts", () => {
    const script = readFileSync(helperScriptPath, "utf8");

    expect(script).toContain("function Read-DesktopEntryCatalog");
    expect(script).toContain("function Assert-DesktopEntryCatalog");
    expect(script).toContain("function Resolve-DesktopPublicEntryPath");
    expect(script).toContain('GetFolderPath("LocalApplicationData")');
    expect(script).toContain("function Resolve-DesktopPublicEntryArguments");
    expect(script).toContain("function Resolve-DesktopPackageEntryPath");
    expect(script).toContain("desktop-entry-catalog.json");
  });
});
