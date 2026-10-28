/** Launcher-owned source-host lifecycle; packaged host distribution is a separate boundary. */
import { createHash, randomBytes, randomUUID } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { isAbsolute, join, resolve } from "node:path";
import { loadWorkbenchJobNative, type WorkbenchJobHandle, type WorkbenchJobNative } from "../process/workbenchJob.js";
import { resolveNoConsolePython } from "../process/workbenchBackend.js";
import { MAX_ASSISTANT_PROJECTS, type AssistantProjectRegistrySnapshot } from "./projectRegistry.js";
import { parseAffairsSyncResult, parseEpisodicSyncResult, runMainControlPump, unknownAffairsSyncResult, unknownEpisodicSyncResult, type InitialMigrationMainControlRequest, type MainControlRequest } from "./mainControlTransport.js";

const STARTUP_MS = 60_000;
const REQUEST_MS = 15_000;
const MAX_RESPONSE_BYTES = 8 * 1024 * 1024;
const MAX_LOG_BYTES = 4 * 1024 * 1024;
const READY_MAX_BYTES = 4_096;

export type AssistantHostSnapshot = {
  state: "stopped" | "starting" | "ready" | "stopping" | "failed";
  errorCode: string | null;
};
export type AssistantHostRequest =
  | { operation: "status" | "detail" | "dispatches" | "config" | "approvals" }
  | { operation: "resolveApproval"; requestId: string; decision: "accept" | "decline" }
  | { operation: "send"; message: string; requestId: string }
  | { operation: "stop"; turnId: string }
  | { operation: "continue"; requestId: string; continuation: { turnId: string; headId: string; ledgerSeq: number; agentId: string } }
  | { operation: "curation"; sessionId: string }
  | { operation: "curate"; sessionId: string; messageId: string; action: "include" | "exclude" }
  | { operation: "operatorAsset"; kind: "avatar" | "background" }
  | { operation: "computerState" }
  | { operation: "computerWindows" }
  | { operation: "computerGrant"; selectionId: string; allowVision: true }
  | { operation: "computerControl"; grantId: string; action: "pause" | "resume" | "takeover" | "return" | "end" }
  | { operation: "computerConfirm"; grantId: string; pendingId: string; approved: boolean };

/** Private to Electron main; attemptToken must never cross the renderer bridge. */
export type AssistantReminder = {
  id: string; kind: "affair_reminder"; severity: "high" | "medium";
  title: string; body: string; targetUrl: string; attemptToken: string; recoveredFallback: boolean;
};
export type AssistantReminderChannel = "system_notification" | "attention_fallback";

/** A point-in-time proof for Electron main; it does not pin future source state. */
export type LegacyReminderSourceIdentity = {
  schemaVersion: 1; projectId: string; revision: number;
  sourceScope: { projectId: string; instanceId: string; agentId: string };
  sourceIdentityDigest: string; authorityDigest: string;
  projectDirectory: { device: string; inode: string; birthtimeNs: string };
};
export type LegacyReminderLedgerObservation = LegacyReminderSourceIdentity & { ledgerKey: string };

export type AssistantHostOptions = {
  profileRoot: string;
  runtimeRoot: string;
  sourceRoot: string;
  pythonPath: string;
  projects: Record<string, string>;
  projectSnapshot?: AssistantProjectRegistrySnapshot;
  projectsSuspended?: boolean;
  env?: NodeJS.ProcessEnv;
  pythonArguments?: string[];
  native?: WorkbenchJobNative;
  fetch?: typeof globalThis.fetch;
  /** Main-only native lifecycle capability; deliberately absent from renderer IPC. */
  mainControl?: (request: MainControlRequest, signal?: AbortSignal) => Promise<unknown>;
  appearanceControl?: boolean;
  initialMigrationControl?: boolean;
};

type Generation = {
  id: string;
  token: string;
  directory: string;
  native: WorkbenchJobNative;
  job: WorkbenchJobHandle;
  abort: AbortController;
  origin?: string;
  sessionId?: string;
  closed: boolean;
  projectRevision: number;
  migrationRetirementRequested?: boolean;
};

class HostError extends Error {
  constructor(readonly code: string) { super(code); }
}
function object(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
function ownKeys(value: Record<string, unknown>, allowed: string[]): boolean {
  return Object.keys(value).every(key => allowed.includes(key));
}
function positiveInteger(value: unknown, max = Number.MAX_SAFE_INTEGER): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0 && value <= max;
}
function projectSnapshot(value: unknown): AssistantProjectRegistrySnapshot {
  if (!object(value) || Object.keys(value).length !== 3 || value.schemaVersion !== 1
    || !Number.isSafeInteger(value.revision) || Number(value.revision) < 0 || !object(value.projects)
    || Object.keys(value.projects).length > MAX_ASSISTANT_PROJECTS || Object.entries(value.projects).some(([id, root]) =>
      !id.trim() || id.length > 160 || typeof root !== "string" || !isAbsolute(root))) throw new HostError("ASSISTANT_REQUEST_INVALID");
  return { schemaVersion: 1, revision: Number(value.revision), projects: { ...value.projects } as Record<string, string> };
}
function projectMapKey(projects: Record<string, string>): string {
  return JSON.stringify(Object.entries(projects).sort(([a], [b]) => a.localeCompare(b)));
}
function identity(value: unknown): string {
  if (!object(value) || !object(value.assistant)
    || typeof value.assistant.agentId !== "string" || !value.assistant.agentId.trim()
    || typeof value.assistant.directSessionId !== "string" || !value.assistant.directSessionId.trim()) {
    throw new HostError("ASSISTANT_IDENTITY_INVALID");
  }
  return value.assistant.directSessionId;
}
function code(error: unknown): string {
  return error instanceof HostError ? error.code : "ASSISTANT_HOST_FAILED";
}
function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  if (signal?.aborted) return Promise.reject(new HostError("ASSISTANT_STOPPED"));
  return new Promise((done, reject) => {
    const onAbort = () => {
      clearTimeout(timer);
      signal?.removeEventListener("abort", onAbort);
      reject(new HostError("ASSISTANT_STOPPED"));
    };
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      done();
    }, ms);
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

/** Owns one independent native Job, never the Workbench's tracked-job map. */
export class AssistantHost {
  private readonly options: AssistantHostOptions;
  private current: Generation | null = null;
  private view: AssistantHostSnapshot = { state: "stopped", errorCode: null };
  private revision = 0;
  private serial: Promise<unknown> = Promise.resolve();
  private starting?: Promise<AssistantHostSnapshot>;
  private startingRevision = -1;
  private stopping?: Promise<AssistantHostSnapshot>;
  private migrationAdmission: { release: () => void; released: Promise<void>; sealed: boolean } | null = null;
  private rendererRequests = 0;
  private mainControlRequests = 0;
  private mainControlUncertain = false;
  private rendererDrainWaiters = new Set<() => void>();
  private projectSnapshot: AssistantProjectRegistrySnapshot;
  private projectsSuspended: boolean;

  constructor(options: AssistantHostOptions) {
    for (const path of [options.profileRoot, options.runtimeRoot, options.sourceRoot, options.pythonPath, ...Object.values(options.projects)]) {
      if (!isAbsolute(path)) throw new HostError("ASSISTANT_PATH_INVALID");
    }
    this.options = { ...options, projects: { ...options.projects }, env: { ...options.env },
      pythonArguments: [...(options.pythonArguments ?? ["-B", "-X", "utf8"])] };
    this.projectSnapshot = projectSnapshot(options.projectSnapshot ?? { schemaVersion: 1, revision: 0, projects: options.projects });
    this.projectsSuspended = options.projectsSuspended === true;
    if (projectMapKey(this.projectSnapshot.projects) !== projectMapKey(options.projects)) throw new HostError("ASSISTANT_REQUEST_INVALID");
  }

  snapshot(): AssistantHostSnapshot { return { ...this.view }; }

  async nextReminder(): Promise<AssistantReminder | null> {
    const generation = this.current;
    if (this.view.state !== "ready" || !generation || generation.closed || generation.abort.signal.aborted) throw new HostError("ASSISTANT_NOT_READY");
    const result = await this.rpc(generation, "/api/assistant/reminders/next", "POST", {}, REQUEST_MS, false, 8192);
    if (!object(result) || !ownKeys(result, ["schemaVersion", "event"]) || result.schemaVersion !== 1) throw new HostError("ASSISTANT_RESPONSE_INVALID");
    if (result.event === null) return null;
    const event = result.event;
    if (!object(event) || !ownKeys(event, ["id", "kind", "severity", "title", "body", "targetUrl", "attemptToken", "recoveredFallback"])
      || typeof event.id !== "string" || !/^reminder:[0-9]{8}:[a-f0-9]{64}$/.test(event.id)
      || event.kind !== "affair_reminder" || !["high", "medium"].includes(String(event.severity))
      || typeof event.title !== "string" || !event.title.trim() || event.title.length > 120
      || typeof event.body !== "string" || event.body.length > 400
      || event.targetUrl !== ""
      || typeof event.recoveredFallback !== "boolean"
      || typeof event.attemptToken !== "string" || !/^[a-f0-9]{64}$/.test(event.attemptToken)) throw new HostError("ASSISTANT_RESPONSE_INVALID");
    return event as AssistantReminder;
  }

  async settleReminder(event: AssistantReminder, channel: AssistantReminderChannel, opened: boolean): Promise<void> {
    const generation = this.current;
    if (this.view.state !== "ready" || !generation || generation.closed || generation.abort.signal.aborted) throw new HostError("ASSISTANT_NOT_READY");
    const result = await this.rpc(generation, `/api/assistant/reminders/${opened ? "opened" : "submitted"}`, "POST",
      { eventId: event.id, attemptToken: event.attemptToken, channel }, REQUEST_MS, false, 8192);
    if (!object(result) || !ownKeys(result, ["schemaVersion", "receipt"]) || result.schemaVersion !== 1
      || !object(result.receipt) || result.receipt.eventId !== event.id
      || result.receipt.state !== (opened ? "opened" : "submitted")
      || result.receipt.channel !== channel) throw new HostError("ASSISTANT_RESPONSE_INVALID");
  }

