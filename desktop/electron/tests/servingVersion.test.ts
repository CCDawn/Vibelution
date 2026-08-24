import { describe, expect, it } from "vitest";
import { inspectWorkbenchServingVersion } from "../src/process/servingVersion.js";

function healthPayload(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    status: "ok",
    routesReady: true,
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
    ...overrides,
  };
}

describe("workbench serving-version handshake", () => {
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
});
