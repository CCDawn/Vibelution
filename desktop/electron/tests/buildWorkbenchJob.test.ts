import { cpSync, existsSync, mkdirSync, mkdtempSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  buildWorkbenchJob,
  findNodeImportLibrary,
  nodeHeadersAreStaged,
  resolveLocalNodeHeaders,
  stageNodeHeaders
} from "../scripts/buildWorkbenchJob.js";

const directories: string[] = [];

function tempDirectory(): string {
  const directory = mkdtempSync(join(tmpdir(), "vibelution-native-build-"));
  directories.push(directory);
  return directory;
}

afterEach(() => {
  for (const directory of directories.splice(0)) {
    rmSync(directory, { recursive: true, force: true });
  }
  vi.unstubAllEnvs();
});

function writeHeaders(cacheRoot: string, version: string): string {
  const directory = join(cacheRoot, version);
  mkdirSync(join(directory, "include", "node"), { recursive: true });
  writeFileSync(join(directory, "include", "node", "node_api.h"), "// headers\n");
  mkdirSync(join(directory, "x64"), { recursive: true });
  writeFileSync(join(directory, "x64", "node.lib"), "import library\n");
  return directory;
}

/** A node-gyp cache root plus the LOCALAPPDATA that points node-gyp at it. */
function cacheFixture(): { localAppData: string; cacheRoot: string } {
  const localAppData = tempDirectory();
  return { localAppData, cacheRoot: join(localAppData, "node-gyp", "Cache") };
}

describe("cached node headers", () => {
  it("uses the newest cached headers of the running major version", () => {
    const { localAppData, cacheRoot } = cacheFixture();
    writeHeaders(cacheRoot, "24.15.0");
    writeHeaders(cacheRoot, "24.18.0");
    writeHeaders(cacheRoot, "22.22.2");

    const resolved = resolveLocalNodeHeaders({
      version: "24.18.0",
      env: { LOCALAPPDATA: localAppData },
      platform: "win32"
    });

    // A cache-miss on the exact patch release must still resolve offline: node
    // is a Node-API consumer here, so 24.x headers link a compatible addon.
    expect(resolved).toBe(join(cacheRoot, "24.18.0"));
  });

  it("ignores cached headers from another major version", () => {
    const { localAppData, cacheRoot } = cacheFixture();
    writeHeaders(cacheRoot, "22.22.2");

    expect(resolveLocalNodeHeaders({
      version: "24.18.0",
      env: { LOCALAPPDATA: localAppData },
      platform: "win32"
    })).toBe("");
  });

  it("skips cache entries without node headers", () => {
    const { localAppData, cacheRoot } = cacheFixture();
    mkdirSync(join(cacheRoot, "24.20.0"), { recursive: true });
    const complete = writeHeaders(cacheRoot, "24.15.0");

    expect(resolveLocalNodeHeaders({
      version: "24.20.0",
      env: { LOCALAPPDATA: localAppData },
      platform: "win32"
    })).toBe(complete);
  });

  it("returns nothing when the cache root does not exist", () => {
    expect(resolveLocalNodeHeaders({
      version: "24.18.0",
      env: { LOCALAPPDATA: join(tempDirectory(), "missing") },
      platform: "win32"
    })).toBe("");
  });

  it("finds the import library under the architecture folder", () => {
    const source = writeHeaders(cacheFixture().cacheRoot, "24.15.0");
    expect(findNodeImportLibrary({ source, arch: "x64", platform: "win32" }))
      .toBe(join(source, "x64", "node.lib"));
  });

  it("stages headers into the layout the MSBuild link step expects", () => {
    const source = writeHeaders(cacheFixture().cacheRoot, "24.15.0");
    const destination = join(tempDirectory(), "node-headers");

    const staged = stageNodeHeaders({ source, destination, arch: "x64", platform: "win32" });

    expect(staged).toBe(destination);
    expect(existsSync(join(destination, "include", "node", "node_api.h"))).toBe(true);
    // node-gyp's addon.gypi links from <nodedir>/$(ConfigurationName)/node.lib,
    // while the cache keeps the import library under <nodedir>/<arch>.
    expect(existsSync(join(destination, "Release", "node.lib"))).toBe(true);
    expect(existsSync(join(destination, "x64", "node.lib"))).toBe(true);
    expect(readdirSync(source)).toContain("x64");
  });

  it("reuses an already staged header tree instead of copying it again", () => {
    const source = writeHeaders(cacheFixture().cacheRoot, "24.15.0");
    const destination = join(tempDirectory(), "node-headers");
    const copy = vi.fn((from: string, to: string, options: object) => cpSync(from, to, options));
    stageNodeHeaders({ source, destination, arch: "x64", platform: "win32", copy });

    const secondCopy = vi.fn();
    const staged = stageNodeHeaders({
      source, destination, arch: "x64", platform: "win32", copy: secondCopy
    });

    // Re-staging 63 MB of headers on every package would be pure waste.
    expect(staged).toBe(destination);
    expect(secondCopy).not.toHaveBeenCalled();
  });

  it("does not stage a directory it cannot link against", () => {
    const { cacheRoot } = cacheFixture();
    const source = join(cacheRoot, "24.15.0");
    mkdirSync(join(source, "include", "node"), { recursive: true });
    writeFileSync(join(source, "include", "node", "node_api.h"), "// headers\n");

    expect(stageNodeHeaders({ source, destination: join(tempDirectory(), "out"), platform: "win32" })).toBe("");
  });
});

