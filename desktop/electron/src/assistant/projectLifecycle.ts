import { realpathSync } from "node:fs";
import { createHash } from "node:crypto";
import { isAbsolute, resolve } from "node:path";

import { getMainLineCommandQueueForProject, type MainLineCommandQueue, type MainLineLifecycleOperation, type MainLineQueuedCommand, type MainLineSubmitInput } from "../lifecycle/mainLine/commandQueue.js";
import type { LifecycleRequestBinding } from "./projectLifecycleRequestStore.js";
import { writeMainLineIntent } from "../lifecycle/mainLine/commandIntent.js";
import { writeMainLineQueueOwnerMarker } from "../lifecycle/mainLine/ownerMarker.js";
import { resolveRuntimeManagerDir } from "../lifecycle/projectStoragePaths.js";
import { runWorkbenchLifecycle, type RunWorkbenchLifecycleInput, type WorkbenchLifecycleResult } from "../process/workbenchLifecycle.js";
import type { AssistantProjectRegistrySnapshot } from "./projectRegistry.js";
import type { ProjectAdmission, ProjectAdmissionTicket } from "../lifecycle/projectAdmission.js";

export type AssistantProjectLifecycleOperation = "status" | "start" | "stop" | "restart";
export type AssistantProjectLifecycleTarget = { projectId: string; workspaceRoot: string };
/** Main-owned configuration only; never populated from the assistant request. */
export type AssistantProjectRuntimeContext = {
  workspaceRoot: string;
  pythonPath: string;
  operatorConfigPath: string;
  /** Compatibility assertion only; the facade derives and uses the native owner. */
  runtimeManagerDir: string;
  /** Explicit target process environment, captured by the trusted main resolver. */
  environment?: NodeJS.ProcessEnv;
};
export type AssistantProjectLifecycleOptions = {
  /** Trusted main-owned gate; ordinary callers leave this unset. */
  admission?: ProjectAdmission;
  /** Must read the current complete permission table, including registry disk validation. */
  getPermissionSnapshot: () => AssistantProjectRegistrySnapshot;
  /** No discovery, repair, bootstrap, backend connection, or assistant-Python fallback. */
  resolveRuntimeContext: (target: AssistantProjectLifecycleTarget) => Promise<AssistantProjectRuntimeContext | null>;
  /** Read existing native status; a stopped backend must remain queryable. */
  readStatus: (target: AssistantProjectLifecycleTarget) => Promise<unknown>;
  runLifecycle?: (input: RunWorkbenchLifecycleInput) => Promise<WorkbenchLifecycleResult>;
  realPath?: (root: string) => string;
  /** Trusted main/test seam only. Production defaults to the native storage owner. */
  resolveNativeRuntimeManagerDir?: (workspaceRoot: string) => string;
};
type FailureCode = "invalid_request" | "project_unavailable" | "registration_changed" | "storage_owner_changed" | "prerequisite_required" | "context_limit" | "status_unavailable" | "lifecycle_failed" | "cancelled";
type ResultCode = FailureCode | "status" | "accepted" | "rejected" | "active_work_blocked" | "restart_queued" | "lifecycle_intent_superseded" | "backend_retire_incomplete" | "close_backoff_coalesced";
type StatusState = "stopped" | "starting" | "running" | "stopping" | "failed" | "unknown";
export type AssistantProjectLifecycleResult = {
  schemaVersion: 1;
  projectId?: string;
  operation?: AssistantProjectLifecycleOperation;
  accepted: boolean;
  code: ResultCode;
  status?: { state: StatusState; activeWorkCount?: number };
};
type Request = { projectId: string; operation: AssistantProjectLifecycleOperation };
type Permission = AssistantProjectLifecycleTarget & { fingerprint: string; physicalRoot: string; runtimeManagerDir: string };
type Context = AssistantProjectRuntimeContext & { queue: MainLineCommandQueue };
export type AssistantProjectLifecycleExecution = {
  signal?: AbortSignal;
  /** Main-owned request association, never supplied by an agent or renderer. */
  onCommand?: (binding: LifecycleRequestBinding, command: MainLineQueuedCommand) => Promise<void>;
};
const nativeCodes = new Set<ResultCode>(["active_work_blocked", "restart_queued", "lifecycle_intent_superseded", "backend_retire_incomplete", "close_backoff_coalesced"]);
export function projectLifecycleResultCode(accepted: boolean, code: unknown): ResultCode {
  return nativeCodes.has(code as ResultCode) ? code as ResultCode : accepted ? "accepted" : "rejected";
}
/** Bound retained registrations without cancelling or replacing an in-flight queue. */
export const MAX_ASSISTANT_PROJECT_LIFECYCLE_CONTEXTS = 128;
class FacadeFailure extends Error { constructor(readonly code: FailureCode) { super(code); } }
const fail = (code: FailureCode): never => { throw new FacadeFailure(code); };
const opaqueId = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$/;
const operations = new Set(["status", "start", "stop", "restart"]);
function record(value: unknown): value is Record<string, unknown> { return value !== null && typeof value === "object" && !Array.isArray(value); }
function canonical(path: string): string { const result = resolve(path); return process.platform === "win32" ? result.toLowerCase() : result; }
function absolute(value: unknown): value is string { return typeof value === "string" && value === value.trim() && !value.includes("\0") && isAbsolute(value); }