  /** Main-only: the original system notification reported failure after submission. */
  async fallbackReminder(event: AssistantReminder): Promise<void> {
    const generation = this.current;
    if (this.view.state !== "ready" || !generation || generation.closed || generation.abort.signal.aborted) throw new HostError("ASSISTANT_NOT_READY");
    const result = await this.rpc(generation, "/api/assistant/reminders/fallback", "POST",
      { eventId: event.id, attemptToken: event.attemptToken }, REQUEST_MS, false, 8192);
    if (!object(result) || !ownKeys(result, ["schemaVersion", "receipt"]) || result.schemaVersion !== 1
      || !object(result.receipt) || result.receipt.eventId !== event.id
      || result.receipt.state !== "submitted" || result.receipt.channel !== "attention_fallback") throw new HostError("ASSISTANT_RESPONSE_INVALID");
  }

  /** Main-only: sourceKey must be derived from a verified source and PA agent. */
  async resolveLegacyReminderIdentity(projectId: string, revision: number): Promise<LegacyReminderSourceIdentity> {
    return await this.resolveLegacyReminderObservation(projectId, revision, false) as LegacyReminderSourceIdentity;
  }

  /** A point-in-time digest, not a synchronous source or process proof. */
  async observeLegacyReminderLedger(projectId: string, revision: number): Promise<LegacyReminderLedgerObservation> {
    return await this.resolveLegacyReminderObservation(projectId, revision, true) as LegacyReminderLedgerObservation;
  }

  private async resolveLegacyReminderObservation(projectId: string, revision: number, ledger: boolean): Promise<LegacyReminderSourceIdentity | LegacyReminderLedgerObservation> {
    if (typeof projectId !== "string" || !/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$/.test(projectId)
      || !Number.isSafeInteger(revision) || revision < 0) throw new HostError("ASSISTANT_REQUEST_INVALID");
    const generation = this.current;
    const root = this.projectSnapshot.projects[projectId];
    const current = () => this.view.state === "ready" && this.current === generation && generation && !generation.closed
      && !generation.abort.signal.aborted && !this.projectsSuspended && generation.projectRevision === revision
      && this.projectSnapshot.revision === revision && this.projectSnapshot.projects[projectId] === root && Boolean(root);
    if (!current() || !generation) throw new HostError("ASSISTANT_NOT_READY");
    const result = await this.rpc(generation, `/api/assistant/legacy-reminders/${ledger ? "source-ledger" : "source"}`, "POST", { projectId, revision }, REQUEST_MS, false, 8192);
    if (!current()) throw new HostError("ASSISTANT_NOT_READY");
    const keys = ["schemaVersion", "projectId", "revision", "sourceScope", "sourceIdentityDigest", "authorityDigest", "projectDirectory", ...(ledger ? ["ledgerKey"] : [])];
    const opaque = (value: unknown) => typeof value === "string" && /^\S{1,160}$/.test(value);
    const decimal = (value: unknown) => typeof value === "string" && /^[1-9][0-9]{0,24}$/.test(value);
    if (!object(result) || Object.keys(result).length !== keys.length || !ownKeys(result, keys)
      || result.schemaVersion !== 1 || result.projectId !== projectId || result.revision !== revision
      || !object(result.sourceScope) || Object.keys(result.sourceScope).length !== 3
      || !ownKeys(result.sourceScope, ["projectId", "instanceId", "agentId"])
      || !opaque(result.sourceScope.projectId) || !opaque(result.sourceScope.instanceId) || !opaque(result.sourceScope.agentId)
      || typeof result.sourceIdentityDigest !== "string" || !/^[a-f0-9]{64}$/.test(result.sourceIdentityDigest)
      || typeof result.authorityDigest !== "string" || !/^[a-f0-9]{64}$/.test(result.authorityDigest)
      || (ledger && (typeof result.ledgerKey !== "string" || !/^[a-f0-9]{64}$/.test(result.ledgerKey)))
      || !object(result.projectDirectory) || Object.keys(result.projectDirectory).length !== 3
      || !ownKeys(result.projectDirectory, ["device", "inode", "birthtimeNs"])
      || !decimal(result.projectDirectory.device) || !decimal(result.projectDirectory.inode) || !decimal(result.projectDirectory.birthtimeNs))
      throw new HostError("ASSISTANT_RESPONSE_INVALID");
    return result as LegacyReminderSourceIdentity;
  }

  /** Main-only: the caller owns its registry/document admission until release drains. */
  async acquireLegacyReminderPermit(projectId: string, revision: number): Promise<Readonly<{
    ledgerKey: string; check(): Promise<void>; release(): Promise<void>;
  }>> {
    if (!/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$/.test(projectId)
      || !Number.isSafeInteger(revision) || revision < 0) throw new HostError("ASSISTANT_REQUEST_INVALID");
    const generation = this.current, root = this.projectSnapshot.projects[projectId];
    const current = () => Boolean(generation && this.current === generation && !generation.closed
      && !generation.abort.signal.aborted && this.view.state === "ready" && !this.projectsSuspended
      && generation.projectRevision === revision && this.projectSnapshot.revision === revision
      && root && this.projectSnapshot.projects[projectId] === root);
    if (!generation || !current()) throw new HostError("ASSISTANT_NOT_READY");
    const permitId = randomBytes(32).toString("hex");
    let released = false;
    // The host tombstones this exact main-generated ID even if release wins
    // the race against acquisition; a lost reply cannot leak an unknown ID.
    const release = async () => {
      if (released) throw new HostError("ASSISTANT_REQUEST_INVALID");
      released = true;
      while (true) {
        try {
          const result = await this.rpc(generation, "/api/assistant/legacy-reminders/permit/release", "POST", { permitId }, 5_000, true, 8192);
          if (object(result) && ownKeys(result, ["schemaVersion", "released"]) && Object.keys(result).length === 2
            && result.schemaVersion === 1 && result.released === true) return;
        } catch { /* A missing acknowledgement does not prove release. */ }
        try {
          if (generation.native.activeCount(generation.job) === 0 && generation.native.drainStatus(generation.job).complete
            && typeof generation.native.exitCode === "function" && generation.native.exitCode(generation.job) !== null) return;
        } catch { /* Retain the exact Job until its exit and output are certain. */ }
        await sleep(1000);
      }
    };
    const valid = (result: unknown, acquired: boolean, key?: string): result is Record<string, unknown> => {
      const keys = ["schemaVersion", "ledgerKey", "coverage", "unmanagedSenders", "readyForCutover", ...(acquired ? ["permitId"] : [])];
      return object(result) && Object.keys(result).length === keys.length && ownKeys(result, keys)
        && result.schemaVersion === 1 && typeof result.ledgerKey === "string" && /^[a-f0-9]{64}$/.test(result.ledgerKey)
        && (!key || result.ledgerKey === key) && (!acquired || result.permitId === permitId)
        && result.coverage === "cooperating_route_writers" && result.unmanagedSenders === "unknown" && result.readyForCutover === false;
    };
    try {
      const result = await this.rpc(generation, "/api/assistant/legacy-reminders/permit/acquire", "POST",
        { projectId, revision, permitId }, REQUEST_MS, false, 8192);
      if (!current() || !valid(result, true)) throw new HostError("ASSISTANT_RESPONSE_INVALID");
      const ledgerKey = result.ledgerKey as string;
      const check = async () => {
        if (released || !current()) throw new HostError("ASSISTANT_NOT_READY");
        const result = await this.rpc(generation, "/api/assistant/legacy-reminders/permit/check", "POST", { permitId }, REQUEST_MS, false, 8192);
        if (released || !current() || !valid(result, false, ledgerKey)) throw new HostError("ASSISTANT_RESPONSE_INVALID");
      };
      await check();
      return Object.freeze({ ledgerKey, check, release });
    } catch (error) {
      await release();
      throw error;
    }
  }

  /** Main-only: sourceKey must be derived from a verified source and PA agent. */
  async reserveLegacyReminder(request: { sourceKey: string; eventId: string }): Promise<unknown> {
    return await this.legacyReminderRpc("reserve", request);
  }

  /** Main-only read of the same native-authorized handoff ID. */
  async reminderHandoffReceipt(projectId: string, revision: number): Promise<"pending" | "unknown"> {
    const generation = this.current;
    const root = this.projectSnapshot.projects[projectId];
    const current = () => this.view.state === "ready" && this.current === generation && generation && !generation.closed
      && !generation.abort.signal.aborted && !this.projectsSuspended && generation.projectRevision === revision
      && this.projectSnapshot.revision === revision && this.projectSnapshot.projects[projectId] === root && Boolean(root);
    if (!current() || !generation || !Number.isSafeInteger(revision) || revision < 0) throw new HostError("ASSISTANT_NOT_READY");
    const result = await this.rpc(generation, "/api/assistant/legacy-reminders/handoff-receipt", "POST",
      { projectId, revision }, REQUEST_MS, false, 8192);
    const digest = createHash("sha256").update(`${projectId}:reminder_handoff`).digest("hex").slice(0, 40);
    if (!current() || !object(result) || result.schemaVersion !== 1 || result.projectId !== projectId
      || result.operationId !== `initial-${digest}` || result.syncId !== `affairs-${digest}` || result.readyForCutover !== false
      || !((result.state === "unknown" && result.code === "unknown" && Object.keys(result).length === 7)
        || (result.state === "pending" && result.code === "source_proof_unavailable" && result.baselineState === "unknown"
          && Object.keys(result).length === 8))) throw new HostError("ASSISTANT_RESPONSE_INVALID");
    return result.state as "pending" | "unknown";
  }

