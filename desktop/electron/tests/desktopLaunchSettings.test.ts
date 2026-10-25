import { join } from "node:path";
import { describe, expect, it, vi } from "vitest";
import { parseDesktopCliArgs } from "../src/cli/desktopCli.js";
import {
  DESKTOP_LAUNCH_PROFILE_FILE,
  applyDesktopLaunchSettingsToEnvironment,
  resolveDesktopLaunchSettings,
  resolveDeferredProjectLaunchSettings
} from "../src/launch/desktopLaunchSettings.js";
import { createDesktopLaunchProfile, serializeDesktopLaunchProfile } from "../src/launch/desktopLaunchProfileWriter.js";

describe("deferred project launch binding", () => {
  it("uses the target project's Python instead of inherited assistant bindings", () => {
    const env = { VIBELUTION_WORKSPACE_ROOT: "old-project", VIBELUTION_PYTHON_PATH: "embedded-python", PYTHON: "other-python" };
    const ownPython = join("target-project", ".venv", "Scripts", "python.exe");
    const input = { env, cliArgs: parseDesktopCliArgs(["--assistant"]), userDataRoot: "private", resourcesRoot: "resources",
      readTextFile: () => JSON.stringify({ schemaVersion: 1, workspaceRoot: "profile-project", pythonPath: "shared-project-python" }),
      fileExists: (path: string) => path === ownPython };
    const result = resolveDeferredProjectLaunchSettings(input, "target-project", "private-config");
    expect(result.assistant).not.toBe(true);
    expect(result.workspaceRoot).toBe("target-project"); expect(result.pythonPath).toBe(ownPython);
    expect(result.configPath).toBe("private-config");
    expect(env.PYTHON).toBe("other-python"); expect(env.VIBELUTION_WORKSPACE_ROOT).toBe("old-project");
  });

  it("keeps the installed profile's explicit shared Python fallback without a local venv", () => {
    const result = resolveDeferredProjectLaunchSettings({
      env: { PYTHON: "embedded-python" }, cliArgs: parseDesktopCliArgs(["--assistant"]), userDataRoot: "private", resourcesRoot: "resources",
      readTextFile: () => JSON.stringify({ schemaVersion: 1, workspaceRoot: "profile-project", pythonPath: "shared-project-python" }),
      fileExists: () => false,
    }, "", "private-config");
    expect(result.workspaceRoot).toBe("profile-project"); expect(result.pythonPath).toBe("shared-project-python");
  });
});

function resolveWithFiles(input: {
  env?: NodeJS.ProcessEnv;
  argv?: string[];
  userDataRoot?: string;
  resourcesRoot?: string;
  files?: Record<string, string>;
  existingFiles?: string[];
}) {
  const userDataRoot = input.userDataRoot ?? "C:/Users/17533/AppData/Roaming/Vibelution";
  const resourcesRoot = input.resourcesRoot ?? "C:/Users/17533/Desktop/Vibelution/dist/desktop/win-unpacked/resources";
  const files = new Map(Object.entries(input.files ?? {}));
  const existing = new Set((input.existingFiles ?? []).map((path) => path.replace(/\\/g, "/")));
  return resolveDesktopLaunchSettings({
    env: input.env ?? {},
    cliArgs: parseDesktopCliArgs(input.argv ?? []),
    userDataRoot,
    resourcesRoot,
    readTextFile: (path) => files.get(path) ?? null,
    fileExists: (path) => existing.has(path.replace(/\\/g, "/"))
  });
}

