import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

import { resolveDesktopShellOwnerPaths } from "../src/lifecycle/projectStoragePaths.js";
import {
  captureElectronOwnerIdentity,
  claimElectronDesktopShellOwner,
  desktopShellOwnerPath,
  releaseElectronDesktopShellOwner
} from "../src/tray/desktopShellOwner.js";

const previousProjectsHome = process.env.VIBELUTION_PROJECTS_HOME;

function seedWorkspace(): { root: string; projectsHome: string } {
  const root = mkdtempSync(join(tmpdir(), "vibelution-shell-owner-"));
  const projectsHome = join(root, "projects");
  mkdirSync(join(root, ".vibelution"), { recursive: true });
  writeFileSync(join(root, ".vibelution", "project.json"), JSON.stringify({ schemaVersion: 1, projectId: "test-vibelution" }), "utf8");
  process.env.VIBELUTION_PROJECTS_HOME = projectsHome;
  return { root, projectsHome };
}

describe("desktopShellOwner", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    if (previousProjectsHome === undefined) {
      delete process.env.VIBELUTION_PROJECTS_HOME;
    } else {
      process.env.VIBELUTION_PROJECTS_HOME = previousProjectsHome;
    }
  });

  it("uses native creation time even when Electron initialization exceeds the owner tolerance", () => {
    vi.stubGlobal("process", { ...process, getCreationTime: () => 100_000 });
    expect(captureElectronOwnerIdentity(process.pid, "electron.exe", 115, 10).createTime).toBe(100);
    expect(captureElectronOwnerIdentity(process.pid + 1, "other.exe", 115, 10).createTime).toBe(105);
  });

  it.each([null, NaN, Infinity, 0, -1, undefined])("retains the portable fallback for invalid native time %s", (value) => {
    vi.stubGlobal("process", { ...process, getCreationTime: value === undefined ? undefined : () => value });
    expect(captureElectronOwnerIdentity(process.pid, "electron.exe", 115, 10).createTime).toBe(105);
  });

  it("claims and releases only the canonical tray owner file", () => {
    const { root } = seedWorkspace();
    try {
      const record = claimElectronDesktopShellOwner(root, {
        pid: 4242,
        createTime: 100,
        executable: "C:/electron.exe"
      });
      expect(record?.owner).toBe("electron");
      expect(record?.pid).toBe(4242);
      expect(record?.updatedAt).toBeTruthy();
      const paths = resolveDesktopShellOwnerPaths(root);
      expect(paths.canonical).toBeTruthy();
      expect(desktopShellOwnerPath(root)).toBe(paths.canonical);
      const written = JSON.parse(readFileSync(paths.canonical!, "utf8")) as { pid: number; createTime: number };
      expect(written.pid).toBe(4242);
      expect(written.createTime).toBe(100);
      expect(existsSync(paths.checkout)).toBe(false);
      mkdirSync(dirname(paths.checkout), { recursive: true });
      writeFileSync(paths.checkout, JSON.stringify({ schemaVersion: 1, owner: "electron", pid: 37812 }), "utf8");
      claimElectronDesktopShellOwner(root, {
        pid: 4242,
        createTime: 100,
        executable: "C:/electron.exe"
      });
      expect(existsSync(paths.checkout)).toBe(false);
      releaseElectronDesktopShellOwner(root, { pid: 4242, createTime: 100, executable: "C:/electron.exe" });
      expect(existsSync(paths.canonical!)).toBe(false);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("does not release an owner that does not match the full identity", () => {
    const { root } = seedWorkspace();
    try {
      claimElectronDesktopShellOwner(root, {
        pid: 4242,
        createTime: 100,
        executable: "C:/electron.exe"
      });
      releaseElectronDesktopShellOwner(root, { pid: 4242, createTime: 99, executable: "C:/other.exe" });
      const paths = resolveDesktopShellOwnerPaths(root);
      expect(existsSync(paths.canonical!)).toBe(true);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
});