  /** Trusted, revalidated identity for one original pending handoff. */
  async reminderHandoffSource(projectId: string, revision: number): Promise<{ operationId: string; syncId: string;
    sourceScope: { projectId: string; instanceId: string; agentId: string }; sourceIdentityDigest: string; registryDigest: string }> {
    const generation = this.current, root = this.projectSnapshot.projects[projectId];
    const current = () => this.view.state === "ready" && this.current === generation && generation && !generation.closed
      && !generation.abort.signal.aborted && !this.projectsSuspended && generation.projectRevision === revision
      && this.projectSnapshot.revision === revision && this.projectSnapshot.projects[projectId] === root && Boolean(root);
    if (!current() || !generation || !Number.isSafeInteger(revision) || revision < 0) throw new HostError("ASSISTANT_NOT_READY");
    const result = await this.rpc(generation, "/api/assistant/legacy-reminders/handoff-source", "POST",
      { projectId, revision }, REQUEST_MS, false, 8192);
    const digest = createHash("sha256").update(`${projectId}:reminder_handoff`).digest("hex").slice(0, 40);
    const keys = ["schemaVersion", "registeredProjectId", "sourceScope", "category", "turnId", "operationId", "syncId", "revision",
      "sourceIdentityDigest", "registryDigest", "targetIdentityDigest", "projectDirectory", "workspaceDirectory", "targetDirectory",
      "targetAgentId", "targetSessionId", "authority", "baselineId", "baselineState", "readyForCutover"];
    const opaque = (value: unknown) => typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$/.test(value);
    const identity = (value: unknown) => object(value) && Object.keys(value).length === 3
      && ["device", "inode", "birthtimeNs"].every(key => typeof value[key] === "string" && /^[1-9][0-9]{0,24}$/.test(value[key] as string));
    if (!current() || !object(result) || Object.keys(result).length !== keys.length || !ownKeys(result, keys)
      || result.schemaVersion !== 1 || result.registeredProjectId !== projectId || result.category !== "reminder_handoff"
      || result.operationId !== `initial-${digest}` || result.syncId !== `affairs-${digest}`
      || result.authority !== "native_policy_admitted" || result.baselineId !== null || result.baselineState !== "unknown"
      || result.readyForCutover !== false || !Number.isSafeInteger(result.revision) || !opaque(result.turnId)
      || !object(result.sourceScope) || Object.keys(result.sourceScope).length !== 3
      || !["projectId", "instanceId", "agentId"].every(key => opaque((result.sourceScope as Record<string, unknown>)[key]))
      || !["sourceIdentityDigest", "registryDigest", "targetIdentityDigest"].every(key => typeof result[key] === "string" && /^[a-f0-9]{64}$/.test(result[key] as string))
      || !identity(result.projectDirectory) || !identity(result.workspaceDirectory) || !identity(result.targetDirectory)
      || !opaque(result.targetAgentId) || !opaque(result.targetSessionId)) throw new HostError("ASSISTANT_RESPONSE_INVALID");
    return { operationId: result.operationId as string, syncId: result.syncId as string,
      sourceScope: result.sourceScope as { projectId: string; instanceId: string; agentId: string },
      sourceIdentityDigest: result.sourceIdentityDigest as string, registryDigest: result.registryDigest as string };
  }

  /** Main-only: the attempt token must never cross the renderer bridge. */
  async settleLegacyReminder(request: { sourceKey: string; eventId: string; attemptToken: string;
    channel: "assistant_window" | "system_notification" | "attention_fallback" }): Promise<unknown> {
    return await this.legacyReminderRpc("settle", request);
  }

  /** Main-only; call after the dispatch has stopped, never to authorize retry. */
  async abandonLegacyReminder(request: { sourceKey: string; eventId: string; attemptToken: string }): Promise<unknown> {
    return await this.legacyReminderRpc("abandon", request);
  }

  /** Private main-only full inventory. Main holds its cross-writer guard across this RPC. */
  async inventoryLegacyReminders(): Promise<unknown> {
    const generation = this.current;
    if (this.view.state !== "ready" || !generation || generation.closed || generation.abort.signal.aborted)
      throw new HostError("ASSISTANT_NOT_READY");
    const result = await this.rpc(generation, "/api/assistant/legacy-reminders/inventory", "POST", {}, REQUEST_MS, false, MAX_RESPONSE_BYTES);
    if (this.current !== generation || generation.closed || generation.abort.signal.aborted || this.view.state !== "ready")
      throw new HostError("ASSISTANT_NOT_READY");
    if (!object(result) || Object.keys(result).length !== 3 || !ownKeys(result, ["schemaVersion", "records", "senders"])
        || result.schemaVersion !== 1 || !Array.isArray(result.records) || result.records.length > 20000
        || !Number.isSafeInteger(result.senders) || (result.senders as number) < 0 || (result.senders as number) > 20000)
      throw new HostError("ASSISTANT_RESPONSE_INVALID");
    for (const row of result.records) {
      if (!object(row) || Object.keys(row).length !== 5 || !ownKeys(row, ["day", "eventKey", "state", "channel", "inflight"])
          || typeof row.day !== "string" || !/^[0-9]{8}$/.test(row.day)
          || typeof row.eventKey !== "string" || !/^legacy:[a-f0-9]{64}$/.test(row.eventKey)
          || typeof row.inflight !== "boolean" || !["pending", "submitted", "opened"].includes(String(row.state))
          || (row.state === "pending" ? row.channel !== null
            : !["assistant_window", "system_notification", "attention_fallback"].includes(String(row.channel))))
        throw new HostError("ASSISTANT_RESPONSE_INVALID");
    }
    return result;
  }

  private async legacyReminderRpc(operation: "reserve" | "settle" | "abandon", request: { sourceKey: string; eventId: string;
    attemptToken?: string; channel?: string }): Promise<unknown> {
    if (!/^[a-f0-9]{64}$/.test(request.sourceKey) || typeof request.eventId !== "string" || request.eventId.length > 128
      || !/^affair-reminder:[A-Za-z0-9._:-]{1,103}:[0-9]{8}$/.test(request.eventId)
      || (operation === "reserve" && (request.attemptToken !== undefined || request.channel !== undefined))
      || (operation === "abandon" && (!/^[a-f0-9]{64}$/.test(request.attemptToken ?? "") || request.channel !== undefined))
      || (operation === "settle" && (!/^[a-f0-9]{64}$/.test(request.attemptToken ?? "")
        || !["assistant_window", "system_notification", "attention_fallback"].includes(request.channel ?? ""))))
      throw new HostError("ASSISTANT_REQUEST_INVALID");
    const generation = this.current;
    if (this.view.state !== "ready" || !generation || generation.closed || generation.abort.signal.aborted) throw new HostError("ASSISTANT_NOT_READY");
    const body = operation === "reserve" ? { sourceKey: request.sourceKey, eventId: request.eventId }
      : operation === "abandon" ? { sourceKey: request.sourceKey, eventId: request.eventId, attemptToken: request.attemptToken }
      : { sourceKey: request.sourceKey, eventId: request.eventId, attemptToken: request.attemptToken, channel: request.channel };
    const result = await this.rpc(generation, `/api/assistant/legacy-reminders/${operation}`, "POST", body, REQUEST_MS, false, 8192);
    const key = "legacy:" + createHash("sha256").update(JSON.stringify([request.sourceKey, request.eventId]), "ascii").digest("hex");
    if (!object(result) || result.schemaVersion !== 1 || result.eventKey !== key
      || (operation === "abandon" && (Object.keys(result).length !== 3 || !ownKeys(result, ["schemaVersion", "eventKey", "state"])
        || result.state !== "abandoned"))
      || (operation === "settle" && (Object.keys(result).length !== 4 || !ownKeys(result, ["schemaVersion", "eventKey", "state", "channel"])
        || result.state !== "submitted" || result.channel !== request.channel))
      || (operation === "reserve" && !(result.state === "reserved" && Object.keys(result).length === 4
          && ownKeys(result, ["schemaVersion", "eventKey", "state", "attemptToken"]) && typeof result.attemptToken === "string"
          && /^[a-f0-9]{64}$/.test(result.attemptToken)
        || result.state === "pending" && Object.keys(result).length === 3 && ownKeys(result, ["schemaVersion", "eventKey", "state"])
        || result.state === "submitted" && Object.keys(result).length === 4 && ownKeys(result, ["schemaVersion", "eventKey", "state", "channel"])
          && ["assistant_window", "system_notification", "attention_fallback"].includes(String(result.channel)))))
      throw new HostError("ASSISTANT_RESPONSE_INVALID");
    return result;
  }

  /** Main-only; this operation is never admitted through renderer request(). */
  updateProjects(snapshot: AssistantProjectRegistrySnapshot): Promise<void> {
    let desired: AssistantProjectRegistrySnapshot;
    try { desired = projectSnapshot(snapshot); }
    catch { return Promise.reject(new HostError("ASSISTANT_REQUEST_INVALID")); }
    if (desired.revision < this.projectSnapshot.revision) return Promise.reject(new HostError("ASSISTANT_REGISTRY_STALE"));
    if (desired.revision === this.projectSnapshot.revision && projectMapKey(desired.projects) !== projectMapKey(this.projectSnapshot.projects)) {
      return Promise.reject(new HostError("ASSISTANT_REGISTRY_CONFLICT"));
    }
    // A future generation must start with the latest main-owned authorization,
    // including when the live update has an unknown response and is retired.
    this.projectSnapshot = desired;
    const operation = this.serial.then(async () => {
      const generation = this.current;
      try {
        if (this.view.state !== "ready" || !generation || generation.closed) throw new HostError("ASSISTANT_NOT_READY");
        const result = await this.rpc(generation, "/api/assistant/project-registry", "PUT", desired);
        if (this.current !== generation || generation.closed || generation.abort.signal.aborted
          || !object(result) || result.schemaVersion !== 1 || result.revision !== desired.revision
          || result.projectCount !== Object.keys(desired.projects).length) throw new HostError("ASSISTANT_REGISTRY_INVALID");
        generation.projectRevision = desired.revision;
        this.projectsSuspended = false;
      } catch {
        // Unknown revocation is not permission to retain a privileged old view.
        // Retire only this owned host; remote native tasks are never cancelled.
        await this.rejectProjectConfirmation(generation);
      }
    });
    this.serial = operation.catch(() => undefined);
    return operation;
  }