describe("desktop launch settings", () => {
  it("removes inherited project bindings case-insensitively while preserving operator config", () => {
    const inherited = { vibelution_workspace_root: "C:/old/checkout", Vibelution_Python_Path: "C:/old/python.exe",
      Python: "C:/old/other-python.exe", pythonpath: "C:/old/modules", PyThOnHoMe: "C:/old/runtime",
      VIBELUTION_CONFIG_PATH: "C:/operator/config.toml", KEEP: "unchanged" };
    const settings = resolveWithFiles({ argv: ["--assistant"], env: inherited });
    const environment = applyDesktopLaunchSettingsToEnvironment(inherited, settings);
    expect(environment).toEqual({ VIBELUTION_CONFIG_PATH: "C:/operator/config.toml", KEEP: "unchanged" });
    expect(inherited.Python).toBe("C:/old/other-python.exe");
    const ordinary = resolveWithFiles({ env: inherited });
    expect(applyDesktopLaunchSettingsToEnvironment(inherited, ordinary)).toEqual(inherited);
  });

  it.each(["user", "resources"])("ignores %s project bindings in assistant mode without probing checkout Python", location => {
    const userDataRoot = "C:/private/user";
    const resourcesRoot = "C:/package/resources";
    const profilePath = join(location === "user" ? userDataRoot : resourcesRoot, DESKTOP_LAUNCH_PROFILE_FILE);
    const profile = JSON.stringify({ schemaVersion: 1, workspaceRoot: "C:/old/project",
      pythonPath: "C:/old/project/.venv/python.exe", operatorConfigPath: "C:/operator/config.toml" });
    const readTextFile = vi.fn((path: string) => path === profilePath ? profile : null);
    const fileExists = vi.fn(() => { throw new Error("checkout Python must not be probed"); });
    const inherited = { VIBELUTION_WORKSPACE_ROOT: "C:/inherited/project", VIBELUTION_PYTHON_PATH: "C:/old/python.exe",
      PYTHON: "C:/other/python.exe", PYTHONPATH: "C:/old/modules", PYTHONHOME: "C:/old/runtime", KEEP: "value" };
    const settings = resolveDesktopLaunchSettings({ env: inherited, cliArgs: parseDesktopCliArgs(["--assistant"]),
      userDataRoot, resourcesRoot, readTextFile, fileExists });
    expect(settings).toMatchObject({ assistant: true, workspaceRoot: "", pythonPath: "", configPath: "C:/operator/config.toml" });
    expect(fileExists).not.toHaveBeenCalled();
    const environment = applyDesktopLaunchSettingsToEnvironment(inherited, settings);
    for (const name of ["VIBELUTION_WORKSPACE_ROOT", "VIBELUTION_PYTHON_PATH", "PYTHON", "PYTHONPATH", "PYTHONHOME"]) {
      expect(environment).not.toHaveProperty(name);
    }
    expect(environment).toMatchObject({ VIBELUTION_CONFIG_PATH: "C:/operator/config.toml", KEEP: "value" });
    expect(JSON.parse(profile).workspaceRoot).toBe("C:/old/project");
    expect(inherited.VIBELUTION_WORKSPACE_ROOT).toBe("C:/inherited/project");
  });

  it("loads a package launch profile as the default Electron entry context", () => {
    const resourcesRoot = "C:/Users/17533/Desktop/Vibelution/dist/desktop/win-unpacked/resources";
    const profilePath = join(resourcesRoot, DESKTOP_LAUNCH_PROFILE_FILE);

    const settings = resolveWithFiles({
      resourcesRoot,
      files: {
        [profilePath]: JSON.stringify({
          schemaVersion: 1,
          workspaceRoot: "C:/Users/17533/Desktop/Vibelution",
          operatorConfigPath: "C:/Users/17533/Documents/Vibelution/config/config.toml",
          pythonPath: "C:/Users/17533/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe"
        })
      }
    });

    expect(settings).toMatchObject({
      workspaceRoot: "C:/Users/17533/Desktop/Vibelution",
      configPath: "C:/Users/17533/Documents/Vibelution/config/config.toml",
      pythonPath: "C:/Users/17533/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe",
      profilePath,
      profileError: ""
    });
  });

  it("keeps CLI and environment values stronger than a package profile", () => {
    const resourcesRoot = "C:/package/resources";
    const profilePath = join(resourcesRoot, DESKTOP_LAUNCH_PROFILE_FILE);

    const settings = resolveWithFiles({
      argv: ["--workspace", "D:/FromCli/Vibelution", "--config", "D:/FromCli/config.toml"],
      env: { VIBELUTION_PYTHON_PATH: "D:/FromEnv/python.exe" },
      resourcesRoot,
      files: {
        [profilePath]: JSON.stringify({
          schemaVersion: 1,
          workspaceRoot: "D:/FromProfile/Vibelution",
          operatorConfigPath: "D:/FromProfile/config.toml",
          pythonPath: "D:/FromProfile/python.exe"
        })
      }
    });

    expect(settings.workspaceRoot).toBe("D:/FromCli/Vibelution");
    expect(settings.configPath).toBe("D:/FromCli/config.toml");
    expect(settings.pythonPath).toBe("D:/FromEnv/python.exe");

    expect(applyDesktopLaunchSettingsToEnvironment({ NODE_ENV: "production" }, settings)).toMatchObject({
      NODE_ENV: "production",
      VIBELUTION_WORKSPACE_ROOT: "D:/FromCli/Vibelution",
      VIBELUTION_CONFIG_PATH: "D:/FromCli/config.toml",
      VIBELUTION_PYTHON_PATH: "D:/FromEnv/python.exe"
    });
  });

  it("ignores malformed or non-string profile fields without leaking profile contents", () => {
    const userDataRoot = "C:/Users/17533/AppData/Roaming/Vibelution";
    const resourcesRoot = "C:/package/resources";
    const userProfilePath = join(userDataRoot, DESKTOP_LAUNCH_PROFILE_FILE);
    const resourceProfilePath = join(resourcesRoot, DESKTOP_LAUNCH_PROFILE_FILE);

    const settings = resolveWithFiles({
      userDataRoot,
      resourcesRoot,
      files: {
        [userProfilePath]: "{not-json",
        [resourceProfilePath]: JSON.stringify({
          schemaVersion: 1,
          workspaceRoot: 123,
          operatorConfigPath: ["secret-config-path"],
          pythonPath: null
        })
      }
    });

    expect(settings.workspaceRoot).toBe("");
    expect(settings.configPath).toBe("");
    expect(settings.pythonPath).toBe("");
    expect(settings.profilePath).toBe(resourceProfilePath);
    expect(settings.profileError).toBe("invalid_launch_profile_json");
    expect(settings.profileError).not.toContain("secret-config-path");
  });

  it("accepts UTF-8 BOM launch profiles generated by Windows packaging scripts", () => {
    const resourcesRoot = "C:/package/resources";
    const profilePath = join(resourcesRoot, DESKTOP_LAUNCH_PROFILE_FILE);

    const settings = resolveWithFiles({
      resourcesRoot,
      files: {
        [profilePath]: `\uFEFF${JSON.stringify({
          schemaVersion: 1,
          workspaceRoot: "C:/Users/17533/Desktop/Vibelution",
          operatorConfigPath: "C:/Users/17533/Documents/Vibelution/config/config.toml",
          pythonPath: "C:/Python/python.exe"
        })}`
      }
    });

    expect(settings.workspaceRoot).toBe("C:/Users/17533/Desktop/Vibelution");
    expect(settings.configPath).toBe("C:/Users/17533/Documents/Vibelution/config/config.toml");
    expect(settings.pythonPath).toBe("C:/Python/python.exe");
    expect(settings.profileError).toBe("");
  });

  it("recovers operatorConfigPath from a leftover profile configPath once without writing it back", () => {
    const resourcesRoot = "C:/package/resources";
    const profilePath = join(resourcesRoot, DESKTOP_LAUNCH_PROFILE_FILE);

    const settings = resolveWithFiles({
      resourcesRoot,
      files: {
        [profilePath]: JSON.stringify({
          schemaVersion: 1,
          workspaceRoot: "C:/Users/17533/Desktop/Vibelution",
          configPath: "C:/Users/17533/Documents/Vibelution/config/config.toml",
          pythonPath: "C:/Python/python.exe"
        })
      }
    });

    expect(settings.configPath).toBe("C:/Users/17533/Documents/Vibelution/config/config.toml");
    expect(
      createDesktopLaunchProfile({
        workspaceRoot: settings.workspaceRoot,
        operatorConfigPath: settings.configPath,
        pythonPath: settings.pythonPath
      })
    ).not.toHaveProperty("configPath");
  });

  it("round-trips generated package launch profiles through the runtime resolver", () => {
    const resourcesRoot = "C:/Users/17533/Desktop/Vibelution/dist/desktop/win-unpacked/resources";
    const profilePath = join(resourcesRoot, DESKTOP_LAUNCH_PROFILE_FILE);
    const profile = createDesktopLaunchProfile({
      workspaceRoot: "C:/Users/17533/Desktop/Vibelution",
      operatorConfigPath: "C:/Users/17533/Documents/Vibelution/config/config.toml",
      pythonPath: "C:/Users/17533/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe"
    });
    const serialized = serializeDesktopLaunchProfile(profile);

    expect(serialized.charCodeAt(0)).not.toBe(0xfeff);
    expect(JSON.parse(serialized)).toEqual({
      schemaVersion: 1,
      workspaceRoot: "C:/Users/17533/Desktop/Vibelution",
      operatorConfigPath: "C:/Users/17533/Documents/Vibelution/config/config.toml",
      pythonPath: "C:/Users/17533/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe"
    });
    expect(JSON.parse(serialized)).not.toHaveProperty("configPath");

    const settings = resolveWithFiles({
      resourcesRoot,
      files: {
        [profilePath]: serialized
      }
    });

    expect(settings.workspaceRoot).toBe(profile.workspaceRoot);
    expect(settings.configPath).toBe(profile.operatorConfigPath);
    expect(settings.pythonPath).toBe(profile.pythonPath);
    expect(settings.profileError).toBe("");
  });

  it("falls back to the workspace venv interpreter when no env or profile python is set", () => {
    const workspaceRoot = "C:/Users/17533/Desktop/Vibelution";
    const venvPython = join(workspaceRoot, ".venv", "Scripts", "python.exe");

    const settings = resolveWithFiles({
      argv: ["--workspace", workspaceRoot],
      existingFiles: [venvPython]
    });

    expect(settings.pythonPath.replace(/\\/g, "/")).toBe(venvPython.replace(/\\/g, "/"));
  });
});
