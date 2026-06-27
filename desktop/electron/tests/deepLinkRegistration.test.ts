import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  buildDeepLinkRegistrationPlan,
  type DesktopEntryCatalog
} from "../src/protocol/deepLinkRegistration.js";

const catalogPath = fileURLToPath(new URL("../desktop-entry-catalog.json", import.meta.url));

function readCatalog(overrides: Partial<DesktopEntryCatalog> = {}): DesktopEntryCatalog {
  const catalog = JSON.parse(readFileSync(catalogPath, "utf8")) as DesktopEntryCatalog;
  return { ...catalog, ...overrides };
}

describe("deep-link registration policy", () => {
  it("builds a catalog-driven registration plan for only the public Launcher focus route", () => {
    const plan = buildDeepLinkRegistrationPlan(readCatalog(), {
      platform: "win32",
      executablePath: "C:/Users/17533/Desktop/Vibelution/dist/desktop/win-unpacked/Vibelution.exe"
    });

    expect(plan).toEqual({
      schemaVersion: 1,
      protocol: "vibelution",
      enabled: true,
      executablePath: "C:/Users/17533/Desktop/Vibelution/dist/desktop/win-unpacked/Vibelution.exe",
      publicEntryId: "vibelution-desktop-package",
      publicRoutes: ["vibelution://launcher/focus"],
      rejectedRoutes: ["vibelution://workbench/open"],
      reason: ""
    });
  });

  it("does not expose Workbench as a public deep-link entry", () => {
    const catalog = readCatalog({
      deepLinks: [
        { route: "vibelution://launcher/focus", action: "focus_launcher", publicProductEntry: true },
        { route: "vibelution://workbench/open", action: "open_workbench", publicProductEntry: true }
      ]
    });

    expect(() =>
      buildDeepLinkRegistrationPlan(catalog, {
        platform: "win32",
        executablePath: "C:/Users/17533/Desktop/Vibelution/dist/desktop/win-unpacked/Vibelution.exe"
      })
    ).toThrow("only launcher focus can be a public deep link");
  });

  it("requires exactly one shortcut-allowed public product entry", () => {
    const catalog = readCatalog({
      publicProductEntries: [
        ...readCatalog().publicProductEntries,
        {
          id: "extra-workbench-entry",
          label: "Workbench",
          path: "dist/desktop/win-unpacked/VibelutionWorkbench.exe",
          target: "workbench",
          windowProvider: "electron",
          shortcutAllowed: true,
          publicProductEntry: true
        }
      ]
    });

    expect(() =>
      buildDeepLinkRegistrationPlan(catalog, {
        platform: "win32",
        executablePath: "C:/Users/17533/Desktop/Vibelution/dist/desktop/win-unpacked/Vibelution.exe"
      })
    ).toThrow("exactly one shortcut-allowed public product entry");
  });

  it("keeps registration disabled when the packaged executable path is unavailable", () => {
    const plan = buildDeepLinkRegistrationPlan(readCatalog(), {
      platform: "linux",
      executablePath: ""
    });

    expect(plan).toMatchObject({
      protocol: "vibelution",
      enabled: false,
      publicRoutes: ["vibelution://launcher/focus"],
      rejectedRoutes: ["vibelution://workbench/open"],
      reason: "missing_executable_path"
    });
  });
});
