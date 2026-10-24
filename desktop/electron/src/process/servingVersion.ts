import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import {
  launcherPortsPath,
  launcherStatePath,
  preferredWorkbenchPort,
  readLauncherStateFile,
  sameProjectRoot
} from "./workbenchBackend.js";
import { BACKEND_HEALTH_HTTP_TIMEOUT_MS, defaultFetchWorkbenchHealth, workbenchHealthPayloadReady, workbenchHealthUrl, type WorkbenchReadiness } from "./workbenchBackendHealth.js";
import { runPythonJsonBridge, PYTHON_JSON_BRIDGE_QUERY_TIMEOUT_MS, type PythonProcessIdentity } from "./pythonJsonBridge.js";
import { readOnlyGitText } from "./gitProcess.js";

export const WORKBENCH_API_CONTRACT_VERSION = "v1";

export type ServingVersionInspection = {
  ok: boolean;
  reason: string;
  port: number;
  buildKey?: string;
  release?: string;
  apiContractVersion?: string;
  backendPid?: number;
  health?: Record<string, unknown>;
};

type ServingVersionInput = {
  workspaceRoot: string;
  signal?: AbortSignal;
  readiness?: WorkbenchReadiness;
  port?: number;
  expectedBuildKey?: string;
  expectedRelease?: string;
  fetchHealth?: (url: string) => Promise<{ status: number; json?: () => Promise<unknown> }>;
  readActive?: (workspaceRoot: string) => { buildKey: string; release: string };
  currentCode?: (workspaceRoot: string) => { head: string; dirtyTreeDigest: string } | Promise<{ head: string; dirtyTreeDigest: string }>;
  readState?: (workspaceRoot: string) => Record<string, unknown>;
  runIdentityBridge?: typeof runPythonJsonBridge;
};

// Windows venv pythonw.exe owns the process tree, but its interpreter child
// serves HTTP. Verify both stable identities and their actual OS parent link;
// a matching port, HEAD or self-reported parent PID is not ownership evidence.
const SERVING_CHILD_IDENTITY_SCRIPT = String.raw`
import json
import sys
import psutil
from core.runtime_manager.process_identity import inspect_process_identity

launch, serving = (json.loads(value) for value in sys.argv[1:3])
matches = False
try:
    child = psutil.Process(serving["pid"])
    matches = (
        child.ppid() == launch["pid"]
        and inspect_process_identity(launch)["status"] == "match"
        and inspect_process_identity(serving)["status"] == "match"
    )
except (psutil.NoSuchProcess, psutil.ZombieProcess, psutil.AccessDenied, OSError):
    pass
print(json.dumps({"matches": matches}))
`;

