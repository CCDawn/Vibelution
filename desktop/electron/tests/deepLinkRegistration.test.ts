import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  buildDeepLinkRegistrationPlan,
  registerDeepLinkProtocolIfAllowed,
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

  it("does not touch OS protocol registration during development", () => {
    const calls: unknown[] = [];
    const result = registerDeepLinkProtocolIfAllowed(
      buildDeepLinkRegistrationPlan(readCatalog(), {
        platform: "win32",
        executablePath: "C:/Users/17533/Desktop/Vibelution/dist/desktop/win-unpacked/Vibelution.exe"
      }),
      {
        app: {
          isPackaged: false,
          setAsDefaultProtocolClient: (...args) => {
            calls.push(args);
            return true;
          }
        },
        env: {},
        platform: "win32",
        smoke: false
      }
    );

    expect(result).toMatchObject({
      attempted: false,
      registered: false,
      reason: "development_registration_disabled"
    });
    expect(calls).toEqual([]);
  });

  it("does not touch OS protocol registration during package smoke verification", () => {
    const calls: unknown[] = [];
    const result = registerDeepLinkProtocolIfAllowed(
      buildDeepLinkRegistrationPlan(readCatalog(), {
        platform: "win32",
        executablePath: "C:/Users/17533/Desktop/Vibelution/dist/desktop/win-unpacked/Vibelution.exe"
      }),
      {
        app: {
          isPackaged: true,
          setAsDefaultProtocolClient: (...args) => {
            calls.push(args);
            return true;
          }
        },
        env: {},
        platform: "win32",
        smoke: true
      }
    );

    expect(result).toMatchObject({
      attempted: false,
      registered: false,
      reason: "smoke_registration_disabled"
    });
    expect(calls).toEqual([]);
  });

  it("lets operators disable packaged protocol registration through env", () => {
    const calls: unknown[] = [];
    const result = registerDeepLinkProtocolIfAllowed(
      buildDeepLinkRegistrationPlan(readCatalog(), {
        platform: "win32",
        executablePath: "C:/Users/17533/Desktop/Vibelution/dist/desktop/win-unpacked/Vibelution.exe"
      }),
      {
        app: {
          isPackaged: true,
          setAsDefaultProtocolClient: (...args) => {
            calls.push(args);
            return true;
          }
        },
        env: { VIBELUTION_ELECTRON_REGISTER_DEEP_LINKS: "0" },
        platform: "win32",
        smoke: false
      }
    );

    expect(result).toMatchObject({
      attempted: false,
      registered: false,
      reason: "disabled_by_env"
    });
    expect(calls).toEqual([]);
  });

  it("registers the catalog-approved protocol only for packaged Windows startup", () => {
    const calls: unknown[] = [];
    const executablePath = "C:/Users/17533/Desktop/Vibelution/dist/desktop/win-unpacked/Vibelution.exe";
    const result = registerDeepLinkProtocolIfAllowed(
      buildDeepLinkRegistrationPlan(readCatalog(), {
        platform: "win32",
        executablePath
      }),
      {
        app: {
          isPackaged: true,
          setAsDefaultProtocolClient: (...args) => {
            calls.push(args);
            return true;
          }
        },
        env: {},
        platform: "win32",
        smoke: false
      }
    );

    expect(result).toMatchObject({
      attempted: true,
      registered: true,
      reason: ""
    });
    expect(calls).toEqual([["vibelution", executablePath, []]]);
  });

  it("reports Electron protocol registration failures without throwing", () => {
    const result = registerDeepLinkProtocolIfAllowed(
      buildDeepLinkRegistrationPlan(readCatalog(), {
        platform: "win32",
        executablePath: "C:/Users/17533/Desktop/Vibelution/dist/desktop/win-unpacked/Vibelution.exe"
      }),
      {
        app: {
          isPackaged: true,
          setAsDefaultProtocolClient: () => false
        },
        env: {},
        platform: "win32",
        smoke: false
      }
    );

    expect(result).toMatchObject({
      attempted: true,
      registered: false,
      reason: "electron_registration_failed"
    });
  });
});
