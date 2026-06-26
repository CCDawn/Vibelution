import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { parseDesktopCliArgs } from "../src/cli/desktopCli.js";
import { resolveDesktopLaunchSettings } from "../src/launch/desktopLaunchSettings.js";
import { runWriteLaunchProfileCli } from "../src/scripts/writeLaunchProfile.js";

const tempRoots: string[] = [];

afterEach(() => {
  for (const root of tempRoots.splice(0)) {
    rmSync(root, { recursive: true, force: true });
  }
});

function tempRoot(): string {
  const root = mkdtempSync(join(tmpdir(), "vibelution-launch-profile-"));
  tempRoots.push(root);
  return root;
}

describe("desktop launch profile writer CLI", () => {
  it("writes a no-BOM package profile that the runtime resolver can read", () => {
    const resourcesRoot = tempRoot();
    const userDataRoot = tempRoot();

    const profilePath = runWriteLaunchProfileCli([
      "--resources-root",
      resourcesRoot,
      "--workspace-root",
      "C:/Users/17533/Desktop/Vibelution",
      "--operator-config",
      "C:/Users/17533/Documents/Vibelution/config/config.toml",
      "--python-path",
      "C:/Users/17533/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe"
    ]);

    const bytes = readFileSync(profilePath);
    expect(bytes[0]).toBe(0x7b);
    expect(bytes.toString("utf8")).toContain("\"schemaVersion\": 1");

    const settings = resolveDesktopLaunchSettings({
      env: {},
      cliArgs: parseDesktopCliArgs([]),
      userDataRoot,
      resourcesRoot
    });

    expect(settings).toMatchObject({
      workspaceRoot: "C:/Users/17533/Desktop/Vibelution",
      configPath: "C:/Users/17533/Documents/Vibelution/config/config.toml",
      pythonPath: "C:/Users/17533/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe",
      profilePath,
      profileError: ""
    });
  });

  it("fails fast when the packaging script omits a required source value", () => {
    expect(() =>
      runWriteLaunchProfileCli([
        "--resources-root",
        "C:/package/resources",
        "--workspace-root",
        "C:/Users/17533/Desktop/Vibelution",
        "--python-path",
        "C:/Python/python.exe"
      ])
    ).toThrow("Missing required launch profile argument: --operator-config");
  });
});
