import { describe, expect, it, vi } from "vitest";
import { inspectWorkbenchServingVersion } from "../src/process/servingVersion.js";

function healthPayload(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    status: "ok",
    routesReady: true,
    workspaceRoot: "C:/workspace",
    apiContractVersion: "v1",
    serving: {
      frontend: { buildKey: "build-current", release: "release-current" },
      backend: {
        pid: 4321,
        head: "head-current",
        dirtyTreeDigest: "dirty-current",
        createTime: 123.5,
        executable: "python.exe",
      },
    },
    ...overrides,
  };
}

function input(overrides: Record<string, unknown> = {}) {
  return {
    workspaceRoot: "C:/workspace",
    fetchHealth: async () => ({ status: 200, json: async () => healthPayload() }),
    readActive: () => ({ buildKey: "build-current", release: "release-current" }),
    currentCode: () => ({ head: "head-current", dirtyTreeDigest: "dirty-current" }),
    readState: () => ({
      backendPid: 4321,
      backendCreateTime: 123.5,
      backendExecutable: "python.exe"
    }),
    runIdentityBridge: async () => JSON.stringify({ matches: false }),
    ...overrides,
  };
}

describe("workbench serving-version handshake", () => {
  it("accepts the verified interpreter child of a Windows venv launcher", async () => {
    const runIdentityBridge = vi.fn(async () => JSON.stringify({ matches: true }));
    const result = await inspectWorkbenchServingVersion(input({
      readState: () => ({
        backendPid: 4000,
        backendCreateTime: 123.4,
        backendExecutable: "C:/workspace/.venv/Scripts/pythonw.exe"
      }),
      runIdentityBridge
    }));

    expect(result.ok).toBe(true);
    expect(result.backendPid).toBe(4321);
    expect(runIdentityBridge).toHaveBeenCalledWith(expect.objectContaining({
      pythonPath: "C:/workspace/.venv/Scripts/pythonw.exe",
      cwd: "C:/workspace",
      killPolicy: "child",
      args: ["-c", expect.stringContaining("inspect_process_identity"),
        JSON.stringify({ pid: 4000, createTime: 123.4, executable: "C:/workspace/.venv/Scripts/pythonw.exe" }),
        JSON.stringify({ pid: 4321, createTime: 123.5, executable: "python.exe" })]
    }));
  });

  it("still rejects stale frontend releases after verifying the interpreter child", async () => {
    const result = await inspectWorkbenchServingVersion(input({
      readState: () => ({ backendPid: 4000, backendCreateTime: 123.4, backendExecutable: "pythonw.exe" }),
      runIdentityBridge: async () => JSON.stringify({ matches: true }),
      readActive: () => ({ buildKey: "build-new", release: "release-new" })
    }));
    expect(result.reason).toBe("serving_release_mismatch");
  });

  it.each(["{}", "not-json"])("rejects an unverified child when the identity bridge returns %s", async (reply) => {
    const result = await inspectWorkbenchServingVersion(input({
      readState: () => ({ backendPid: 4000, backendCreateTime: 123.4, backendExecutable: "pythonw.exe" }),
      runIdentityBridge: async () => reply
    }));
    expect(result.reason).toBe("serving_backend_identity_mismatch");
  });

  it("rejects an inaccessible child identity", async () => {
    const result = await inspectWorkbenchServingVersion(input({
      readState: () => ({ backendPid: 4000, backendCreateTime: 123.4, backendExecutable: "pythonw.exe" }),
      runIdentityBridge: async () => { throw new Error("access denied"); }
    }));
    expect(result.reason).toBe("serving_backend_identity_mismatch");
  });

  it("does not treat a reused PID or incomplete launch identity as a child", async () => {
    const runIdentityBridge = vi.fn(async () => JSON.stringify({ matches: true }));
    for (const state of [
      { backendPid: 4321, backendCreateTime: 999, backendExecutable: "python.exe" },
      { backendPid: 4000, backendCreateTime: 0, backendExecutable: "pythonw.exe" }
    ]) {
      const result = await inspectWorkbenchServingVersion(input({ readState: () => state, runIdentityBridge }));
      expect(result.reason).toBe("serving_backend_identity_mismatch");
    }
    expect(runIdentityBridge).not.toHaveBeenCalled();
  });

  it("accepts a healthy backend whose release and code match disk", async () => {
    const result = await inspectWorkbenchServingVersion(input());

    expect(result.ok).toBe(true);
    expect(result.reason).toBe("serving_version_current");
    expect(result.release).toBe("release-current");
    expect(result.backendPid).toBe(4321);
  });

  it("rejects a backend serving an older active release", async () => {
    const result = await inspectWorkbenchServingVersion(
      input({
        readActive: () => ({ buildKey: "build-new", release: "release-new" }),
      }),
    );

    expect(result.ok).toBe(false);
    expect(result.reason).toBe("serving_release_mismatch");
  });

  it("rejects an incompatible API contract", async () => {
    const result = await inspectWorkbenchServingVersion(
      input({
        fetchHealth: async () => ({
          status: 200,
          json: async () => healthPayload({ apiContractVersion: "v0" }),
        }),
      }),
    );

    expect(result.ok).toBe(false);
    expect(result.reason).toBe("api_contract_mismatch:v0");
  });

  it("rejects backend dirty-tree drift even when HEAD is unchanged", async () => {
    const result = await inspectWorkbenchServingVersion(
      input({
        currentCode: () => ({ head: "head-current", dirtyTreeDigest: "dirty-new" }),
      }),
    );

    expect(result.ok).toBe(false);
    expect(result.reason).toBe("backend_code_mismatch");
  });

  it("fails closed when process identity is missing", async () => {
    const result = await inspectWorkbenchServingVersion(
      input({
        fetchHealth: async () => ({
          status: 200,
          json: async () => healthPayload({
            serving: {
              frontend: { buildKey: "build-current", release: "release-current" },
              backend: {
                pid: 4321,
                head: "head-current",
                dirtyTreeDigest: "dirty-current",
                createTime: 0,
                executable: "",
              },
            },
          }),
        }),
      }),
    );

    expect(result.ok).toBe(false);
    expect(result.reason).toBe("serving_contract_missing");
  });

  it("rejects a health response from another workspace", async () => {
    const result = await inspectWorkbenchServingVersion(
      input({
        fetchHealth: async () => ({
          status: 200,
          json: async () => healthPayload({ workspaceRoot: "C:/other-workspace" })
        })
      })
    );

    expect(result.ok).toBe(false);
    expect(result.reason).toBe("serving_workspace_mismatch");
  });

  it("rejects a healthy backend whose identity no longer matches launcher state", async () => {
    const result = await inspectWorkbenchServingVersion(
      input({
        readState: () => ({
          backendPid: 9999,
          backendCreateTime: 999.5,
          backendExecutable: "python.exe"
        })
      })
    );

    expect(result.ok).toBe(false);
    expect(result.reason).toBe("serving_backend_identity_mismatch");
  });
});
