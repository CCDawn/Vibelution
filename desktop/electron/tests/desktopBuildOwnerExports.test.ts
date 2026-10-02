import { mkdirSync, mkdtempSync, readdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { runDesktopPackageBuild } from "../scripts/buildDesktopPackage.js";
import { buildWorkbenchJob } from "../scripts/buildWorkbenchJob.js";

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