async function servingChildIdentityMatches(
  input: ServingVersionInput,
  launch: PythonProcessIdentity,
  serving: PythonProcessIdentity
): Promise<boolean> {
  try {
    const raw = await (input.runIdentityBridge ?? runPythonJsonBridge)({
      pythonPath: launch.executable,
      args: ["-c", SERVING_CHILD_IDENTITY_SCRIPT, JSON.stringify(launch), JSON.stringify(serving)],
      cwd: input.workspaceRoot,
      failureLabel: "workbench serving process identity",
      timeoutMs: PYTHON_JSON_BRIDGE_QUERY_TIMEOUT_MS,
      signal: input.signal,
      killPolicy: "child"
    });
    input.signal?.throwIfAborted();
    const result: unknown = JSON.parse(raw);
    return isRecord(result) && result.matches === true;
  } catch {
    input.signal?.throwIfAborted();
    return false;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function normalizeRelease(value: unknown): string {
  const text = String(value || "").trim();
  return text.startsWith("release-") ? text : "";
}

function activeFrontendRelease(workspaceRoot: string): { buildKey: string; release: string } {
  try {
    const payload = JSON.parse(readFileSync(join(workspaceRoot, "web", ".vibelution-builds", "active.json"), "utf8")) as unknown;
    if (!isRecord(payload)) {
      return { buildKey: "", release: "" };
    }
    return {
      buildKey: String(payload.buildKey || "").trim(),
      release: normalizeRelease(payload.release)
    };
  } catch {
    return { buildKey: "", release: "" };
  }
}

async function currentBackendCode(workspaceRoot: string): Promise<{ head: string; dirtyTreeDigest: string }> {
  const [rawStatus, rawHead] = await Promise.all([
    readOnlyGitText(workspaceRoot, ["status", "--porcelain=v1", "--untracked-files=all"]),
    readOnlyGitText(workspaceRoot, ["rev-parse", "HEAD"])
  ]);
  // A failed status probe must not be hashed as an empty (clean) worktree.
  if (rawStatus === null || rawHead === null) return { head: "", dirtyTreeDigest: "" };
  const status = rawStatus.replace(/\n+$/g, "");
  return {
    head: rawHead.trim(),
    dirtyTreeDigest: createHash("sha256").update(status, "utf8").digest("hex")
  };
}

function servingHealthPayload(body: Record<string, unknown>): {
  apiContractVersion: string;
  buildKey: string;
  release: string;
  workspaceRoot: string;
  backendPid: number;
  code: Record<string, unknown>;
} | null {
  const serving = isRecord(body.serving) ? body.serving : null;
  const frontend = serving && isRecord(serving.frontend) ? serving.frontend : null;
  const backend = serving && isRecord(serving.backend)
    ? serving.backend
    : isRecord(body.backendCodeFingerprint)
      ? body.backendCodeFingerprint
      : null;
  const apiContractVersion = String(body.apiContractVersion || serving?.apiContractVersion || "").trim();
  const buildKey = String(frontend?.buildKey || body.servingBuildKey || "").trim();
  const release = normalizeRelease(frontend?.release || body.servingRelease);
  const workspaceRoot = String(body.workspaceRoot || "").trim();
  const backendPid = Number(body.pid || backend?.pid || 0);
  if (!apiContractVersion || !buildKey || !release || !workspaceRoot || !backend || !Number.isFinite(backendPid) || backendPid <= 0) {
    return null;
  }
  if (Number(backend.pid || 0) !== backendPid || !String(backend.head || "").trim()) {
    return null;
  }
  if (!String(backend.dirtyTreeDigest || "").trim() || Number(backend.createTime || 0) <= 0 || !String(backend.executable || "").trim()) {
    return null;
  }
  return { apiContractVersion, buildKey, release, workspaceRoot, backendPid, code: backend };
}

export async function inspectWorkbenchServingVersion(input: ServingVersionInput): Promise<ServingVersionInspection> {
  input.signal?.throwIfAborted();
  const port = Math.trunc(input.port || preferredWorkbenchPort({ workspaceRoot: input.workspaceRoot }));
  if (!Number.isFinite(port) || port <= 0) {
    return { ok: false, reason: "invalid_backend_port", port };
  }
  let response: { status: number; json?: () => Promise<unknown> };
  try {
    const fetchHealth = input.fetchHealth ?? defaultFetchWorkbenchHealth({
      httpTimeoutMs: BACKEND_HEALTH_HTTP_TIMEOUT_MS,
      signal: input.signal
    });
    response = await fetchHealth(workbenchHealthUrl(port));
    input.signal?.throwIfAborted();
  } catch {
    input.signal?.throwIfAborted();
    return { ok: false, reason: "health_unreachable", port };
  }
  if (response.status !== 200 || typeof response.json !== "function") {
    return { ok: false, reason: "health_not_ready", port };
  }
  let raw: unknown;
  try {
    raw = await response.json();
    input.signal?.throwIfAborted();
  } catch {
    input.signal?.throwIfAborted();
    return { ok: false, reason: "health_invalid_json", port };
  }
  if (!isRecord(raw) || !workbenchHealthPayloadReady(raw, input.readiness)) {
    return { ok: false, reason: "health_not_ready", port };
  }
  const serving = servingHealthPayload(raw);
  if (!serving) {
    return { ok: false, reason: "serving_contract_missing", port, health: raw };
  }
  if (serving.apiContractVersion !== WORKBENCH_API_CONTRACT_VERSION) {
    return {
      ok: false,
      reason: `api_contract_mismatch:${serving.apiContractVersion}`,
      port,
      apiContractVersion: serving.apiContractVersion,
      buildKey: serving.buildKey,
      release: serving.release,
      backendPid: serving.backendPid,
      health: raw
    };
  }
  if (!sameProjectRoot(serving.workspaceRoot, input.workspaceRoot)) {
    return {
      ok: false,
      reason: "serving_workspace_mismatch",
      port,
      apiContractVersion: serving.apiContractVersion,
      buildKey: serving.buildKey,
      release: serving.release,
      backendPid: serving.backendPid,
      health: raw
    };
  }
  const launcherState = (input.readState || ((workspaceRoot: string) =>
    readLauncherStateFile(launcherStatePath(workspaceRoot))))(input.workspaceRoot);
  const statePid = Number(launcherState.backendPid || 0);
  const stateCreateTime = Number(launcherState.backendCreateTime || 0);
  const stateExecutable = String(launcherState.backendExecutable || "").trim();
  const healthCreateTime = Number(serving.code.createTime || 0);
  const healthExecutable = String(serving.code.executable || "").trim();
  const normalizeExecutable = (value: string): string => value.trim().replace(/\\/g, "/").toLowerCase();
  const identitiesComplete = Number.isInteger(statePid) && statePid > 0
    && Number.isFinite(stateCreateTime) && stateCreateTime > 0 && Boolean(stateExecutable)
    && Number.isInteger(serving.backendPid) && serving.backendPid > 0
    && Number.isFinite(healthCreateTime) && healthCreateTime > 0 && Boolean(healthExecutable);
  const sameProcess = statePid === serving.backendPid
    && Math.abs(stateCreateTime - healthCreateTime) <= 0.001
    && normalizeExecutable(stateExecutable) === normalizeExecutable(healthExecutable);
  const probeCurrentCode = async () => {
    try {
      return { current: await (input.currentCode || currentBackendCode)(input.workspaceRoot) };
    } catch (error) {
      return { error };
    }
  };
  let currentProbe: ReturnType<typeof probeCurrentCode> | undefined;
  let identityMatches = identitiesComplete && sameProcess;
  if (identitiesComplete && statePid !== serving.backendPid) {
    // Consume both outcomes immediately: cancellation can throw before the
    // identity await, and an earlier identity/release failure wins over Git.
    const identityProbe = servingChildIdentityMatches(
      input,
      { pid: statePid, createTime: stateCreateTime, executable: stateExecutable },
      { pid: serving.backendPid, createTime: healthCreateTime, executable: healthExecutable }
    ).then((matches) => ({ matches }), (error: unknown) => ({ error }));
    input.signal?.throwIfAborted();
    currentProbe = probeCurrentCode();
    const identity = await identityProbe;
    input.signal?.throwIfAborted();
    if ("error" in identity) throw identity.error;
    identityMatches = identity.matches;
  }
  input.signal?.throwIfAborted();
  if (!identityMatches) {
    return {
      ok: false,
      reason: "serving_backend_identity_mismatch",
      port,
      apiContractVersion: serving.apiContractVersion,
      buildKey: serving.buildKey,
      release: serving.release,
      backendPid: serving.backendPid,
      health: raw
    };
  }
  const active = (input.readActive || activeFrontendRelease)(input.workspaceRoot);
  const expectedBuildKey = String(input.expectedBuildKey || active.buildKey || "").trim();
  const expectedRelease = normalizeRelease(input.expectedRelease || active.release);
  if (!expectedBuildKey || !expectedRelease) {
    return { ok: false, reason: "active_release_missing", port, health: raw };
  }
  if (serving.buildKey !== expectedBuildKey || serving.release !== expectedRelease) {
    return {
      ok: false,
      reason: "serving_release_mismatch",
      port,
      apiContractVersion: serving.apiContractVersion,
      buildKey: serving.buildKey,
      release: serving.release,
      backendPid: serving.backendPid,
      health: raw
    };
  }
  input.signal?.throwIfAborted();
  const code = await (currentProbe ?? probeCurrentCode());
  // An already issued read-only Git query may finish, but a superseded
  // observer must never accept its result or start another verification.
  input.signal?.throwIfAborted();
  if ("error" in code) throw code.error;
  const current = code.current;
  if (!current.head || !current.dirtyTreeDigest || serving.code.head !== current.head || serving.code.dirtyTreeDigest !== current.dirtyTreeDigest) {
    return {
      ok: false,
      reason: "backend_code_mismatch",
      port,
      apiContractVersion: serving.apiContractVersion,
      buildKey: serving.buildKey,
      release: serving.release,
      backendPid: serving.backendPid,
      health: raw
    };
  }
  return {
    ok: true,
    reason: "serving_version_current",
    port,
    apiContractVersion: serving.apiContractVersion,
    buildKey: serving.buildKey,
    release: serving.release,
    backendPid: serving.backendPid,
    health: raw
  };
}

export function servingVersionStateFilePort(workspaceRoot: string): number {
  const ports = readLauncherStateFile(launcherPortsPath(workspaceRoot));
  const value = Number(ports.backendPort || 0);
  return Number.isFinite(value) && value > 0 ? Math.trunc(value) : 0;
}

export type ServingProcessIdentity = {
  pid: number;
  createTime: number;
};

export type RestartedServingVerification = {
  ok: boolean;
  reason: string;
  inspection: ServingVersionInspection | null;
};

// Transient health reasons are worth a bounded retry: runWorkbenchLifecycle has
// already accepted the lifecycle mutation, so a slow-to-answer (but alive) new
// backend must not be reported as a failed restart verification.
const TRANSIENT_VERIFICATION_REASONS = new Set([
  "health_unreachable",
  "health_not_ready",
  "health_invalid_json",
]);

function sameProcessIdentity(
  previous: ServingProcessIdentity,
  current: ServingProcessIdentity,
): boolean {
  return previous.pid === current.pid
    && Math.abs(previous.createTime - current.createTime) <= 0.001;
}

/**
 * Prove a lifecycle start/restart actually replaced the serving backend with a
 * process built from the current checkout before the workbench window opens.
 *
 * - `inspectWorkbenchServingVersion` already proves the serving head matches
 *   the checkout HEAD (backend_code_mismatch otherwise) plus identity/release
 *   handshake.
 * - When a pre-restart backend identity is known, pid or createTime MUST have
 *   changed; an unchanged identity means the "restart" silently kept the old
 *   process (2026-09-11: acceptance ran against a 09-09 build while main had
 *   moved two days ahead, with no failure surfaced).
 *
 * Never spawns visible consoles: reuses the health fetch and the hidden
 * python JSON bridge inside `inspectWorkbenchServingVersion`.
 */
export async function verifyRestartedServingVersion(input: {
  workspaceRoot: string;
  signal?: AbortSignal;
  readiness?: WorkbenchReadiness;
  previousBackendIdentity?: ServingProcessIdentity | null;
  inspect?: typeof inspectWorkbenchServingVersion;
  attempts?: number;
  delayMs?: number;
  delay?: (ms: number) => Promise<void>;
}): Promise<RestartedServingVerification> {
  const inspect = input.inspect ?? inspectWorkbenchServingVersion;
  const attempts = Math.max(1, Math.trunc(input.attempts ?? 3));
  const delayMs = Math.max(0, Math.trunc(input.delayMs ?? 1_000));
  const wait = input.delay ?? ((ms: number) => delay(ms, undefined, { signal: input.signal }));
  const previous = input.previousBackendIdentity ?? null;
  const hasPrevious = Boolean(
    previous && Number.isFinite(previous.pid) && previous.pid > 0
      && Number.isFinite(previous.createTime) && previous.createTime > 0,
  );

  let last: RestartedServingVerification = { ok: false, reason: "verification_not_run", inspection: null };
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    input.signal?.throwIfAborted();
    if (attempt > 0) {
      await wait(delayMs);
      input.signal?.throwIfAborted();
    }
    const inspection = await inspect({ workspaceRoot: input.workspaceRoot, readiness: input.readiness, signal: input.signal });
    input.signal?.throwIfAborted();
    if (!inspection.ok) {
      last = { ok: false, reason: inspection.reason, inspection };
      if (!TRANSIENT_VERIFICATION_REASONS.has(inspection.reason)) {
        return last;
      }
      continue;
    }
    const healthRecord = isRecord(inspection.health) ? inspection.health : null;
    const servingRecord = healthRecord && isRecord(healthRecord.serving) ? healthRecord.serving : null;
    const backendRecord = servingRecord && isRecord(servingRecord.backend) ? servingRecord.backend : null;
    const current: ServingProcessIdentity = {
      pid: Number(inspection.backendPid || 0),
      createTime: Number(backendRecord?.createTime || 0),
    };
    if (hasPrevious && sameProcessIdentity(previous as ServingProcessIdentity, current)) {
      return {
        ok: false,
        reason: "serving_process_not_replaced",
        inspection,
      };
    }
    return { ok: true, reason: inspection.reason, inspection };
  }
  return last;
}