/** Capture data descriptors once: accessors, symbols and extra capabilities are rejected. */
function request(value: unknown): Request {
  if (!record(value) || ![Object.prototype, null].includes(Object.getPrototypeOf(value))) return fail("invalid_request");
  const descriptors = Object.getOwnPropertyDescriptors(value);
  if (Reflect.ownKeys(value).length !== 2 || !Object.hasOwn(descriptors, "projectId") || !Object.hasOwn(descriptors, "operation")) return fail("invalid_request");
  const id = descriptors.projectId, op = descriptors.operation;
  if (!Object.hasOwn(id, "value") || !Object.hasOwn(op, "value") || typeof id.value !== "string" || !opaqueId.test(id.value)
    || typeof op.value !== "string" || !operations.has(op.value)) return fail("invalid_request");
  return { projectId: id.value, operation: op.value as AssistantProjectLifecycleOperation };
}

/**
 * An Electron-main capability boundary over the existing native lifecycle owner.
 * cancelled/lifecycle_failed mean this call did not confirm the outcome: a native
 * command may already have had effects. They MUST NOT trigger automatic retries.
 * Durable request association is supplied by the main-owned request controller;
 * the transport must use that controller before exposing writes to an agent.
 * Retained contexts are capped for this facade's lifetime; hitting the cap fails
 * closed until its owner can safely retire/recreate it, never cancelling work.
 */