  /** Main-only fail-closed gate; never changes the persisted project table. */
  suspendProjects(): Promise<void> {
    // Preserve the gate even if this acknowledgement is lost and start retries.
    this.projectsSuspended = true;
    const operation = this.serial.then(async () => {
      this.projectsSuspended = true;
      const generation = this.current;
      try {
        if (this.view.state !== "ready" || !generation || generation.closed) throw new HostError("ASSISTANT_NOT_READY");
        const result = await this.rpc(generation, "/api/assistant/project-registry/suspend", "POST", {});
        if (this.current !== generation || generation.closed || generation.abort.signal.aborted
          || !object(result) || Object.keys(result).length !== 3
          || !ownKeys(result, ["schemaVersion", "revision", "projectsSuspended"])
          || result.schemaVersion !== 1 || result.revision !== generation.projectRevision
          || result.projectsSuspended !== true) throw new HostError("ASSISTANT_REGISTRY_INVALID");
      } catch { await this.rejectProjectConfirmation(generation); }
    });
    this.serial = operation.catch(() => undefined);
    return operation;
  }

  private async rejectProjectConfirmation(generation: Generation | null): Promise<never> {
    try { if (generation && !generation.closed) await this.retire(generation, true); }
    catch { /* Retain an unclosed owned Job so stop() can retry its retirement. */ }
    finally {
      if (generation?.closed && this.current === generation) this.current = null;
      this.view = { state: "failed", errorCode: "ASSISTANT_REGISTRY_UNCONFIRMED" };
    }
    throw new HostError("ASSISTANT_REGISTRY_UNCONFIRMED");
  }

  start(): Promise<AssistantHostSnapshot> {
    if (this.migrationAdmission) {
      if (!this.migrationAdmission.sealed && this.view.state === "ready" && this.current && !this.current.abort.signal.aborted)
        return Promise.resolve(this.snapshot());
      return this.migrationAdmission.released.then(() => this.start());
    }
    return this.startOwned(false);
  }

  /** Registry-only startup while renderer admission remains fenced. */
  startForMigration(): Promise<AssistantHostSnapshot> {
    return this.startOwned(true);
  }

  private startOwned(migration: boolean): Promise<AssistantHostSnapshot> {
    if (this.starting && this.startingRevision === this.revision) return this.starting;
    const revision = this.revision;
    const operation = this.serial.then(() => this.startGeneration(revision, migration));
    this.serial = operation.catch(() => undefined);
    this.starting = operation;
    this.startingRevision = revision;
    void operation.finally(() => { if (this.starting === operation) this.starting = undefined; }).catch(() => undefined);
    return operation;
  }

  stop(): Promise<AssistantHostSnapshot> {
    if (this.stopping) return this.stopping;
    this.revision += 1;
    this.current?.abort.abort();
    const operation = this.serial.then(async () => {
      this.view = { state: "stopping", errorCode: null };
      const generation = this.current;
      try {
        if (generation?.migrationRetirementRequested) {
          if (!this.finishMigrationRetirement(generation)) throw new HostError("ASSISTANT_DRAIN_PENDING");
        } else if (generation) await this.retire(generation, true);
        this.view = { state: "stopped", errorCode: null };
      } catch (error) {
        this.view = { state: "failed", errorCode: code(error) };
        throw new HostError(code(error));
      } finally {
        if (this.current === generation && generation?.closed) this.current = null;
      }
      return this.snapshot();
    });
    this.serial = operation.catch(() => undefined);
    this.stopping = operation;
    void operation.finally(() => { if (this.stopping === operation) this.stopping = undefined; }).catch(() => undefined);
    return operation;
  }

  /**
   * Main-only: caller must retain every producer and native-session fence from
   * before this call until the captured Job has exited and output has drained.
   * A missing acknowledgement or incomplete drain retains the same Job and is
   * reported as pending. Never terminate, close, or respawn it in this path.
   */
  retireForMigration(): Promise<boolean> {
    const operation = this.serial.then(async () => {
      const generation = this.current;
      if (!generation || generation.closed) return false;
      if (!generation.migrationRetirementRequested) {
        if (!this.migrationAdmission?.sealed || this.view.state !== "ready" || !generation.origin
          || generation.abort.signal.aborted || this.mainControlUncertain) return false;
        try {
          const proof = await this.rpc(generation, "/api/assistant/migration-barrier/status", "GET", undefined, REQUEST_MS, false, 8192);
          if (!object(proof) || Object.keys(proof).length !== 2 || proof.schemaVersion !== 1 || proof.state !== "ready") return false;
        } catch { return false; }
        if (this.mainControlUncertain) return false;
        generation.migrationRetirementRequested = true;
        this.view = { state: "stopping", errorCode: null };
        generation.abort.abort();
        try { await this.rpc(generation, "/api/assistant/shutdown", "POST", {}, 2_000, true); }
        catch { /* A lost reply is ambiguous; retain and observe the same Job. */ }
      }
      return this.finishMigrationRetirement(generation);
    });
    this.serial = operation.catch(() => undefined);
    return operation;
  }

  private finishMigrationRetirement(generation: Generation): boolean {
    try {
      if (generation.native.activeCount(generation.job) !== 0
        || typeof generation.native.exitCode !== "function" || generation.native.exitCode(generation.job) === null
        || !generation.native.drainStatus(generation.job).complete) return false;
      generation.native.close(generation.job);
      generation.closed = true;
      generation.token = "";
      if (this.current === generation) this.current = null;
      this.view = { state: "stopped", errorCode: null };
      return true;
    } catch { return false; }
  }

  /** Rebind the same window-facing host to the latest validated registry. */
  prepareForMigrationRestart(snapshot: AssistantProjectRegistrySnapshot, projectsSuspended: boolean): void {
    if (this.current?.migrationRetirementRequested && !this.finishMigrationRetirement(this.current))
      throw new HostError("ASSISTANT_DRAIN_PENDING");
    if (!this.migrationAdmission || this.current || !["stopped", "failed"].includes(this.view.state) || typeof projectsSuspended !== "boolean")
      throw new HostError("ASSISTANT_NOT_READY");
    this.projectSnapshot = projectSnapshot(snapshot);
    this.projectsSuspended = projectsSuspended;
  }

  /** Caller owns the external producer fences throughout this private probe. */
  async migrationBarrier(operation: "prepare" | "status" | "release"): Promise<"idle" | "probing" | "ready" | "busy" | "released"> {
    const generation = this.current;
    if (!this.migrationAdmission?.sealed || !generation || generation.closed || generation.abort.signal.aborted
        || this.view.state !== "ready" || (this.mainControlUncertain && operation !== "release")) throw new HostError("ASSISTANT_NOT_READY");
    const result = await this.rpc(generation, `/api/assistant/migration-barrier/${operation}`,
      operation === "status" ? "GET" : "POST", operation === "status" ? undefined : {}, REQUEST_MS, false, 8192);
    if (!object(result) || Object.keys(result).length !== 2 || result.schemaVersion !== 1
      || !["idle", "probing", "ready", "busy", "released"].includes(String(result.state)))
      throw new HostError("ASSISTANT_RESPONSE_INVALID");
    return result.state as "idle" | "probing" | "ready" | "busy" | "released";
  }

  /**
   * Fence renderer commands before starting the larger migration barrier.
   * Requests already sent are drained without replay. Requests arriving after
   * the fence retain their original payload until release and have not yet
   * reached the native Session. This is not proof that other producers drained.
   */
  beginMigrationAdmission(): { drained: Promise<void>; seal: () => Promise<void>; release: () => void } {
    if (this.migrationAdmission || this.mainControlUncertain) throw new HostError("ASSISTANT_MIGRATION_BUSY");
    let resolve!: () => void;
    const released = new Promise<void>(done => { resolve = done; });
    const admission = { released, sealed: false, release: () => {
      if (this.migrationAdmission !== admission) return;
      this.migrationAdmission = null;
      resolve();
    } };
    this.migrationAdmission = admission;
    const drain = () => this.rendererRequests === 0 && this.mainControlRequests === 0
      ? Promise.resolve() : new Promise<void>(done => this.rendererDrainWaiters.add(done));
    return { drained: drain(), seal: () => {
      if (this.migrationAdmission !== admission) return Promise.reject(new HostError("ASSISTANT_MIGRATION_BUSY"));
      admission.sealed = true;
      return drain();
    }, release: admission.release };
  }

  async request(payload: AssistantHostRequest): Promise<unknown> {
    // Capture the exact request before waiting. Only admission failures are
    // delayed; an uncertain native response is never automatically retried.
    const captured = structuredClone(payload);
    while (this.migrationAdmission) {
      const admission = this.migrationAdmission;
      const safeWhileWaiting = ["status", "detail", "dispatches", "config", "approvals", "curation", "operatorAsset", "resolveApproval", "stop", "computerState"]
        .includes(captured.operation);
      // Confirmation only settles an existing native waiter; it remains a
      // counted writer in the host barrier even after admission is sealed.
      if (captured.operation === "computerConfirm" || captured.operation === "computerState"
        || (!admission.sealed && safeWhileWaiting)) break;
      await admission.released;
    }
    this.rendererRequests += 1;
    try { return await this.requestNow(captured); }
    finally {
      this.rendererRequests -= 1;
      this.settleMigrationAdmissionDrain();
    }
  }

