import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { EventEmitter } from "node:events";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { PassThrough } from "node:stream";
import { afterEach, describe, expect, it, vi } from "vitest";

const nativeSpawn = vi.hoisted(() => vi.fn());
vi.mock("../src/process/workbenchJob.js", async (importOriginal) => ({
  ...await importOriginal<typeof import("../src/process/workbenchJob.js")>(),
  loadWorkbenchJobNative: () => ({
    spawn: nativeSpawn,
    exitCode: () => 0,
    activeCount: () => 0,
    drainStatus: () => ({ complete: true, channels: [] }),
    close: vi.fn()
  })
}));

import { createMainLineCommandQueue } from "../src/lifecycle/mainLine/commandQueue.js";
import {
  ensureFrontendRelease,
  executeMainLineWorkbench,
  spawnWorkbenchBackend,
  workbenchBackendEnv,
  type WorkbenchBackendSpawn
} from "../src/process/workbenchBackend.js";
import { runWorkbenchLifecycle } from "../src/process/workbenchLifecycle.js";
import {
  capturePythonProcessIdentity,
  createPythonOwnedProcessTreeTerminator,
  runPythonJsonBridge,
  type PythonJsonBridgeSpawn
} from "../src/process/pythonJsonBridge.js";
import { resolveWorkbenchPortOwner } from "../src/process/resolveWorkbenchPortOwner.js";

const roots: string[] = [];
function workspace(): string {
  const root = mkdtempSync(join(tmpdir(), "vibelution-target-environment-"));
  roots.push(root);
  return root;
}

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
  nativeSpawn.mockReset();
  for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true });
});

function setProjectAEnvironment(): void {
  vi.stubEnv("VIBELUTION_PORT", "18101");
  vi.stubEnv("VIBELUTION_DATA_HOME", "synthetic-project-a-data");
  vi.stubEnv("VIBELUTION_CONFIG_HOME", "synthetic-project-a-config");
  vi.stubEnv("VIBELUTION_LAUNCHER_CONTROL_TOKEN", "synthetic-project-a-token");
}

function projectBEnvironment(root: string): NodeJS.ProcessEnv {
  return {
    VIBELUTION_PORT: "18202",
    VIBELUTION_DATA_HOME: join(root, "data"),
    VIBELUTION_CONFIG_HOME: join(root, "config"),
    VIBELUTION_LAUNCHER_CONTROL_TOKEN: "synthetic-project-b-token",
    PYTHONPATH: join(root, "python")
  };
}

// Assert only synthetic fixture fields: a failing assertion must never print
// the ambient process environment (which may contain operator credentials).
function expectEnvironmentFields(actual: NodeJS.ProcessEnv | undefined, expected: NodeJS.ProcessEnv): void {
  for (const [key, value] of Object.entries(expected)) expect(actual?.[key], key).toBe(value);
}

function lifecycleSeams(root: string) {
  let spawned = false;
  const spawnImpl: WorkbenchBackendSpawn = vi.fn(() => {
    spawned = true;
    return { pid: 0, kill: () => true };
  });
  return {
    workspaceRoot: root,
    pythonPath: join(root, "python.exe"),
    fileExists: () => true,
    readState: () => ({ backendPort: 18303 }),
    writeState: vi.fn(),
    listActiveWork: () => [],
    ensureFrontend: vi.fn(async () => undefined),
    spawnImpl,
    connect: vi.fn(async (_port: number, _host: string) => spawned),
    fetchHealth: async () => ({ status: 200, json: async () => ({ status: "ok", shellReady: true }) }),
    pidAlive: () => false,
    killPid: () => undefined,
    readDaemonPid: () => 0,
    readDaemonIdentity: () => null
  };
}