export function createAssistantProjectLifecycle(options: AssistantProjectLifecycleOptions): {
  dispatch(input: unknown, execution?: AssistantProjectLifecycleExecution): Promise<AssistantProjectLifecycleResult>;
  /** Trusted main-only binding inspection; not a model/renderer response. */
  bindingFor(projectId: string): LifecycleRequestBinding;
} {
  const { getPermissionSnapshot, resolveRuntimeContext, readStatus } = options;
  const runner = options.runLifecycle ?? runWorkbenchLifecycle;
  const realPath = options.realPath ?? (root => realpathSync.native(root));
  const nativeStorageOwner = options.resolveNativeRuntimeManagerDir ?? resolveRuntimeManagerDir;
  const contexts = new Map<string, { runtimeManagerDir: string; ready: Promise<Context> }>();

  function storageOwner(workspaceRoot: string): string {
    try {
      const owner = nativeStorageOwner(workspaceRoot);
      if (!absolute(owner)) return fail("storage_owner_changed");
      return canonical(owner);
    } catch { return fail("storage_owner_changed"); }
  }
  function contextKey(expected: AssistantProjectLifecycleTarget & { physicalRoot: string }): string {
    return JSON.stringify([expected.projectId, expected.workspaceRoot, expected.physicalRoot]);
  }
  function checkStorageOwner(context: Pick<Context, "workspaceRoot" | "runtimeManagerDir">): void {
    if (storageOwner(context.workspaceRoot) !== context.runtimeManagerDir) fail("storage_owner_changed");
  }

  function permission(projectId: string): Permission {
    const snapshot = getPermissionSnapshot();
    if (!record(snapshot) || snapshot.schemaVersion !== 1 || !Number.isSafeInteger(snapshot.revision) || snapshot.revision < 0 || !record(snapshot.projects)) return fail("project_unavailable");
    // Capture the entire table before asynchronous work. Revision alone cannot
    // protect against a faulty/stale provider changing a root under one epoch.
    const entries = Object.entries(snapshot.projects).sort(([a], [b]) => a.localeCompare(b));
    if (entries.length > 128 || entries.some(([id, root]) => !opaqueId.test(id) || !absolute(root))) return fail("project_unavailable");
    const root = entries.find(([id]) => id === projectId)?.[1];
    if (!root) return fail("project_unavailable");
    let physicalRoot: string;
    try { physicalRoot = canonical(realPath(root)); } catch { return fail("registration_changed"); }
    if (physicalRoot !== canonical(root)) return fail("registration_changed");
    const expected = { projectId, workspaceRoot: root, physicalRoot, runtimeManagerDir: storageOwner(root), fingerprint: JSON.stringify([snapshot.revision, entries]) };
    const cached = contexts.get(contextKey(expected));
    // Preserve the original queue on migration; creating another queue for the
    // same registration would split intent and native settlement ownership.
    if (cached && cached.runtimeManagerDir !== expected.runtimeManagerDir) fail("storage_owner_changed");
    return expected;
  }
  function recheck(expected: Permission): void {
    let current: Permission;
    try { current = permission(expected.projectId); } catch (error) {
      if (error instanceof FacadeFailure && error.code === "storage_owner_changed") throw error;
      return fail("registration_changed");
    }
    if (current.fingerprint !== expected.fingerprint || current.workspaceRoot !== expected.workspaceRoot || current.physicalRoot !== expected.physicalRoot) fail("registration_changed");
    if (current.runtimeManagerDir !== expected.runtimeManagerDir) fail("storage_owner_changed");
  }
  function checkSignal(signal?: AbortSignal): void { if (signal?.aborted) fail("cancelled"); }
  function bindingFor(expected: Permission): LifecycleRequestBinding {
    return { workspaceRoot: expected.workspaceRoot, runtimeManagerDir: expected.runtimeManagerDir,
      registryFingerprint: createHash("sha256").update(expected.fingerprint).digest("hex") };
  }
  async function contextFor(expected: Permission): Promise<Context> {
    recheck(expected);
    const key = contextKey(expected);
    let existing = contexts.get(key);
    if (!existing) {
      if (contexts.size >= MAX_ASSISTANT_PROJECT_LIFECYCLE_CONTEXTS) return fail("context_limit");
      const ready = (async () => {
        const raw = await resolveRuntimeContext({ projectId: expected.projectId, workspaceRoot: expected.workspaceRoot });
        recheck(expected);
        if (!raw || !absolute(raw.workspaceRoot) || raw.workspaceRoot !== expected.workspaceRoot || !absolute(raw.pythonPath) || !absolute(raw.operatorConfigPath) || !absolute(raw.runtimeManagerDir)) return fail("prerequisite_required");
        if (canonical(raw.runtimeManagerDir) !== expected.runtimeManagerDir) fail("storage_owner_changed");
        const runtime = { workspaceRoot: raw.workspaceRoot, pythonPath: raw.pythonPath, operatorConfigPath: raw.operatorConfigPath, runtimeManagerDir: expected.runtimeManagerDir,
          ...(raw.environment ? { environment: { ...raw.environment } } : {}) };
        checkStorageOwner(runtime);
        // The assistant and ordinary Launcher controls share the target's
        // canonical native queue, never a parallel assistant executor.
        const queue = getMainLineCommandQueueForProject(runtime.workspaceRoot, runtime.runtimeManagerDir, {
          persistIntent: intent => { checkStorageOwner(runtime); return writeMainLineIntent(runtime.runtimeManagerDir, intent); },
          writeOwnerMarker: async () => { checkStorageOwner(runtime); await writeMainLineQueueOwnerMarker(runtime.runtimeManagerDir); },
        });
        return { ...runtime, queue };
      })();
      existing = { runtimeManagerDir: expected.runtimeManagerDir, ready };
      contexts.set(key, existing);
      const captured = existing;
      void captured.ready.catch(() => { if (contexts.get(key) === captured) contexts.delete(key); });
    }
    const context = await existing.ready;
    recheck(expected);
    checkStorageOwner(context);
    return context;
  }
  // Stop and restart can retire a live backend, so their guarded admission must
  // hold the main-line exclusive fence: it refuses concurrent queue work, drains
  // outstanding settlement/marker evidence first, and never joins, supersedes or
  // coalesces another command's intent. Start only opens and keeps the ordinary
  // join path.
  const fencedOperations = new Set<MainLineLifecycleOperation>(["stop", "restart"]);
  function guardedQueue(context: Context, expected: Permission, execution: AssistantProjectLifecycleExecution, admission?: ProjectAdmissionTicket): MainLineCommandQueue {
    const { signal, onCommand } = execution;
    return {
      snapshot: () => context.queue.snapshot(),
      ...(context.queue.captureExecutionDrain ? { captureExecutionDrain: () => context.queue.captureExecutionDrain!() } : {}),
      submit(input) {
        checkSignal(signal); recheck(expected); checkStorageOwner(context);
        admission?.check();
        const guarded: MainLineSubmitInput = { ...input, signal,
          ...(onCommand ? { onCommand: async (command: MainLineQueuedCommand) => {
            checkSignal(signal); recheck(expected); checkStorageOwner(context);
            admission?.check();
            await onCommand(bindingFor(expected), command);
            checkSignal(signal); recheck(expected); checkStorageOwner(context);
            admission?.check();
          } } : {}), execute: async command => {
            checkSignal(signal); recheck(expected); checkStorageOwner(context);
            admission?.check();
            return input.execute(command);
          } };
        return fencedOperations.has(input.operation) && context.queue.submitExclusive
          ? context.queue.submitExclusive(guarded) : context.queue.submit(guarded);
      },
    };
  }
  return {
    bindingFor: projectId => bindingFor(permission(request({ projectId, operation: "status" }).projectId)),
    async dispatch(input, execution = {}) {
      let captured: Request;
      try { captured = request(input); } catch { return { schemaVersion: 1, accepted: false, code: "invalid_request" }; }
      const base = { schemaVersion: 1 as const, ...captured };
      const signal = execution.signal;
      let admission: ProjectAdmissionTicket | undefined;
      try {
        checkSignal(signal);
        const expected = permission(captured.projectId);
        if ((captured.operation === "start" || captured.operation === "restart") && options.admission) admission = options.admission.enter(expected.workspaceRoot);
        if (captured.operation === "status") {
          let raw: unknown;
          try { raw = await readStatus({ projectId: expected.projectId, workspaceRoot: expected.workspaceRoot }); }
          catch { return fail("status_unavailable"); }
          checkSignal(signal); recheck(expected);
          const states = new Set(["stopped", "starting", "running", "stopping", "failed", "unknown"]);
          const state: StatusState = record(raw) && typeof raw.state === "string" && states.has(raw.state) ? raw.state as StatusState : "unknown";
          const count = record(raw) ? raw.activeWorkCount : undefined;
          return { ...base, accepted: true, code: "status", status: { state, ...(typeof count === "number" && Number.isSafeInteger(count) && count >= 0 ? { activeWorkCount: count } : {}) } };
        }
        const context = await contextFor(expected);
        checkSignal(signal); recheck(expected);
        admission?.check();
        const result = await runner({ workspaceRoot: context.workspaceRoot, pythonPath: context.pythonPath, operatorConfigPath: context.operatorConfigPath,
          ...(admission ? { beforeExecute: () => admission!.check(), beforeSpawn: () => admission!.check() } : {}),
          operation: captured.operation, interruptActiveWork: false, targetEnvironment: context.environment, signal, queue: guardedQueue(context, expected, execution, admission) });
        checkSignal(signal);
        if (!result || result.schemaVersion !== 1 || typeof result.accepted !== "boolean") fail("lifecycle_failed");
        // Never forward native message, commandId, work rows, arbitrary codes,
        // path-bearing state, or thrown exception text across the boundary.
        const code = projectLifecycleResultCode(result.accepted, result.code);
        return { ...base, accepted: result.accepted, code };
      } catch (error) {
        return { ...base, accepted: false, code: signal?.aborted ? "cancelled" : error instanceof FacadeFailure ? error.code : "lifecycle_failed" };
      } finally {
        admission?.finish();
      }
    },
  };
}