  private settleMigrationAdmissionDrain(): void {
    if (this.rendererRequests !== 0 || this.mainControlRequests !== 0) return;
    for (const done of this.rendererDrainWaiters) done();
    this.rendererDrainWaiters.clear();
  }

  private async requestNow(payload: AssistantHostRequest): Promise<unknown> {
    const generation = this.current;
    if (this.view.state !== "ready" || !generation || generation.closed || generation.abort.signal.aborted) {
      throw new HostError("ASSISTANT_NOT_READY");
    }
    if (!object(payload)) throw new HostError("ASSISTANT_REQUEST_INVALID");
    switch (payload.operation) {
      case "status":
      case "detail":
      case "dispatches":
      case "approvals":
      case "config": {
        if (!ownKeys(payload, ["operation"])) throw new HostError("ASSISTANT_REQUEST_INVALID");
        const paths = { status: "/api/assistant", detail: "/api/assistant/session", dispatches: "/api/assistant/dispatches", config: "/api/assistant/config", approvals: "/api/assistant/approvals" };
        const result = await this.rpc(generation, paths[payload.operation], "GET");
        if (payload.operation === "status" && identity(result) !== generation.sessionId) throw new HostError("ASSISTANT_IDENTITY_INVALID");
        if (payload.operation === "detail" && (!object(result) || result.id !== generation.sessionId)) throw new HostError("ASSISTANT_IDENTITY_INVALID");
        return result;
      }
      case "resolveApproval":
        if (!ownKeys(payload, ["operation", "requestId", "decision"])
          || typeof payload.requestId !== "string" || !/^[A-Za-z0-9_.:-]{1,160}$/.test(payload.requestId)
          || !["accept", "decline"].includes(payload.decision)) throw new HostError("ASSISTANT_REQUEST_INVALID");
        return await this.rpc(generation, "/api/assistant/approvals/decision", "POST",
          { requestId: payload.requestId, decision: payload.decision });
      case "operatorAsset":
        if (!ownKeys(payload, ["operation", "kind"]) || !["avatar", "background"].includes(payload.kind)) throw new HostError("ASSISTANT_REQUEST_INVALID");
        // Native backgrounds allow 10 MiB; base64 fits this operation's 16 MiB
        // envelope without widening ordinary JSON or main-control budgets.
        return await this.rpc(generation, `/api/assistant/operator-assets/${payload.kind}`, "GET", undefined, REQUEST_MS, false, 16 * 1024 * 1024);
      case "computerState":
      case "computerWindows":
      case "computerGrant":
      case "computerControl":
      case "computerConfirm": {
        const token = (value: unknown): value is string => typeof value === "string" && value.length > 0 && value.length <= 100;
        const exact = (value: Record<string, unknown>, keys: string[]) => Object.keys(value).length === keys.length && ownKeys(value, keys);
        let path = "/api/assistant/computer", method: "GET" | "POST" = "POST", body: object | undefined;
        if (payload.operation === "computerState" || payload.operation === "computerWindows") {
          if (!exact(payload, ["operation"])) throw new HostError("ASSISTANT_REQUEST_INVALID");
          if (payload.operation === "computerState") method = "GET";
          else { path += "/windows"; body = {}; }
        } else if (payload.operation === "computerGrant") {
          if (!exact(payload, ["operation", "selectionId", "allowVision"]) || !token(payload.selectionId) || payload.allowVision !== true)
            throw new HostError("ASSISTANT_REQUEST_INVALID");
          path += "/grant"; body = { selectionId: payload.selectionId, allowVision: true };
        } else if (payload.operation === "computerControl") {
          if (!exact(payload, ["operation", "grantId", "action"]) || !token(payload.grantId)
            || !["pause", "resume", "takeover", "return", "end"].includes(payload.action)) throw new HostError("ASSISTANT_REQUEST_INVALID");
          path += "/control"; body = { grantId: payload.grantId, action: payload.action };
        } else {
          if (!exact(payload, ["operation", "grantId", "pendingId", "approved"]) || !token(payload.grantId)
            || !token(payload.pendingId) || typeof payload.approved !== "boolean") throw new HostError("ASSISTANT_REQUEST_INVALID");
          path += "/confirm"; body = { grantId: payload.grantId, pendingId: payload.pendingId, approved: payload.approved };
        }
        const result = await this.rpc(generation, path, method, body, REQUEST_MS, false, 1024 * 1024);
        const bounded = (value: unknown, max: number): value is string => typeof value === "string" && value.length <= max;
        const validWindow = (value: unknown): boolean => object(value) && exact(value, ["selectionId", "title", "appName"])
          && token(value.selectionId) && bounded(value.title, 240) && bounded(value.appName, 80);
        if (payload.operation === "computerWindows") {
          if (!object(result) || !exact(result, ["windows"]) || !Array.isArray(result.windows)
            || result.windows.length > 256 || !result.windows.every(validWindow)) throw new HostError("ASSISTANT_RESPONSE_INVALID");
          return result;
        }
        if (!object(result) || !exact(result, ["available", "status", "message", "grantId", "window", "pending"])
          || typeof result.available !== "boolean" || typeof result.status !== "string"
          || !["idle", "ready", "working", "waiting_confirmation", "paused", "manual", "ended", "error"].includes(result.status)
          || !bounded(result.message, 2000) || !(result.grantId === null || token(result.grantId))
          || !(result.window === null || validWindow(result.window)) || (result.grantId === null) !== (result.window === null))
          throw new HostError("ASSISTANT_RESPONSE_INVALID");
        if (result.pending !== null && (!object(result.pending) || !exact(result.pending, ["id", "action", "targetLabel", "text"])
          || !token(result.pending.id) || typeof result.pending.action !== "string"
          || !["click", "set_value", "type_text", "scroll"].includes(result.pending.action)
          || !bounded(result.pending.targetLabel, 400) || !(result.pending.text === null || bounded(result.pending.text, 2000))
          || result.grantId === null || result.status !== "waiting_confirmation")) throw new HostError("ASSISTANT_RESPONSE_INVALID");
        return result;
      }
      case "send":
        if (!ownKeys(payload, ["operation", "message", "requestId"])
          || typeof payload.message !== "string" || !payload.message.trim() || payload.message.length > 64_000
          || typeof payload.requestId !== "string" || !/^[A-Za-z0-9_.:-]{1,128}$/.test(payload.requestId)) throw new HostError("ASSISTANT_REQUEST_INVALID");
        return await this.rpc(generation, "/api/assistant/messages", "POST", { message: payload.message, requestId: payload.requestId });
      case "stop":
        if (!ownKeys(payload, ["operation", "turnId"]) || typeof payload.turnId !== "string"
          || !payload.turnId.trim() || payload.turnId.length > 160) throw new HostError("ASSISTANT_REQUEST_INVALID");
        return await this.rpc(generation, "/api/assistant/stop", "POST", { turnId: payload.turnId });
      case "continue": {
        const expected = payload.continuation;
        if (!ownKeys(payload, ["operation", "requestId", "continuation"])
          || typeof payload.requestId !== "string" || !/^[A-Za-z0-9_.:-]{1,128}$/.test(payload.requestId)
          || !object(expected) || Object.keys(expected).length !== 4 || !ownKeys(expected, ["turnId", "headId", "ledgerSeq", "agentId"])
          || ![expected.turnId, expected.headId, expected.agentId].every(value => typeof value === "string" && value.trim() && value.length <= 200)
          || expected.turnId.length > 160 || expected.agentId.length > 160
          || !positiveInteger(expected.ledgerSeq)) throw new HostError("ASSISTANT_REQUEST_INVALID");
        return await this.rpc(generation, "/api/assistant/continue", "POST", { requestId: payload.requestId, continuation: expected });
      }
      case "curation":
      case "curate":
        if (payload.sessionId !== generation.sessionId) throw new HostError("ASSISTANT_SESSION_FORBIDDEN");
        if (payload.operation === "curation") {
          if (!ownKeys(payload, ["operation", "sessionId"])) throw new HostError("ASSISTANT_REQUEST_INVALID");
          return await this.rpc(generation, "/api/assistant/curation", "GET");
        }
        if (!ownKeys(payload, ["operation", "sessionId", "messageId", "action"])
          || typeof payload.messageId !== "string" || !payload.messageId.trim() || payload.messageId.length > 160
          || !["include", "exclude"].includes(payload.action)) throw new HostError("ASSISTANT_REQUEST_INVALID");
        return await this.rpc(generation, "/api/assistant/curation", "POST", { messageId: payload.messageId, action: payload.action });
      default:
        throw new HostError("ASSISTANT_REQUEST_INVALID");
    }
  }

