import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";

import { afterEach, describe, expect, it } from "vitest";

import {
  resolveCanonicalRuntimeHome,
  instanceIdForProject,
  resolveLauncherRuntimeDir,
  resolveRuntimeManagerDir,
} from "../src/lifecycle/projectStoragePaths.js";

const originalProjectsHome = process.env.VIBELUTION_PROJECTS_HOME;
const temporaryRoots: string[] = [];

afterEach(() => {
  if (originalProjectsHome === undefined) {
    delete process.env.VIBELUTION_PROJECTS_HOME;
  } else {
    process.env.VIBELUTION_PROJECTS_HOME = originalProjectsHome;
  }
  for (const root of temporaryRoots.splice(0)) {
    rmSync(root, { recursive: true, force: true });
  }
});

function createProjectFixture(): { projectRoot: string; projectId: string } {
  const root = mkdtempSync(join(tmpdir(), "vibelution-project-storage-"));
  temporaryRoots.push(root);
  const projectRoot = join(root, "project");
  const projectsHome = join(root, "projects");
  const projectId = "port-authority-test";
  mkdirSync(join(projectRoot, ".vibelution"), { recursive: true });
  writeFileSync(join(projectRoot, ".vibelution", "project.json"), JSON.stringify({ projectId }), "utf8");
  process.env.VIBELUTION_PROJECTS_HOME = projectsHome;
  return { projectRoot, projectId };
}

function writeMigrationMarker(projectRoot: string, projectId: string): string {
  const canonicalRuntime = resolveCanonicalRuntimeHome(projectRoot);
  if (!canonicalRuntime) {
    throw new Error("fixture did not resolve a canonical runtime path");
  }
  const markerPath = join(dirname(canonicalRuntime), "storage-migration.json");
  mkdirSync(dirname(markerPath), { recursive: true });
  writeFileSync(markerPath, JSON.stringify({
    schemaVersion: 1,
    status: "completed",
    projectId,
    instanceId: instanceIdForProject(projectRoot),
  }), "utf8");
  return canonicalRuntime;
}

describe("project storage runtime paths", () => {
  it("uses the canonical launcher and Runtime Manager directories after migration even before state.json exists", () => {
    const { projectRoot, projectId } = createProjectFixture();
    const canonicalRuntime = writeMigrationMarker(projectRoot, projectId);
    const checkoutLauncher = join(projectRoot, ".runtime", "launcher");
    const checkoutRuntimeManager = join(projectRoot, ".runtime", "runtime-manager");
    mkdirSync(checkoutLauncher, { recursive: true });
    mkdirSync(checkoutRuntimeManager, { recursive: true });
    writeFileSync(join(checkoutLauncher, "ports.json"), JSON.stringify({ backendPort: 8002 }), "utf8");
    writeFileSync(join(checkoutRuntimeManager, "state.json"), "{}", "utf8");

    expect(existsSync(join(canonicalRuntime, "launcher", "state.json"))).toBe(false);
    expect(resolveLauncherRuntimeDir(projectRoot)).toBe(join(canonicalRuntime, "launcher"));
    expect(resolveRuntimeManagerDir(projectRoot)).toBe(join(canonicalRuntime, "runtime-manager"));
  });

  it("keeps checkout runtime paths before a migration marker exists", () => {
    const { projectRoot } = createProjectFixture();
    const canonicalRuntime = resolveCanonicalRuntimeHome(projectRoot);
    if (!canonicalRuntime) {
      throw new Error("fixture did not resolve a canonical runtime path");
    }
    mkdirSync(join(canonicalRuntime, "launcher"), { recursive: true });
    mkdirSync(join(canonicalRuntime, "runtime-manager"), { recursive: true });
    writeFileSync(join(canonicalRuntime, "launcher", "state.json"), "{}", "utf8");
    writeFileSync(join(canonicalRuntime, "runtime-manager", "state.json"), "{}", "utf8");

    expect(resolveLauncherRuntimeDir(projectRoot)).toBe(join(projectRoot, ".runtime", "launcher"));
    expect(resolveRuntimeManagerDir(projectRoot)).toBe(join(projectRoot, ".runtime", "runtime-manager"));
  });

  it("fails closed when a present migration marker does not identify this instance", () => {
    const { projectRoot, projectId } = createProjectFixture();
    const canonicalRuntime = resolveCanonicalRuntimeHome(projectRoot);
    if (!canonicalRuntime) {
      throw new Error("fixture did not resolve a canonical runtime path");
    }
    const markerPath = join(dirname(canonicalRuntime), "storage-migration.json");
    mkdirSync(dirname(markerPath), { recursive: true });
    writeFileSync(markerPath, JSON.stringify({
      schemaVersion: 1,
      status: "completed",
      projectId,
      instanceId: "another-instance",
    }), "utf8");

    expect(() => resolveLauncherRuntimeDir(projectRoot)).toThrow("storage_migration_marker_invalid");
    expect(() => resolveRuntimeManagerDir(projectRoot)).toThrow("storage_migration_marker_invalid");
  });
});