describe("buildWorkbenchJob", () => {
  it("compiles against locally cached headers instead of downloading them", () => {
    const workspace = tempDirectory();
    const sessionRoot = join(workspace, "dist", ".desktop-shell-build-test");
    const outputRoot = join(sessionRoot, "builder-output");
    const buildRoot = join(sessionRoot, "native-build");
    const electronRoot = join(workspace, "desktop", "electron");
    mkdirSync(join(electronRoot, "native", "workbench-job"), { recursive: true });
    for (const name of ["binding.gyp", "job_object.c", "job_object_stub.c"]) {
      writeFileSync(join(electronRoot, "native", "workbench-job", name), "// source\n");
    }
    mkdirSync(outputRoot, { recursive: true });
    const cache = cacheFixture();
    const headers = writeHeaders(cache.cacheRoot, "24.15.0");

    vi.stubEnv("VIBELUTION_DESKTOP_BUILD_MANAGED", "1");
    vi.stubEnv("VIBELUTION_DESKTOP_BUILD_ROOT", sessionRoot);
    vi.stubEnv("VIBELUTION_ELECTRON_DIST", outputRoot);
    vi.stubEnv("VIBELUTION_WORKBENCH_JOB_BUILD_ROOT", buildRoot);
    vi.stubEnv("ProgramFiles(x86)", "");

    const run = vi.fn((_executable: string, _args: string[], options: { cwd: string }) => {
      mkdirSync(join(options.cwd, "build", "Release"), { recursive: true });
      writeFileSync(join(options.cwd, "build", "Release", "workbench_job.node"), "addon\n");
      return { status: 0 };
    });

    const stageRoot = join(tempDirectory(), "node-headers");
    const output = buildWorkbenchJob({
      electronRoot,
      platform: "win32",
      run,
      headersStageRoot: stageRoot,
      env: { ...process.env, LOCALAPPDATA: cache.localAppData }
    });

    expect(output).toBe(join(outputRoot, "native", "workbench_job.node"));
    expect(existsSync(output)).toBe(true);
    const [, nodeGypArgs] = run.mock.calls[0];
    const nodedir = nodeGypArgs.find((argument: string) => argument.startsWith("--nodedir="));
    expect(nodedir).toBe(`--nodedir=${join(stageRoot, "24.15.0")}`);
    // The staged copy survives the build so the next package reuses it instead
    // of copying 63 MB of headers again, and the shared cache is untouched.
    expect(nodeHeadersAreStaged({ destination: join(stageRoot, "24.15.0"), arch: "x64" })).toBe(true);
    expect(existsSync(join(headers, "x64", "node.lib"))).toBe(true);
  });
});