  private async startGeneration(revision: number, migration = false): Promise<AssistantHostSnapshot> {
    if (revision !== this.revision) throw new HostError("ASSISTANT_STOPPED");
    const previous = this.current;
    if (previous && !previous.closed) {
      if (previous.migrationRetirementRequested) throw new HostError("ASSISTANT_JOB_STILL_OWNED");
      let active: number;
      try { active = previous.native.activeCount(previous.job); }
      catch {
        this.view = { state: "failed", errorCode: "ASSISTANT_JOB_INSPECTION_FAILED" };
        throw new HostError("ASSISTANT_JOB_INSPECTION_FAILED");
      }
      if (active !== 0) {
        // An unresponsive host with an active owner is not evidence permitting restart.
        if (this.view.state === "ready" && !previous.abort.signal.aborted) return this.snapshot();
        throw new HostError("ASSISTANT_JOB_STILL_OWNED");
      }
      this.view = { state: "starting", errorCode: null };
      try { await this.retire(previous, false); }
      catch (error) {
        this.view = { state: "failed", errorCode: code(error) };
        throw new HostError(code(error));
      } finally {
        if (this.current === previous && previous.closed) this.current = null;
      }
      // stop() may have invalidated this recovery while the old stdio drained.
      if (revision !== this.revision) throw new HostError("ASSISTANT_STOPPED");
    }
    this.view = { state: "starting", errorCode: null };
    let generation: Generation | undefined;
    try {
      const native = this.options.native ?? loadWorkbenchJobNative();
      const python = resolveNoConsolePython(this.options.pythonPath);
      if (!python.toLowerCase().endsWith("pythonw.exe") || !existsSync(python)) throw new HostError("ASSISTANT_PYTHONW_REQUIRED");
      const id = randomUUID();
      const token = randomBytes(32).toString("hex");
      const directory = join(resolve(this.options.runtimeRoot), id);
      mkdirSync(this.options.profileRoot, { recursive: true, mode: 0o700 });
      mkdirSync(this.options.runtimeRoot, { recursive: true, mode: 0o700 });
      mkdirSync(directory, { mode: 0o700 });
      const manifest = join(directory, "projects.json");
      writeFileSync(manifest, JSON.stringify(this.projectSnapshot), { encoding: "utf8", mode: 0o600, flag: "wx" });
      const environment: NodeJS.ProcessEnv = { ...process.env, ...this.options.env,
        VIBELUTION_ASSISTANT_TOKEN: token, PYTHONUTF8: "1", PYTHONUNBUFFERED: "1" };
      // A project-bound primary process can own this independent host too. Sanitize
      // after merging so omitted options cannot reintroduce inherited bindings.
      const excluded = new Set(["VIBELUTION_WORKSPACE_ROOT", "VIBELUTION_PYTHON_PATH", "PYTHON"]);
      if (this.options.pythonArguments?.includes("-I")) {
        excluded.add("PYTHONPATH");
        excluded.add("PYTHONHOME");
      }
      for (const key of Object.keys(environment)) {
        if (excluded.has(key.toUpperCase()) || key.toUpperCase() === "VIBELUTION_ASSISTANT_MAIN_CONTROL") delete environment[key];
      }
      for (const key of Object.keys(environment)) if (key.toUpperCase() === "VIBELUTION_ASSISTANT_APPEARANCE_CONTROL") delete environment[key];
      for (const key of Object.keys(environment)) if (key.toUpperCase() === "VIBELUTION_ASSISTANT_INITIAL_MIGRATION_CONTROL") delete environment[key];
      if (this.options.mainControl) environment.VIBELUTION_ASSISTANT_MAIN_CONTROL = "1";
      if (this.options.mainControl && this.options.appearanceControl) environment.VIBELUTION_ASSISTANT_APPEARANCE_CONTROL = "1";
      if (this.options.mainControl && this.options.initialMigrationControl) environment.VIBELUTION_ASSISTANT_INITIAL_MIGRATION_CONTROL = "1";
      const spawned = native.spawn({
        executable: python,
        arguments: [...this.options.pythonArguments!, join(this.options.sourceRoot, "scripts", "assistant_host.py"), "--profile-root", this.options.profileRoot,
          "--runtime-dir", directory, "--instance-id", id, "--projects-file", manifest,
          ...(this.projectsSuspended ? ["--projects-suspended"] : [])],
        cwd: this.options.profileRoot,
        env: environment,
        stdoutPath: join(directory, "stdout.log"), stderrPath: join(directory, "stderr.log"),
        containDescendants: true, maxLogBytes: MAX_LOG_BYTES,
      });
      generation = { id, token, directory, native, job: spawned.job, abort: new AbortController(), closed: false,
        projectRevision: this.projectSnapshot.revision };
      this.current = generation;
      if (!positiveInteger(spawned.pid)) throw new HostError("ASSISTANT_SPAWN_INVALID");
      const deadline = Date.now() + STARTUP_MS;
      while (Date.now() < deadline) {
        if (revision !== this.revision || generation.abort.signal.aborted) throw new HostError("ASSISTANT_STOPPED");
        if (native.activeCount(generation.job) === 0) throw new HostError("ASSISTANT_EXITED");
        const ready = this.readReady(generation);
        if (ready) {
          generation.origin = `http://127.0.0.1:${ready.port}`;
          try {
            const timeout = Math.max(1, Math.min(2_000, deadline - Date.now()));
            const health = await this.rpc(generation, "/health", "GET", undefined, timeout);
            if (!object(health) || health.status !== "ok" || health.role !== "launcher_assistant" || health.protocolVersion !== 1) throw new HostError("ASSISTANT_HEALTH_INVALID");
            if (this.options.mainControl && health.mainControlVersion !== 1) throw new HostError("ASSISTANT_MAIN_CONTROL_UNAVAILABLE");
            if (this.options.appearanceControl && health.appearanceControlVersion !== 1) throw new HostError("ASSISTANT_APPEARANCE_CONTROL_UNAVAILABLE");
            if (this.options.initialMigrationControl && health.initialMigrationControlVersion !== 1) throw new HostError("ASSISTANT_INITIAL_MIGRATION_UNAVAILABLE");
            const status = await this.rpc(generation, "/api/assistant", "GET", undefined, Math.max(1, deadline - Date.now()));
            generation.sessionId = identity(status);
            if (revision !== this.revision || generation.abort.signal.aborted) throw new HostError("ASSISTANT_STOPPED");
            this.view = { state: "ready", errorCode: null };
            if (this.options.mainControl) this.startMainControl(generation);
            return this.snapshot();
          } catch (error) {
            if (!(error instanceof HostError) || !["ASSISTANT_TRANSPORT_FAILED", "ASSISTANT_REQUEST_TIMEOUT"].includes(error.code)) throw error;
          }
        }
        await sleep(Math.min(50, Math.max(1, deadline - Date.now())), generation.abort.signal);
      }
      throw new HostError("ASSISTANT_STARTUP_TIMEOUT");
    } catch (error) {
      let failure = code(error);
      if (generation) {
        if (migration) {
          // Never reclaim an uncertain failed startup by force. Retry only
          // after this exact Job and its streams have naturally drained.
          generation.migrationRetirementRequested = true;
          this.finishMigrationRetirement(generation);
        } else {
          try { await this.retire(generation, false); }
          catch (retirementError) { failure = code(retirementError); }
        }
        if (this.current === generation && generation.closed) this.current = null;
      }
      this.view = { state: "failed", errorCode: failure };
      throw new HostError(failure);
    }
  }

  /** Main-only bytes from an operator-selected image, never renderer/model JSON. */
  async importOperatorImage(input: { kind: "avatar" | "background"; filename: string; contentType: string; dataBase64: string }, deliveryId: string): Promise<unknown> {
    if (!/^[0-9a-f]{32}$/.test(deliveryId) || !["avatar","background"].includes(input.kind)
      || typeof input.filename !== "string" || input.filename.length > 240 || typeof input.contentType !== "string"
      || typeof input.dataBase64 !== "string" || input.dataBase64.length > Math.ceil((input.kind === "avatar" ? 5 : 10)*1024*1024/3)*4) throw new HostError("ASSISTANT_REQUEST_INVALID");
    const generation = this.current;
    if (!this.options.appearanceControl || !generation || generation.closed || generation.abort.signal.aborted || this.view.state !== "ready") throw new HostError("ASSISTANT_NOT_READY");
    return await this.rpc(generation, `/api/assistant/operator-assets/${input.kind}`, "POST",
      { deliveryId, filename: input.filename, contentType: input.contentType, dataBase64: input.dataBase64 }, REQUEST_MS, false, 8192);
  }

  /** Main-only. Caller owns the registry lease and the native approval policy. */
  async importHistory(input: { projectId: string; previewId: string; turnId: string; revision: number; signal?: AbortSignal }): Promise<unknown> {
    if (!/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$/.test(input.projectId)
      || !/^[a-f0-9]{64}$/.test(input.previewId) || typeof input.turnId !== "string"
      || !/^\S{1,160}$/.test(input.turnId) || !Number.isSafeInteger(input.revision) || input.revision < 0) {
      throw new HostError("ASSISTANT_REQUEST_INVALID");
    }
    const generation = this.current;
    if (!generation || generation.closed || generation.abort.signal.aborted || this.view.state !== "ready"
      || this.projectsSuspended || generation.projectRevision !== input.revision) throw new HostError("ASSISTANT_NOT_READY");
    const operationId = randomBytes(16).toString("hex");
    const body = { projectId: input.projectId, previewId: input.previewId, turnId: input.turnId, revision: input.revision, operationId };
    const unknown = { schemaVersion: 1, projectId: input.projectId, previewId: input.previewId,
      state: "unknown", code: "unknown", readyForCutover: false };
    const fence = async () => {
      const result = await this.rpc(generation, "/api/assistant/history-import/cancel", "POST",
        { operationId, previewId: input.previewId }, 5_000, true, 8192);
      if (!object(result) || Object.keys(result).length !== 3 || result.schemaVersion !== 1
        || result.operationId !== operationId || result.cancelled !== true) throw new HostError("ASSISTANT_RESPONSE_INVALID");
    };
    if (input.signal?.aborted) {
      try { await fence(); return { ...unknown, state: "rejected", code: "cancelled" }; }
      catch { await this.stop(); return unknown; }
    }
    try {
      const result = await this.rpc(generation, "/api/assistant/history-import", "POST", body, 120_000, false, 8192, input.signal);
      if (!object(result) || !ownKeys(result, ["schemaVersion", "projectId", "previewId", "state", "code", "historyCount", "readyForCutover"])
        || result.schemaVersion !== 1 || result.projectId !== input.projectId || result.previewId !== input.previewId
        || result.readyForCutover !== false || !["published", "rejected", "unknown"].includes(String(result.state))
        || !(result.state === "published" && result.code === "imported" && Number.isSafeInteger(result.historyCount) && Number(result.historyCount) >= 0 && Number(result.historyCount) <= 10_000
          || result.state === "rejected" && ["preview_invalid", "project_unavailable", "cancelled", "busy"].includes(String(result.code)) && result.historyCount === undefined
          || result.state === "unknown" && result.code === "unknown" && result.historyCount === undefined)) {
        throw new HostError("ASSISTANT_RESPONSE_INVALID");
      }
      return result;
    } catch {
      try {
        // A fresh request bypasses the aborted signal. Its ACK is sent only
        // after the host has fenced this operation's publication guard.
        await fence();
      } catch {
        // Never release the main registry lease while an unfenced writer lives.
        await this.stop();
      }
      return unknown;
    }
  }

