import { describe, expect, it } from "vitest";
import { applyDesktopCliToEnvironment, parseDesktopCliArgs } from "../src/cli/desktopCli.js";
import { desktopSmokeSummary, desktopSmokeSummaryPath } from "../src/smoke/desktopSmoke.js";

describe("desktop CLI arguments", () => {
  it("maps package smoke arguments onto the existing environment contract", () => {
    const args = parseDesktopCliArgs([
      "--workspace",
      "C:/Users/17533/Desktop/Vibelution",
      "--config",
      "C:/Users/17533/Documents/Vibelution/config/config.toml",
      "--smoke"
    ]);

    expect(args).toEqual({
      workspaceRoot: "C:/Users/17533/Desktop/Vibelution",
      configPath: "C:/Users/17533/Documents/Vibelution/config/config.toml",
      smoke: true
    });
    expect(applyDesktopCliToEnvironment({ NODE_ENV: "production" } as NodeJS.ProcessEnv, args)).toMatchObject({
      NODE_ENV: "production",
      VIBELUTION_WORKSPACE_ROOT: "C:/Users/17533/Desktop/Vibelution",
      VIBELUTION_CONFIG_PATH: "C:/Users/17533/Documents/Vibelution/config/config.toml",
      VIBELUTION_ELECTRON_SMOKE: "1"
    });
  });

  it("keeps smoke summaries redacted and workspace-bound", () => {
    expect(
      desktopSmokeSummary({
        workspaceRoot: "C:/Users/17533/Desktop/Vibelution",
        configPath: "C:/Users/17533/Documents/Vibelution/config/config.toml",
        launcherUrl: "http://127.0.0.1:8765/launcher",
        workbenchUrl: "http://127.0.0.1:8000/",
        controlToken: "secret-token",
        packaged: true
      })
    ).toEqual({
      schemaVersion: 1,
      mode: "electron_package_smoke",
      workspaceRoot: "C:/Users/17533/Desktop/Vibelution",
      operatorConfigPath: "C:/Users/17533/Documents/Vibelution/config/config.toml",
      packaged: true,
      launcherOrigin: "http://127.0.0.1:8765",
      workbenchOrigin: "http://127.0.0.1:8000",
      controlTokenPresent: true
    });
    expect(desktopSmokeSummaryPath("C:/Users/17533/Desktop/Vibelution").replaceAll("\\", "/")).toBe(
      "C:/Users/17533/Desktop/Vibelution/.runtime/launcher/electron-smoke-summary.json"
    );
  });
});
