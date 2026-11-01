import { mkdirSync, mkdtempSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { runDesktopPackageBuild } from "../scripts/buildDesktopPackage.js";
import { buildWorkbenchJob, resolveNativeBuildEnvironment } from "../scripts/buildWorkbenchJob.js";

const temporaryRoots: string[] = [];
const ownerEnvironmentKeys = [
  "VIBELUTION_DESKTOP_BUILD_MANAGED",
  "VIBELUTION_DESKTOP_BUILD_ROOT",
  "VIBELUTION_ELECTRON_DIST",
  "VIBELUTION_WORKBENCH_JOB_BUILD_ROOT"
];

function createFixture() {
  const root = mkdtempSync(join(tmpdir(), "vibelution-build-owner-export-"));
  temporaryRoots.push(root);
  return root;
}

function withBuildOwnerEnvironment(values: Record<string, string>, run: () => void) {
  const previous = new Map(ownerEnvironmentKeys.map((key) => [key, process.env[key]]));
  for (const key of ownerEnvironmentKeys) {
    const value = values[key];
    if (value === undefined) {
      delete process.env[key];
    } else {
      process.env[key] = value;
    }
  }
  try {
    run();
  } finally {
    for (const [key, value] of previous) {
      if (value === undefined) {
        delete process.env[key];
      } else {
        process.env[key] = value;
      }
    }
  }
}

function withoutBuildOwnerEnvironment(run: () => void) {
  withBuildOwnerEnvironment({}, run);
}

afterEach(() => {
  for (const root of temporaryRoots.splice(0)) {
    rmSync(root, { recursive: true, force: true });
  }
});

describe("native build Visual Studio discovery", () => {
  const programFiles = "C:\\Program Files (x86)";
  const installationPath = "D:\\开发工具\\VS Build Tools";
  const instance = {
    installationPath,
    installationVersion: "17.14.37824.6",
    packages: [{ id: "Microsoft.VisualStudio.Component.Windows11SDK.26100" }]
  };

  it("passes discovered tools and SDK only to the hidden native child", () => {
    const root = createFixture();
    const electronRoot = resolve(root, "desktop/electron");
    const sourceRoot = join(electronRoot, "native/workbench-job");
    const session = resolve(root, "dist/.desktop-shell-build-owned");
    const outputRoot = join(session, "output");
    const nativeBuildRoot = join(session, "native-workbench-job");
    mkdirSync(sourceRoot, { recursive: true });
    mkdirSync(outputRoot, { recursive: true });
    writeFileSync(join(sourceRoot, "binding.gyp"), "{}");
    const env = { "ProgramFiles(x86)": programFiles, PATH: "original" };
    const run = vi.fn((command: string, _args: string[], options: any) => {
      if (command.endsWith("vswhere.exe")) return { status: 0, stdout: JSON.stringify([instance]) };
      mkdirSync(join(options.cwd, "build/Release"), { recursive: true });
      writeFileSync(join(options.cwd, "build/Release/workbench_job.node"), "native");
      return { status: 0 };
    });
    withBuildOwnerEnvironment({
      VIBELUTION_DESKTOP_BUILD_MANAGED: "1",
      VIBELUTION_DESKTOP_BUILD_ROOT: session,
      VIBELUTION_ELECTRON_DIST: outputRoot,
      VIBELUTION_WORKBENCH_JOB_BUILD_ROOT: nativeBuildRoot
    }, () => {
      expect(buildWorkbenchJob({ electronRoot, platform: "win32", env, run, exists: () => true }))
        .toBe(join(outputRoot, "native/workbench_job.node"));
    });
    expect(run).toHaveBeenCalledTimes(2);
    expect(run.mock.calls[0][2]).toMatchObject({ encoding: "utf8", shell: false, windowsHide: true });
    expect(run.mock.calls[1][2]).toMatchObject({
      shell: false, windowsHide: true,
      env: { ...env, VCINSTALLDIR: join(installationPath, "VC"), VSCMD_VER: instance.installationVersion, WindowsSDKVersion: "10.0.26100.0" }
    });
    expect(env).toEqual({ "ProgramFiles(x86)": programFiles, PATH: "original" });
  });

  it.each([
    { vcinstalldir: "existing" },
    { VSCMD_VER: "17.0" },
    { npm_config_msvs_version: "2022" }
  ])("preserves explicit developer configuration %o", (settings) => {
    const env = { "ProgramFiles(x86)": programFiles, ...settings };
    const run = vi.fn();
    expect(resolveNativeBuildEnvironment({ env, run, exists: () => true })).toBe(env);
    expect(run).not.toHaveBeenCalled();
  });

  it("preserves an explicitly selected SDK and skips unusable installations", () => {
    const env = { "ProgramFiles(x86)": programFiles, WindowsSDKVersion: "10.0.19041.0\\" };
    const run = vi.fn(() => ({ status: 0, stdout: JSON.stringify([
      { ...instance, installationPath: "D:\\incomplete" }, instance
    ]) }));
    const result = resolveNativeBuildEnvironment({ env, run, exists: (path: string) => !path.includes("incomplete") });
    expect(result).toMatchObject({ VCINSTALLDIR: join(installationPath, "VC"), WindowsSDKVersion: env.WindowsSDKVersion });
  });

  it.each([
    { status: 1, stdout: "" },
    { status: 0, stdout: "invalid json" },
    { status: 0, stdout: JSON.stringify([{ ...instance, packages: [] }]) }
  ])("falls back to node-gyp discovery on unusable vswhere output %#", (result) => {
    const env = { "ProgramFiles(x86)": programFiles };
    expect(resolveNativeBuildEnvironment({ env, run: () => result, exists: () => true })).toBe(env);
  });
});

describe("build owner exported APIs", () => {
  it("rejects a directly imported package build before creating output paths", () => {
    const root = createFixture();
    const before = readdirSync(root);

    withoutBuildOwnerEnvironment(() => {
      expect(() => runDesktopPackageBuild({
        workspaceRoot: root,
        electronRoot: resolve(root, "desktop/electron")
      })).toThrow("managed Python build owner");
    });

    expect(readdirSync(root)).toEqual(before);
  });

  it("rejects a directly imported native build before creating output paths", () => {
    const root = createFixture();
    const before = readdirSync(root);

    withoutBuildOwnerEnvironment(() => {
      expect(() => buildWorkbenchJob({
        electronRoot: resolve(root, "desktop/electron"),
        platform: "win32",
        outputRoot: resolve(root, "dist/desktop"),
        nativeBuildRoot: resolve(root, "native-build")
      })).toThrow("managed Python build owner");
    });

    expect(readdirSync(root)).toEqual(before);
  });

  it("rejects a package session override that targets a shared output", () => {
    const root = createFixture();
    const session = resolve(root, "dist/.desktop-shell-build-owned");
    const before = readdirSync(root);

    withBuildOwnerEnvironment({
      VIBELUTION_DESKTOP_BUILD_MANAGED: "1",
      VIBELUTION_DESKTOP_BUILD_ROOT: session
    }, () => {
      expect(() => runDesktopPackageBuild({
        workspaceRoot: root,
        electronRoot: resolve(root, "desktop/electron"),
        buildRoot: resolve(root, "dist/desktop")
      })).toThrow("does not match the owner-provided path");
    });

    expect(readdirSync(root)).toEqual(before);
  });

  it("rejects native output redirected outside the owner session", () => {
    const root = createFixture();
    const ownedSession = resolve(root, "dist/.desktop-shell-build-owned");
    mkdirSync(ownedSession, { recursive: true });
    const before = readdirSync(root);

    withBuildOwnerEnvironment({
      VIBELUTION_DESKTOP_BUILD_MANAGED: "1",
      VIBELUTION_DESKTOP_BUILD_ROOT: ownedSession,
      VIBELUTION_ELECTRON_DIST: resolve(root, "dist/desktop"),
      VIBELUTION_WORKBENCH_JOB_BUILD_ROOT: resolve(ownedSession, "native-workbench-job")
    }, () => {
      expect(() => buildWorkbenchJob({
        electronRoot: resolve(root, "desktop/electron"),
        platform: "win32"
      })).toThrow("stay inside the owner session");
    });

    expect(readdirSync(root)).toEqual(before);
  });
});