  /** Main-only. The caller keeps the registry lease until this worker drains. */
  async prepareInitialMigration(request: InitialMigrationMainControlRequest, revision: number, signal?: AbortSignal): Promise<boolean | "busy"> {
    if (!this.options.initialMigrationControl || !/^[a-f0-9]{32}$/.test(request.deliveryId)
      || !/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$/.test(request.projectId) || !/^[a-f0-9]{64}$/.test(request.previewId)
        || !/^\S{1,160}$/.test(request.turnId) || !/^(?:initial|ksync|krec)-[a-f0-9]{40}$/.test(request.operationId)
        || (request.category === "knowledge_sync") !== request.operationId.startsWith("ksync-")
        || (request.category === "knowledge_recovery") !== request.operationId.startsWith("krec-")
        || (request.category === "knowledge_recovery" ? typeof request.originalSyncId !== "string" || !/^ksync-[a-f0-9]{40}$/.test(request.originalSyncId) : request.originalSyncId !== undefined)
        || !["personal", "knowledge", "knowledge_sync", "knowledge_recovery", "reminder_handoff"].includes(request.category) || !Number.isSafeInteger(revision) || revision < 0) {
      console.warn("ASSISTANT_INITIAL_PREPARE phase=admission code=request_invalid");
      throw new HostError("ASSISTANT_REQUEST_INVALID");
    }
    const generation = this.current;
    if (!generation || generation.closed || generation.abort.signal.aborted || this.view.state !== "ready"
      || this.projectsSuspended || generation.projectRevision !== revision) {
      console.warn("ASSISTANT_INITIAL_PREPARE phase=admission code=not_ready");
      throw new HostError("ASSISTANT_NOT_READY");
    }
    const body = { deliveryId: request.deliveryId, projectId: request.projectId, previewId: request.previewId,
      turnId: request.turnId, category: request.category, operationId: request.operationId, revision,
      ...(request.category === "knowledge_recovery" ? { originalSyncId: request.originalSyncId } : {}) };
    let phase: "rpc" | "validation" = "rpc";
    try {
      const result = await this.rpc(generation, "/api/assistant/initial-migration/prepare", "POST", body, 120_000, false, 8192, signal);
      phase = "validation";
      if (object(result) && Object.keys(result).length === 4 && result.schemaVersion === 1
        && result.operationId === request.operationId && result.state === "rejected" && result.code === "busy"
        && !signal?.aborted && !generation.abort.signal.aborted) return "busy";
      const keys = ["schemaVersion", "registeredProjectId", "sourceScope", "category", "turnId", "operationId", "revision",
        "sourceIdentityDigest", "registryDigest", "targetIdentityDigest", "projectDirectory", "workspaceDirectory", "targetDirectory",
        "targetAgentId", "targetSessionId", "authority", "readyForCutover"];
        if (request.category === "knowledge_sync" || request.category === "knowledge_recovery") keys.push("previewId", "baselineMigrationId");
        if (request.category === "knowledge_recovery") keys.push("originalSyncId");
        if (request.category === "reminder_handoff") keys.push("syncId", "baselineId", "baselineState");
      const identity = (value: unknown) => object(value) && Object.keys(value).length === 3
        && ["device", "inode", "birthtimeNs"].every(key => typeof value[key] === "string" && /^[1-9][0-9]{0,24}$/.test(value[key] as string));
      const opaque = (value: unknown) => typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$/.test(value);
      if (!object(result) || Object.keys(result).length !== keys.length || !ownKeys(result, keys)
        || result.schemaVersion !== 1 || result.registeredProjectId !== request.projectId || result.category !== request.category
        || result.turnId !== request.turnId || result.operationId !== request.operationId || result.revision !== revision
          || ((request.category === "knowledge_sync" || request.category === "knowledge_recovery") && (result.previewId !== request.previewId
            || result.baselineMigrationId !== `initial-${createHash("sha256").update(`${request.projectId}:knowledge`).digest("hex").slice(0, 40)}`))
        || (request.category === "knowledge_recovery" && result.originalSyncId !== request.originalSyncId)
        || (request.category === "reminder_handoff" && (result.baselineId !== null || result.baselineState !== "unknown"
          || result.syncId !== `affairs-${createHash("sha256").update(`${request.projectId}:reminder_handoff`).digest("hex").slice(0, 40)}`))
        || result.authority !== "native_policy_admitted" || result.readyForCutover !== false
        || !object(result.sourceScope) || Object.keys(result.sourceScope).length !== 3
        || !["projectId", "instanceId", "agentId"].every(key => opaque((result.sourceScope as Record<string, unknown>)[key]))
        || !["sourceIdentityDigest", "registryDigest", "targetIdentityDigest"].every(key => typeof result[key] === "string" && /^[a-f0-9]{64}$/.test(result[key] as string))
        || !identity(result.projectDirectory) || !identity(result.workspaceDirectory) || !identity(result.targetDirectory)
        || !opaque(result.targetAgentId) || !opaque(result.targetSessionId)) throw new HostError("ASSISTANT_RESPONSE_INVALID");
      return true;
    } catch (error) {
      const allowed = new Set(["ASSISTANT_HTTP_FAILED", "ASSISTANT_RESPONSE_INVALID", "ASSISTANT_RESPONSE_TOO_LARGE",
        "ASSISTANT_REQUEST_TIMEOUT", "ASSISTANT_STOPPED", "ASSISTANT_TRANSPORT_FAILED", "ASSISTANT_NOT_READY"]);
      const failure = error instanceof HostError && allowed.has(error.code) ? error.code : "unexpected";
      console.warn(`ASSISTANT_INITIAL_PREPARE phase=${phase} code=${failure}`);
      // HTTP abort does not stop a native worker. Revoke and wait for its
      // private drain ACK, or for the captured Job itself to fully exit.
      while (true) {
        try {
          const result = await this.rpc(generation, "/api/assistant/initial-migration/drain", "POST",
            { deliveryId: request.deliveryId, operationId: request.operationId }, 5_000, true, 8192);
          if (object(result) && Object.keys(result).length === 4 && result.schemaVersion === 1
            && result.operationId === request.operationId && result.state === "unknown" && result.drained === true) return false;
        } catch { /* Retain the lease until a worker or Job drain is confirmed. */ }
        try {
          if (generation.native.activeCount(generation.job) === 0 && generation.native.drainStatus(generation.job).complete
            && typeof generation.native.exitCode === "function" && generation.native.exitCode(generation.job) !== null) return false;
        } catch { /* Continue to own the original Job. */ }
        await sleep(1000);
      }
    }
  }

  /** Main-only; caller holds the project registry lease through cancellation and drain. */
  async syncAffairs(input: { projectId: string; previewId: string; turnId: string; revision: number; signal?: AbortSignal; recoverSyncId?: string }): Promise<unknown> {
    return this.syncMemory(input, false);
  }

  async syncEpisodic(input: { projectId: string; previewId: string; turnId: string; revision: number; signal?: AbortSignal; recoverSyncId?: string; resolveSyncId?: string; reviewToken?: string }): Promise<unknown> {
    return this.syncMemory(input, true);
  }

