import { afterEach, describe, expect, it, vi } from "vitest";
import { inspectWorkbenchServingVersion, verifyRestartedServingVersion } from "../src/process/servingVersion.js";

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

describe("serving-version cancellation", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("does not start any probe when already cancelled", async () => {
    const controller = new AbortController();
    const reason = new Error("superseded");
    controller.abort(reason);
    const fetchHealth = vi.fn();
    await expect(inspectWorkbenchServingVersion(input({ signal: controller.signal, fetchHealth }))).rejects.toBe(reason);
    expect(fetchHealth).not.toHaveBeenCalled();
  });

  it("cancels the HTTP request without treating cancellation as unreachable health", async () => {
    const controller = new AbortController();
    const reason = new Error("superseded");
    let requestSignal: AbortSignal | undefined;
    const fetchHealth = vi.fn((_url: string, options: RequestInit) => {
      requestSignal = options.signal as AbortSignal;
      return new Promise((_resolve, reject) => requestSignal!.addEventListener("abort", () => reject(requestSignal!.reason), { once: true }));
    });
    vi.stubGlobal("fetch", fetchHealth);
    const pending = inspectWorkbenchServingVersion(input({ signal: controller.signal, fetchHealth: undefined }));
    const rejected = expect(pending).rejects.toBe(reason);
    expect(requestSignal?.aborted).toBe(false);
    controller.abort(reason);
    await rejected;
    expect(requestSignal?.aborted).toBe(true);
  });

  it.each([false, true])("stops after a cancelled health body read (rejects: %s)", async (rejects) => {
    const controller = new AbortController();
    const reason = new Error("superseded");
    const currentCode = vi.fn();
    const fetchHealth = async () => ({ status: 200, json: async () => {
      controller.abort(reason);
      if (rejects) throw new Error("body aborted");
      return healthPayload();
    } });
    await expect(inspectWorkbenchServingVersion(input({ signal: controller.signal, fetchHealth, currentCode }))).rejects.toBe(reason);
    expect(currentCode).not.toHaveBeenCalled();
  });

  it("cancels only the identity probe child and does not report an identity mismatch", async () => {
    const controller = new AbortController();
    const reason = new Error("superseded");
    const currentCode = vi.fn();
    const runIdentityBridge = vi.fn(async (options: { signal?: AbortSignal }) => {
      expect(options.signal).toBe(controller.signal);
      controller.abort(reason);
      throw new Error("probe aborted");
    });
    await expect(inspectWorkbenchServingVersion(input({
      signal: controller.signal,
      readState: () => ({ backendPid: 4000, backendCreateTime: 123.4, backendExecutable: "pythonw.exe" }),
      runIdentityBridge,
      currentCode
    }))).rejects.toBe(reason);
    expect(runIdentityBridge).toHaveBeenCalledWith(expect.objectContaining({ signal: controller.signal, killPolicy: "child" }));
    expect(currentCode).not.toHaveBeenCalled();
  });

  it("discards a successful identity response returned after cancellation", async () => {
    const controller = new AbortController();
    const reason = new Error("superseded");
    const currentCode = vi.fn();
    await expect(inspectWorkbenchServingVersion(input({
      signal: controller.signal,
      readState: () => ({ backendPid: 4000, backendCreateTime: 123.4, backendExecutable: "pythonw.exe" }),
      runIdentityBridge: async () => { controller.abort(reason); return JSON.stringify({ matches: true }); },
      currentCode
    }))).rejects.toBe(reason);
    expect(currentCode).not.toHaveBeenCalled();
  });

  it("allows an issued code query to finish but never accepts its late result", async () => {
    const controller = new AbortController();
    const reason = new Error("superseded");
    let finish!: (value: { head: string; dirtyTreeDigest: string }) => void;
    const currentCode = vi.fn(() => new Promise<{ head: string; dirtyTreeDigest: string }>((resolve) => { finish = resolve; }));
    const pending = inspectWorkbenchServingVersion(input({ signal: controller.signal, currentCode }));
    const rejected = expect(pending).rejects.toBe(reason);
    await vi.waitFor(() => expect(currentCode).toHaveBeenCalledOnce());
    controller.abort(reason);
    finish({ head: "head-current", dirtyTreeDigest: "dirty-current" });
    await rejected;
  });
});

describe("shell serving verification", () => {
  it("waits for the asynchronous code fingerprint before accepting the backend", async () => {
    let finish!: (value: { head: string; dirtyTreeDigest: string }) => void;
    const currentCode = vi.fn(() => new Promise<{ head: string; dirtyTreeDigest: string }>((resolve) => { finish = resolve; }));
    let settled = false;
    const pending = inspectWorkbenchServingVersion(input({ currentCode })).then((result) => { settled = true; return result; });
    await vi.waitFor(() => expect(currentCode).toHaveBeenCalledOnce());
    expect(settled).toBe(false);
    finish({ head: "head-current", dirtyTreeDigest: "dirty-current" });
    expect((await pending).ok).toBe(true);
  });
  it("keeps identity and version validation before routes finish warming", async () => {
    const fetchHealth = async () => ({ status: 200, json: async () => healthPayload({ shellReady: true, routesReady: false }) });
    expect((await inspectWorkbenchServingVersion(input({ fetchHealth }))).reason).toBe("health_not_ready");
    expect((await inspectWorkbenchServingVersion(input({ fetchHealth, readiness: "shell" }))).ok).toBe(true);
    expect((await inspectWorkbenchServingVersion(input({
      fetchHealth, readiness: "shell", currentCode: () => ({ head: "other", dirtyTreeDigest: "dirty-current" })
    }))).reason).toBe("backend_code_mismatch");
    expect((await inspectWorkbenchServingVersion(input({
      fetchHealth, readiness: "shell", readState: () => ({ backendPid: 4321, backendCreateTime: 999, backendExecutable: "python.exe" })
    }))).reason).toBe("serving_backend_identity_mismatch");
  });
});

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

