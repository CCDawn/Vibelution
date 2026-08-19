import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";

import { resolveDesktopShellOwnerPaths } from "../src/lifecycle/projectStoragePaths.js";
import {
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
    if (previousProjectsHome === undefined) {
      delete process.env.VIBELUTION_PROJECTS_HOME;
    } else {
      process.env.VIBELUTION_PROJECTS_HOME = previousProjectsHome;
    }
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