  private async syncMemory(input: { projectId: string; previewId: string; turnId: string; revision: number; signal?: AbortSignal; recoverSyncId?: string; resolveSyncId?: string; reviewToken?: string }, episodic: boolean): Promise<unknown> {
    if (!/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$/.test(input.projectId)
      || !/^[a-f0-9]{64}$/.test(input.previewId) || typeof input.turnId !== "string"
      || !/^\S{1,160}$/.test(input.turnId) || !Number.isSafeInteger(input.revision) || input.revision < 0
      || (input.recoverSyncId !== undefined && !(episodic ? /^episodic-[a-f0-9]{40}$/ : /^affairs-[a-f0-9]{40}$/).test(input.recoverSyncId))
      || (input.resolveSyncId === undefined) !== (input.reviewToken === undefined)
      || (input.resolveSyncId !== undefined && (!episodic || input.recoverSyncId !== undefined
        || !/^episodic-[a-f0-9]{40}$/.test(input.resolveSyncId) || !/^[a-f0-9]{64}$/.test(input.reviewToken!)))) {
      throw new HostError("ASSISTANT_REQUEST_INVALID");
    }
    const generation = this.current;
    if (!generation || generation.closed || generation.abort.signal.aborted || this.view.state !== "ready"
      || this.projectsSuspended || generation.projectRevision !== input.revision) throw new HostError("ASSISTANT_NOT_READY");
    const operationId = randomBytes(16).toString("hex");
    const body = { projectId: input.projectId, previewId: input.previewId, turnId: input.turnId, revision: input.revision, operationId,
      ...(input.recoverSyncId !== undefined ? { recoverSyncId: input.recoverSyncId } : {}),
      ...(input.resolveSyncId !== undefined ? { resolveSyncId: input.resolveSyncId, reviewToken: input.reviewToken } : {}) };
    const unknown = (episodic ? unknownEpisodicSyncResult : unknownAffairsSyncResult)(input);
    const path = episodic ? "/api/assistant/episodic-sync" : "/api/assistant/affairs-sync";
    const fence = async () => {
      const result = await this.rpc(generation, `${path}/cancel`, "POST",
        { operationId, previewId: input.previewId }, 15_000, true, 8192);
      if (!object(result) || Object.keys(result).length !== 3 || result.schemaVersion !== 1
        || result.operationId !== operationId || result.cancelled !== true) throw new HostError("ASSISTANT_RESPONSE_INVALID");
    };
    if (input.signal?.aborted) {
      try { await fence(); return input.recoverSyncId !== undefined ? unknown : { ...unknown, state: "rejected", code: "cancelled" }; }
      catch { await this.stop(); return unknown; }
    }
    try {
      const result = await this.rpc(generation, path, "POST", body, 120_000, false, 8192, input.signal);
      const parsed = (episodic ? parseEpisodicSyncResult : parseAffairsSyncResult)(input, result);
      if (!parsed) throw new HostError("ASSISTANT_RESPONSE_INVALID");
      return parsed;
    } catch {
      try { await fence(); }
      catch { await this.stop(); }
      return unknown;
    }
  }

  private startMainControl(generation: Generation): void {
    const onRequest = this.options.mainControl!;
    this.mainControlUncertain = false;
    void runMainControlPump({
      signal: generation.abort.signal,
      isCurrent: () => this.current === generation && !generation.closed && this.view.state === "ready",
      invoke: (path, method, body) => this.rpc(generation, path, method, body, REQUEST_MS, false, 8_192),
      onRequest: async (request, signal) => {
        while (this.migrationAdmission) {
          const admission = this.migrationAdmission;
          const aborted = AbortSignal.any([generation.abort.signal, ...(signal ? [signal] : [])]);
          if (aborted.aborted) throw new HostError("ASSISTANT_STOPPED");
          await new Promise<void>((resolve, reject) => {
            const cancel = () => { aborted.removeEventListener("abort", cancel); reject(new HostError("ASSISTANT_STOPPED")); };
            aborted.addEventListener("abort", cancel, { once: true });
            admission.released.then(() => { aborted.removeEventListener("abort", cancel); resolve(); });
          });
        }
        if (generation.abort.signal.aborted || signal?.aborted) throw new HostError("ASSISTANT_STOPPED");
        this.mainControlRequests += 1;
        try { return await onRequest(request, signal); }
        finally { this.mainControlRequests -= 1; this.settleMigrationAdmissionDrain(); }
      },
      onFailure: () => {
        if (this.current !== generation || generation.abort.signal.aborted) return;
        if (this.migrationAdmission) {
          // A failed control pump is not proof that its effects drained. Keep
          // the host and heartbeat alive; migration must remain unavailable.
          this.mainControlUncertain = true;
          return;
        }
        generation.abort.abort();
        this.view = { state: "failed", errorCode: "ASSISTANT_MAIN_CONTROL_FAILED" };
        // Reuse the same serialized Job owner; never race another retirement or
        // cancel a native project command when only the assistant channel failed.
        const operation = this.serial.then(async () => {
          if (this.current !== generation) return;
          try { await this.retire(generation, false); }
          finally { if (generation.closed && this.current === generation) this.current = null; }
        });
        this.serial = operation.catch(() => undefined);
      },
    }).catch(() => undefined);
  }

  private readReady(generation: Generation): { port: number } | null {
    const path = join(generation.directory, "ready.json");
    if (!existsSync(path)) return null;
    let ready: unknown;
    try {
      if (statSync(path).size > READY_MAX_BYTES) throw new HostError("ASSISTANT_READY_INVALID");
      ready = JSON.parse(readFileSync(path, "utf8"));
    } catch { throw new HostError("ASSISTANT_READY_INVALID"); }
    if (!object(ready) || !ownKeys(ready, ["protocolVersion", "role", "instanceId", "pid", "port"])
      || ready.protocolVersion !== 1 || ready.role !== "launcher_assistant" || ready.instanceId !== generation.id
      || !positiveInteger(ready.pid) || !positiveInteger(ready.port, 65_535)) throw new HostError("ASSISTANT_READY_INVALID");
    // A venv pythonw redirector can have a different root PID; Job ownership is authoritative.
    return { port: ready.port };
  }

  private async rpc(generation: Generation, path: string, method: "GET" | "POST" | "PUT", body?: object,
    timeoutMs = REQUEST_MS, retiring = false, maxResponseBytes = MAX_RESPONSE_BYTES, callerSignal?: AbortSignal): Promise<unknown> {
    if (!generation.origin || generation.closed || (!retiring && generation.abort.signal.aborted)) throw new HostError("ASSISTANT_NOT_READY");
    const timeout = new AbortController();
    const timer = setTimeout(() => timeout.abort(), timeoutMs);
    const signal = AbortSignal.any([timeout.signal, ...(!retiring ? [generation.abort.signal] : []), ...(callerSignal ? [callerSignal] : [])]);
    try {
      const response = await (this.options.fetch ?? globalThis.fetch)(`${generation.origin}${path}`, {
        method, redirect: "error", signal,
        headers: { Authorization: `Bearer ${generation.token}`, ...(body ? { "Content-Type": "application/json" } : {}) },
        ...(body ? { body: JSON.stringify(body) } : {}),
      });
      if (!response.ok) {
        await response.body?.cancel().catch(() => undefined);
        throw new HostError(path === "/api/assistant/reminders/next" && response.status === 409
          ? "ASSISTANT_REMINDER_BLOCKED" : "ASSISTANT_HTTP_FAILED");
      }
      const length = Number(response.headers.get("content-length"));
      if (Number.isFinite(length) && length > maxResponseBytes) {
        await response.body?.cancel().catch(() => undefined);
        throw new HostError("ASSISTANT_RESPONSE_TOO_LARGE");
      }
      if (!response.body) throw new HostError("ASSISTANT_RESPONSE_INVALID");
      const reader = response.body.getReader();
      const chunks: Uint8Array[] = [];
      let size = 0;
      try {
        while (true) {
          const part = await reader.read();
          if (signal.aborted) throw new HostError(timeout.signal.aborted ? "ASSISTANT_REQUEST_TIMEOUT" : "ASSISTANT_STOPPED");
          if (part.done) break;
          size += part.value.byteLength;
          if (size > maxResponseBytes) throw new HostError("ASSISTANT_RESPONSE_TOO_LARGE");
          chunks.push(part.value);
        }
      } finally {
        await reader.cancel().catch(() => undefined);
        reader.releaseLock();
      }
      try { return JSON.parse(Buffer.concat(chunks).toString("utf8")); }
      catch { throw new HostError("ASSISTANT_RESPONSE_INVALID"); }
    } catch (error) {
      const failure = error instanceof HostError ? error : new HostError(timeout.signal.aborted ? "ASSISTANT_REQUEST_TIMEOUT"
        : generation.abort.signal.aborted && !retiring ? "ASSISTANT_STOPPED" : "ASSISTANT_TRANSPORT_FAILED");
      if (!retiring && this.current === generation && this.view.state === "ready"
        && ["ASSISTANT_TRANSPORT_FAILED", "ASSISTANT_REQUEST_TIMEOUT"].includes(failure.code)) {
        try {
          if (generation.native.activeCount(generation.job) === 0) this.view = { state: "failed", errorCode: "ASSISTANT_EXITED" };
        } catch { this.view = { state: "failed", errorCode: "ASSISTANT_JOB_INSPECTION_FAILED" }; }
      }
      // A later explicit start may recover a dead Job. This request is never replayed.
      throw failure;
    } finally { clearTimeout(timer); }
  }

  private async retire(generation: Generation, graceful: boolean): Promise<void> {
    if (generation.closed) return;
    generation.abort.abort();
    let drained = false;
    let failure: string | null = null;
    try {
      if (generation.native.activeCount(generation.job) === 0) {
        // Natural/crash exit still owns its output drains until the same handle closes.
        drained = await this.waitDrain(generation, 8_000);
      } else if (graceful && generation.origin) {
        // This shuts down/drains the own chat host; no remote-dispatch cancel endpoint exists here.
        try { await this.rpc(generation, "/api/assistant/shutdown", "POST", {}, 2_000, true); }
        catch { /* Reclaim only this captured Job if graceful shutdown is unavailable. */ }
        drained = await this.waitDrain(generation, 12_000);
      }
      if (!drained) {
        if (!generation.native.terminate(generation.job)) failure = "ASSISTANT_TERMINATE_UNCONFIRMED";
        drained = await this.waitDrain(generation, 8_000);
      }
      if (!drained) failure ??= "ASSISTANT_DRAIN_TIMEOUT";
    } catch { failure = "ASSISTANT_RETIRE_FAILED"; }
    finally {
      try {
        generation.native.close(generation.job);
        generation.closed = true;
        generation.token = "";
      }
      catch { failure = "ASSISTANT_CLOSE_FAILED"; }
    }
    if (failure) throw new HostError(failure);
  }

  private async waitDrain(generation: Generation, timeoutMs: number): Promise<boolean> {
    const deadline = Date.now() + timeoutMs;
    do {
      if (generation.native.activeCount(generation.job) === 0 && generation.native.drainStatus(generation.job).complete) return true;
      if (Date.now() >= deadline) return false;
      await sleep(20);
    } while (true);
  }
}