describe("verifyRestartedServingVersion", () => {
  function baseInspection(overrides: Record<string, unknown> = {}): Record<string, unknown> {
    return {
      ok: true,
      reason: "serving_version_current",
      port: 8765,
      backendPid: 4321,
      health: {
        status: "ok",
        serving: { backend: { pid: 4321, createTime: 123.5 } },
      },
      ...overrides,
    };
  }

  it("does not inspect an already cancelled verification", async () => {
    const controller = new AbortController();
    const reason = new Error("superseded");
    controller.abort(reason);
    const inspect = vi.fn();
    await expect(verifyRestartedServingVersion({ workspaceRoot: "C:/workspace", signal: controller.signal, inspect })).rejects.toBe(reason);
    expect(inspect).not.toHaveBeenCalled();
  });

  it.each([true, false])("does not retry or accept a late cancelled inspection (ok: %s)", async (ok) => {
    const controller = new AbortController();
    const reason = new Error("superseded");
    const wait = vi.fn(async () => {});
    const inspect = vi.fn(async (options: { signal?: AbortSignal }) => {
      expect(options.signal).toBe(controller.signal);
      controller.abort(reason);
      return baseInspection({ ok, reason: ok ? "serving_version_current" : "health_unreachable" }) as never;
    });
    await expect(verifyRestartedServingVersion({
      workspaceRoot: "C:/workspace", signal: controller.signal, inspect, delay: wait
    })).rejects.toBe(reason);
    expect(inspect).toHaveBeenCalledOnce();
    expect(wait).not.toHaveBeenCalled();
  });

  it("cancels the default retry wait without issuing another health probe", async () => {
    const controller = new AbortController();
    const reason = new Error("superseded");
    const inspect = vi.fn(async () => baseInspection({ ok: false, reason: "health_not_ready" }) as never);
    const pending = verifyRestartedServingVersion({ workspaceRoot: "C:/workspace", signal: controller.signal, inspect });
    const rejected = expect(pending).rejects.toMatchObject({ name: "AbortError", cause: reason });
    await vi.waitFor(() => expect(inspect).toHaveBeenCalledOnce());
    controller.abort(reason);
    await rejected;
    expect(inspect).toHaveBeenCalledOnce();
  });

  it("rejects when the serving process was not replaced after restart", async () => {
    // 2026-09-11: a "restarted" workbench kept serving the old process.
    const inspect = vi.fn(async () => baseInspection() as never);
    const result = await verifyRestartedServingVersion({
      workspaceRoot: "C:/workspace",
      previousBackendIdentity: { pid: 4321, createTime: 123.5 },
      inspect,
      attempts: 2,
      delayMs: 0,
      delay: async () => {},
    });
    expect(result.ok).toBe(false);
    expect(result.reason).toBe("serving_process_not_replaced");
  });

  it("accepts when pid or createTime changed and the build is current", async () => {
    const inspect = vi.fn(async () => baseInspection() as never);
    const result = await verifyRestartedServingVersion({
      workspaceRoot: "C:/workspace",
      previousBackendIdentity: { pid: 4000, createTime: 100.0 },
      inspect,
      attempts: 1,
      delayMs: 0,
      delay: async () => {},
    });
    expect(result.ok).toBe(true);
    expect(result.reason).toBe("serving_version_current");
  });

  it("retries transient health reasons before failing", async () => {
    const inspect = vi.fn()
      .mockResolvedValueOnce(baseInspection({ ok: false, reason: "health_not_ready" }) as never)
      .mockResolvedValueOnce(baseInspection({ ok: false, reason: "health_unreachable" }) as never)
      .mockResolvedValueOnce(baseInspection() as never);
    const result = await verifyRestartedServingVersion({
      workspaceRoot: "C:/workspace",
      previousBackendIdentity: { pid: 4000, createTime: 100.0 },
      inspect,
      attempts: 3,
      delayMs: 0,
      delay: async () => {},
    });
    expect(result.ok).toBe(true);
    expect(inspect).toHaveBeenCalledTimes(3);
  });

  it("fails fast on a non-transient mismatch such as a stale build", async () => {
    // backend_code_mismatch proves the serving head is not the checkout HEAD.
    const inspect = vi.fn(async () => baseInspection({ ok: false, reason: "backend_code_mismatch" }) as never);
    const result = await verifyRestartedServingVersion({
      workspaceRoot: "C:/workspace",
      previousBackendIdentity: { pid: 4000, createTime: 100.0 },
      inspect,
      attempts: 3,
      delayMs: 0,
      delay: async () => {},
    });
    expect(result.ok).toBe(false);
    expect(result.reason).toBe("backend_code_mismatch");
    expect(inspect).toHaveBeenCalledTimes(1);
  });

  it("does not require a replacement when no previous identity is known", async () => {
    const inspect = vi.fn(async () => baseInspection() as never);
    const result = await verifyRestartedServingVersion({
      workspaceRoot: "C:/workspace",
      previousBackendIdentity: null,
      inspect,
      attempts: 1,
      delayMs: 0,
      delay: async () => {},
    });
    expect(result.ok).toBe(true);
  });
});