describe("native lifecycle target environment", () => {
  it("uses a private target snapshot for queued frontend, port and backend startup", async () => {
    setProjectAEnvironment();
    const root = workspace();
    const targetEnvironment = projectBEnvironment(root);
    const expectedEnvironment = { ...targetEnvironment };
    const seams = lifecycleSeams(root);
    let releaseFrontend!: () => void;
    let startFrontend!: () => void;
    const frontendStarted = new Promise<void>((done) => { startFrontend = done; });
    const frontendWait = new Promise<void>((done) => { releaseFrontend = done; });
    const ensureFrontend = vi.fn(async (_options: { force: boolean; signal?: AbortSignal; env?: NodeJS.ProcessEnv }) => {
      startFrontend();
      await frontendWait;
    });
    const result = runWorkbenchLifecycle({
      ...seams,
      operation: "start",
      operatorConfigPath: join(root, "config", "config.toml"),
      queue: createMainLineCommandQueue(),
      targetEnvironment,
      ensureFrontend
    });
    await frontendStarted;
    targetEnvironment.VIBELUTION_PORT = "18999";
    targetEnvironment.VIBELUTION_DATA_HOME = "caller-mutated-data";
    releaseFrontend();
    await expect(result).resolves.toMatchObject({ accepted: true });
    const frontendOptions = ensureFrontend.mock.calls[0]?.[0] as { env?: NodeJS.ProcessEnv } | undefined;
    expectEnvironmentFields(frontendOptions?.env, expectedEnvironment);
    const spawnOptions = vi.mocked(seams.spawnImpl).mock.calls[0]?.[2];
    expectEnvironmentFields(spawnOptions?.env, expectedEnvironment);
    expect(spawnOptions?.env.VIBELUTION_WORKSPACE_ROOT).toBe(root);
    expect(seams.writeState).toHaveBeenLastCalledWith(expect.objectContaining({ backendPort: 18202 }));
    expect(process.env.VIBELUTION_PORT).toBe("18101");
    expect(process.env.VIBELUTION_DATA_HOME).toBe("synthetic-project-a-data");
    expect(process.env.VIBELUTION_CONFIG_HOME).toBe("synthetic-project-a-config");
    expect(process.env.VIBELUTION_LAUNCHER_CONTROL_TOKEN).toBe("synthetic-project-a-token");
  });

  it.each(["start", "stop"] as const)("does not borrow the global port on explicit target %s without PORT", async (operation) => {
    setProjectAEnvironment();
    const root = workspace();
    const seams = lifecycleSeams(root);
    const targetEnvironment = projectBEnvironment(root);
    delete targetEnvironment.VIBELUTION_PORT;
    await executeMainLineWorkbench({
      ...seams, operation, targetEnvironment,
      command: { commandId: `target-${operation}`, type: operation === "start" ? "open" : "close", operation, noBrowser: true }
    });
    expect(seams.connect).toHaveBeenCalled();
    expect(seams.connect.mock.calls.every(([port]) => port === 18303)).toBe(true);
    expect(process.env.VIBELUTION_PORT).toBe("18101");
  });

  it("keeps global environment defaults for ordinary lifecycle calls", async () => {
    setProjectAEnvironment();
    const root = workspace();
    const seams = lifecycleSeams(root);
    await executeMainLineWorkbench({
      ...seams, operation: "start",
      command: { commandId: "ordinary-start", type: "open", operation: "start", noBrowser: true }
    });
    expectEnvironmentFields(vi.mocked(seams.spawnImpl).mock.calls[0]?.[2].env, {
      VIBELUTION_PORT: "18101", VIBELUTION_DATA_HOME: "synthetic-project-a-data"
    });
    expect(seams.writeState).toHaveBeenLastCalledWith(expect.objectContaining({ backendPort: 18101 }));
  });

  it("preserves canonical backend overrides while excluding the ambient environment", () => {
    setProjectAEnvironment();
    const root = workspace();
    const baseEnv = projectBEnvironment(root);
    const spawnImpl: WorkbenchBackendSpawn = vi.fn(() => ({ pid: 0, kill: () => true }));
    spawnWorkbenchBackend({
      workspaceRoot: root, pythonPath: join(root, "python.exe"), port: 18404,
      baseEnv, extraEnv: { VIBELUTION_WORKSPACE_ROOT: "wrong-root", VIBELUTION_PORT: "1", EXTRA: "yes" },
      dataHome: join(root, "canonical-data"), configHome: join(root, "canonical-config"),
      spawnImpl, fileExists: () => true
    });
    expectEnvironmentFields(vi.mocked(spawnImpl).mock.calls[0]?.[2].env, {
      VIBELUTION_WORKSPACE_ROOT: root, VIBELUTION_PORT: "18404", AGENT_WORKBENCH_BACKEND_PORT: "18404",
      VIBELUTION_DATA_HOME: join(root, "canonical-data"), VIBELUTION_CONFIG_HOME: join(root, "canonical-config"),
      EXTRA: "yes", PYTHONUTF8: "1"
    });
    expect(workbenchBackendEnv({ workspaceRoot: root, port: 18404, baseEnv: {} }).VIBELUTION_LAUNCHER_CONTROL_TOKEN).toBeUndefined();
    expect(baseEnv).toEqual(projectBEnvironment(root));
  });

  it("passes the target environment to the JSON frontend build bridge", async () => {
    setProjectAEnvironment();
    const root = workspace();
    const env = projectBEnvironment(root);
    const runBridge = vi.fn(async (_input: Parameters<typeof runPythonJsonBridge>[0]) => JSON.stringify({ ok: true, rebuilt: true }));
    await ensureFrontendRelease({ workspaceRoot: root, pythonPath: join(root, "python.exe"), env, runBridge });
    expectEnvironmentFields((runBridge.mock.calls[0]?.[0] as { env?: NodeJS.ProcessEnv } | undefined)?.env, env);
    expect(env).toEqual(projectBEnvironment(root));
  });

  it.runIf(process.platform === "win32")("passes the target environment to the Windows owned frontend Job", async () => {
    setProjectAEnvironment();
    const root = workspace();
    const env = projectBEnvironment(root);
    nativeSpawn.mockImplementation((input) => {
      writeFileSync(input.stdoutPath, JSON.stringify({ ok: true, skipped: true }));
      return { job: {} };
    });
    await ensureFrontendRelease({ workspaceRoot: root, pythonPath: join(root, "python.exe"), env });
    expectEnvironmentFields(nativeSpawn.mock.calls[0]?.[0]?.env, env);
    expect(process.env.VIBELUTION_PORT).toBe("18101");
  });

  it.runIf(process.platform === "win32")("carries the target through the default frontend ensure path", async () => {
    setProjectAEnvironment();
    const root = workspace();
    const env = projectBEnvironment(root);
    nativeSpawn.mockImplementation((input) => {
      writeFileSync(input.stdoutPath, JSON.stringify({ ok: true, skipped: true }));
      return { job: {} };
    });
    await executeMainLineWorkbench({
      ...lifecycleSeams(root), ensureFrontend: undefined, targetEnvironment: env, operation: "start",
      command: { commandId: "default-frontend", type: "open", operation: "start", noBrowser: true }
    });
    expectEnvironmentFields(nativeSpawn.mock.calls[0]?.[0]?.env, env);
  });

  it.each([true, false])("uses the real JSON bridge spawn environment (explicit target: %s)", async (explicit) => {
    setProjectAEnvironment();
    const root = workspace();
    const env = projectBEnvironment(root);
    const spawnImpl: PythonJsonBridgeSpawn = vi.fn(() => {
      const child = Object.assign(new EventEmitter(), {
        pid: undefined, stdout: new PassThrough(), stderr: new PassThrough(), kill: () => true
      });
      queueMicrotask(() => {
        child.stdout.end("{}");
        child.stderr.end();
        child.emit("close", 0, null);
      });
      return child as unknown as ReturnType<PythonJsonBridgeSpawn>;
    });
    await expect(runPythonJsonBridge({
      pythonPath: join(root, "python.exe"), args: [], cwd: root, spawnImpl,
      failureLabel: "synthetic environment bridge", timeoutMs: 1000, killPolicy: "child",
      ...(explicit ? { env } : {})
    })).resolves.toBe("{}");
    expectEnvironmentFields(vi.mocked(spawnImpl).mock.calls[0]?.[2].env, explicit ? env : {
      VIBELUTION_PORT: "18101", VIBELUTION_DATA_HOME: "synthetic-project-a-data"
    });
    expect(process.env.VIBELUTION_PORT).toBe("18101");
  });

  it.each(["identity", "termination", "port-owner"] as const)("passes target context through the %s helper to its real bridge spawn", async (helper) => {
    setProjectAEnvironment();
    const root = workspace();
    const env = projectBEnvironment(root);
    const identity = { pid: 4321, createTime: 1, executable: join(root, "python.exe") };
    const payload = helper === "identity" ? identity : helper === "termination"
      ? { pid: 4321, status: "terminated" }
      : { schemaVersion: 1, ok: true, pid: 4321, kind: "managed_workbench_backend", alive: true, trusted: true };
    const spawnImpl: PythonJsonBridgeSpawn = vi.fn(() => {
      const child = Object.assign(new EventEmitter(), {
        pid: undefined, stdout: new PassThrough(), stderr: new PassThrough(), kill: () => true
      });
      queueMicrotask(() => {
        child.stdout.end(JSON.stringify(payload));
        child.stderr.end();
        child.emit("close", 0, null);
      });
      return child as unknown as ReturnType<PythonJsonBridgeSpawn>;
    });
    const input = { workspaceRoot: root, pythonPath: identity.executable, env, spawnImpl };
    if (helper === "identity") {
      await expect(capturePythonProcessIdentity({ ...input, pid: 4321 })).resolves.toEqual(identity);
    } else if (helper === "termination") {
      const terminate = createPythonOwnedProcessTreeTerminator({ ...input, allowedKinds: ["managed_workbench_backend"] });
      await expect(terminate(4321, identity)).resolves.toBe(true);
    } else {
      await expect(resolveWorkbenchPortOwner({ ...input, port: 18202 })).resolves.toMatchObject({ pid: 4321, trusted: true });
    }
    const spawnOptions = vi.mocked(spawnImpl).mock.calls[0]?.[2];
    expectEnvironmentFields(spawnOptions?.env, env);
    expect(spawnOptions?.cwd).toBe(root);
    expect(process.env.VIBELUTION_PORT).toBe("18101");
  });

  it.each([true, false])("keeps identity helper admission scoped (explicit target: %s)", async (explicit) => {
    setProjectAEnvironment();
    const root = workspace();
    const env = projectBEnvironment(root);
    const identity = { pid: 4321, createTime: 1, executable: join(root, "python.exe") };
    const captureProcessIdentity = vi.fn(async (_input: { env?: NodeJS.ProcessEnv }) => identity);
    let spawned = false;
    await executeMainLineWorkbench({
      ...lifecycleSeams(root), operation: "start", captureProcessIdentity,
      ...(explicit ? { targetEnvironment: env } : {}),
      spawnImpl: () => { spawned = true; return { pid: 4321, kill: () => true }; },
      connect: async () => spawned,
      command: { commandId: "helper-admission", type: "open", operation: "start", noBrowser: true }
    });
    const helperInput = captureProcessIdentity.mock.calls[0]?.[0];
    expect(helperInput && Object.hasOwn(helperInput, "env")).toBe(explicit);
    if (explicit) expectEnvironmentFields(helperInput?.env, env);
  });

  it.each([true, false])("keeps port-owner helper admission scoped (explicit target: %s)", async (explicit) => {
    setProjectAEnvironment();
    const root = workspace();
    const env = projectBEnvironment(root);
    const resolvePortOwner = vi.fn(async (_input: { env?: NodeJS.ProcessEnv }) => null);
    await expect(executeMainLineWorkbench({
      ...lifecycleSeams(root), operation: "start", resolvePortOwner,
      ...(explicit ? { targetEnvironment: env } : {}),
      connect: async () => true,
      fetchHealth: async () => ({ status: 200, json: async () => ({ status: "unknown" }) }),
      command: { commandId: "owner-admission", type: "open", operation: "start", noBrowser: true }
    })).rejects.toThrow();
    expect(resolvePortOwner).toHaveBeenCalled();
    const helperInput = resolvePortOwner.mock.calls[0]?.[0];
    expect(helperInput && Object.hasOwn(helperInput, "env")).toBe(explicit);
    if (explicit) expectEnvironmentFields(helperInput?.env, env);
  });
});
