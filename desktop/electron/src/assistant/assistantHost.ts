/** Launcher-owned source-host lifecycle; packaged host distribution is a separate boundary. */
import { createHash, randomBytes, randomUUID } from "node:crypto";
import { closeSync, existsSync, mkdirSync, openSync, readFileSync, readSync, realpathSync, statSync, writeFileSync } from "node:fs";
import { isAbsolute, join, resolve } from "node:path";
import { loadWorkbenchJobNative, type WorkbenchJobHandle, type WorkbenchJobNative } from "../process/workbenchJob.js";
import { resolveNoConsolePython } from "../process/workbenchBackend.js";
import { MAX_ASSISTANT_PROJECTS, type AssistantProjectRegistrySnapshot } from "./projectRegistry.js";
import { parseAffairsSyncResult, parseEpisodicSyncResult, runMainControlPump, unknownAffairsSyncResult, unknownEpisodicSyncResult, type InitialMigrationMainControlRequest, type MainControlRequest } from "./mainControlTransport.js";
import { isConfigurationReferenceRequest, type ConfigurationReferenceHostContext } from "./configurationReferenceProtocol.js";

const STARTUP_MS = 60_000;
const REQUEST_MS = 15_000;
/** Light UI reads pay shorter RPC budgets than the write default: status is
 * the most frequent and cheapest poll; the other read views return bounded
 * page payloads and never mutate host state. Writes, computer control and
 * the explicit long operations keep REQUEST_MS or their own budgets. */
const STATUS_READ_MS = 5_000;
const READ_MS = 8_000;
/** Control-channel claim/settle RPC budget. A claim is a bounded 10s
 * host-side long poll and settle carries full results, while a chronic
 * global lock can hold one host turn for ~14s (2026-11-03 live-fire): at
 * REQUEST_MS=15s that left ~1s of margin, and one trip killed the host.
 * Only this channel gets the doubled budget; every other RPC keeps its own. */
const MAIN_CONTROL_RPC_MS = 30_000;
const MAX_RESPONSE_BYTES = 8 * 1024 * 1024;
/** Error responses only need to carry a short structured code; larger failure
 * bodies are cancelled unread and fall back to the status-only mapping. */
const MAX_ERROR_BODY_BYTES = 4096;
const MAX_LOG_BYTES = 4 * 1024 * 1024;
const READY_MAX_BYTES = 4_096;
/** The native Job binding exposes no exit event; poll alive-ness at a low rate. */
const LIVENESS_POLL_MS = 2_000;
const RESPAWN_BASE_DELAY_MS = 2_000;
const RESPAWN_MAX_DELAY_MS = 60_000;
/** Automatic respawns per rolling window before the host is declared unavailable. */
const RESPAWN_MAX_ATTEMPTS = 5;
const RESPAWN_WINDOW_MS = 600_000;
const FORENSICS_STDERR_TAIL_BYTES = 2_048;
/** A dying host resets its control sockets before its Job settles: a venv
 * pythonw redirector root exits only after its killed host child. A failed
 * pump on a still-counted Job is re-probed this long before it is treated as
 * a live host's control-channel failure. */
const CONTROL_FAILURE_SETTLE_MS = 1_000;
const CONTROL_FAILURE_SETTLE_POLL_MS = 50;
/** Consecutive control-channel pump failures tolerated on a live host before
 * it is retired. Tonight one healthy host was terminated three times, 5-13
 * minutes apart, on single RPC hiccups behind the chronic slow handler;
 * each kill silently dropped reminders and native sessions until the next
 * renderer request revived it. Up to LIMIT-1 failures now reconnect the
 * transport instead, and any successful claim resets the count, so only a
 * channel that stays broken across reconnects reaches the limit. */
const MAIN_CONTROL_FAILURE_LIMIT = 3;

/** Which shell observer first classified an unexpected host exit. */
type HostDeathObserver = "liveness_poll" | "main_control";

export type AssistantHostSnapshot = {
  state: "stopped" | "starting" | "ready" | "stopping" | "failed";
  errorCode: string | null;
};
export type AssistantQueuedTurnRequest =
  | { operation: "updateQueuedTurn"; sessionId: string; queuedTurnId: string; content?: string; position?: number; status?: "paused" | "queued" }
  | { operation: "removeQueuedTurn"; sessionId: string; queuedTurnId: string }
  | { operation: "sendNowQueuedTurn"; sessionId: string; queuedTurnId: string; expectedTurnId?: string };
export type AssistantHostRequest =
  | AssistantQueuedTurnRequest
  | { operation: "previewTaskCleanup" | "executeTaskCleanup"; agentId: string; directSessionId: string; targets: unknown[]; fingerprint?: string }
  | { operation: "teamRuns"; cursor?: string }
  | { operation: "setModel"; modelId: string }
  | { operation: "budgetParameters" }
  | { operation: "usageSummary" }
  | { operation: "setBudgetParameters"; revision: number; maxCallsPerTurn: number | null }
  | { operation: "setManagementPermissionPreset"; preset: "request_approval" | "auto_review" | "full_access"; expectedRevision: number }
  | { operation: "detail"; beforeMessageIndex?: number }
  | { operation: "status" | "dispatches" | "config" | "approvals" | "assistantAvatar" }
  | { operation: "resolveApproval"; requestId: string; decision: "accept" | "decline" }
  | { operation: "previewDispatchApproval"; dispatchId: string; taskId: string; approvalId: string }
  | { operation: "declineDispatchApproval"; dispatchId: string; taskId: string; approvalId: string; revision: string }
  | { operation: "decideDispatchApproval"; dispatchId: string; taskId: string; approvalId: string; revision: string; decision: "accept" | "decline" }
  | { operation: "send"; message: string; requestId: string; attachmentIds?: string[]; references?: unknown[];
      controlContinuation?: { agentId: string; sessionId: string; turnId: string; headId: string; ledgerSeq: number } }
  | { operation: "uploadAttachment"; filename: string; contentType: string; dataBase64: string }
  | { operation: "upload_attachment"; kind: "user_secret"; value: string; secretKind?: "api_key" | "token" | "password" | "secret"; label?: string }
  | { operation: "readAttachment"; artifactId: string }
  | { operation: "stop"; turnId: string }
  | { operation: "continue"; requestId: string; continuation: { turnId: string; headId: string; ledgerSeq: number; agentId: string } }
  | { operation: "switchHead"; nodeId: string }
  | { operation: "regenerate"; messageId: string; requestId: string }
  | { operation: "guidance"; content: string; mode: "safe" | "interrupt" }
  | { operation: "curation"; sessionId: string }
  | { operation: "curate"; sessionId: string; messageId: string; action: "include" | "exclude" }
  | { operation: "operatorAsset"; kind: "avatar" | "background" }
  | { operation: "computerState" }
  | { operation: "computerWindows" }
  | { operation: "computerGrant"; selectionId: string; allowVision: true; authorizationRequestId?: string }
  | { operation: "computerControl"; grantId: string; action: "pause" | "resume" | "takeover" | "return" | "end" }
  | { operation: "computerConfirm"; grantId: string; pendingId: string; approved: boolean };

/** Read-only requests still drain with migration, but cannot submit new work. */
const LIFECYCLE_READ_OPERATIONS: ReadonlySet<AssistantHostRequest["operation"]> = new Set([
  "status", "detail", "dispatches", "teamRuns", "config", "approvals", "curation",
  "operatorAsset", "assistantAvatar", "computerState", "readAttachment", "budgetParameters", "usageSummary"
]);

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
  /** Owner shutdown fences new starts, never the captured Job's stop/drain. */
  startupSignal?: AbortSignal;
  /** Main-only native lifecycle capability; deliberately absent from renderer IPC. */
  mainControl?: (request: MainControlRequest, signal?: AbortSignal, hostContext?: ConfigurationReferenceHostContext) => Promise<unknown>;
  mainControlSettled?: (request: MainControlRequest, result: Record<string, unknown>, accepted: boolean | undefined,
    hostContext?: ConfigurationReferenceHostContext) => void | Promise<void>;
  appearanceControl?: boolean;
  browserControl?: boolean;
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
  agentId?: string;
  closed: boolean;
  projectRevision: number;
  migrationRetirementRequested?: boolean;
  referenceDrained?: boolean;
  nativeAssistantRoot: string;
  profileIdentity: string;
  referenceLeases?: Set<symbol>;
  referenceRecovery?: boolean;
  controlRetryMs?: number;
  controlPump?: AbortController;
  /** Consecutive failed control-channel pumps on this generation; any
   * successful claim resets it. Reaching MAIN_CONTROL_FAILURE_LIMIT retires
   * a live host the old code killed on the first failure. Survives pump
   * reconnects; a fresh generation starts uncounted. */
  controlFailures?: number;
  /** Bounded name of the last control-channel failure; forensics only. */
  lastControlError?: string;
  /** Job root pid captured at spawn; forensics only, never an ownership proof. */
  pid?: number;
  /** ready.json pid of the serving host; differs from pid under a venv redirector. Forensics only. */
  hostPid?: number;
  /** Wall clock when this generation reached the ready view; uptime source. */
  readyAt?: number;
  /** Set by the first observer that classifies this generation's exit. */
  exitHandled?: boolean;
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
/** Shared transport validation; fixed Session identity is checked by the host generation. */
export function isAssistantQueuedTurnRequest(value: unknown): value is AssistantQueuedTurnRequest {
  if (!object(value)) return false;
  const fields = value.operation === "updateQueuedTurn" ? ["content", "position", "status"]
    : value.operation === "sendNowQueuedTurn" ? ["expectedTurnId"]
    : value.operation === "removeQueuedTurn" ? [] : null;
  const id = (item: unknown): item is string => typeof item === "string" && /^[A-Za-z0-9_-]{1,160}(?![\s\S])/.test(item);
  if (fields === null || !ownKeys(value, ["operation", "sessionId", "queuedTurnId", ...fields])
    || !id(value.sessionId) || !id(value.queuedTurnId)) return false;
  if ("content" in value && (typeof value.content !== "string" || value.content.length > 64000)
    || "position" in value && (!Number.isSafeInteger(value.position) || (value.position as number) < 1)
    || "status" in value && value.status !== "paused" && value.status !== "queued"
    || "expectedTurnId" in value && !id(value.expectedTurnId)) return false;
  return true;
}
const USAGE_NUMBER_FIELDS = ["inputTokens", "cachedInputTokens", "cacheReadInputTokens", "cacheCreationInputTokens",
  "uncachedInputTokens", "outputTokens", "reasoningOutputTokens", "totalTokens", "latencyMs"];
const USAGE_ROLLUP_COUNT_FIELDS = ["callCount", "observedCallCount", "estimatedCallCount", "missingCallCount",
  "notCalledCount", "cacheObservedInputTokens", "cacheObservedCallCount", "cacheUnobservedCallCount"];
function validUsageProjection(value: unknown, rollup: boolean): boolean {
  const fields = [...USAGE_NUMBER_FIELDS, "cacheHitRate", "cacheUsageObserved", "cacheUsageMissingReason",
    ...(rollup ? [...USAGE_ROLLUP_COUNT_FIELDS, "cacheUsageComplete"] : ["source"])];
  if (!object(value) || Object.keys(value).length !== fields.length || !ownKeys(value, fields)
    || [...USAGE_NUMBER_FIELDS, ...(rollup ? USAGE_ROLLUP_COUNT_FIELDS : [])].some(key =>
      !Number.isSafeInteger(value[key]) || (value[key] as number) < 0)
    || typeof value.cacheHitRate !== "number" || !Number.isFinite(value.cacheHitRate)
    || value.cacheHitRate < 0 || value.cacheHitRate > 1 || typeof value.cacheUsageObserved !== "boolean"
    || typeof value.cacheUsageMissingReason !== "string"
    || !["", "not_called", "provider_cache_usage_missing", "partial_provider_cache_usage"].includes(value.cacheUsageMissingReason)) return false;
  return rollup ? typeof value.cacheUsageComplete === "boolean"
    : typeof value.source === "string" && ["provider_usage", "estimated", "missing", "not_called"].includes(value.source);
}
function validUsageSummary(value: unknown): value is Record<string, unknown> {
  return object(value) && Object.keys(value).length === 4
    && ownKeys(value, ["sessionId", "agentId", "sessionTokenUsage", "lastTokenUsage"])
    && [value.sessionId, value.agentId].every(id => typeof id === "string" && /^[A-Za-z0-9_-]{1,160}$/.test(id))
    && validUsageProjection(value.sessionTokenUsage, true) && validUsageProjection(value.lastTokenUsage, false);
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
/** Bounded error name/code for control-failure forensics; never a body,
 * stack or unbounded message. */
function controlErrorName(error: unknown): string {
  const text = error instanceof HostError ? error.code
    : error instanceof Error ? (error.message ? `${error.name}: ${error.message}` : error.name) : String(error);
  return text.slice(0, 120) || "unknown";
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
  private lifecycleAdmission: { arrival: boolean; committed: boolean } | null = null;
  private rendererRequests = 0;
  private rendererMutationRequests = 0;
  private mainControlRequests = 0;
  private mainControlUncertain = false;
  private rendererDrainWaiters = new Set<() => void>();
  private projectSnapshot: AssistantProjectRegistrySnapshot;
  private projectsSuspended: boolean;
  private livenessTimer: ReturnType<typeof setInterval> | null = null;
  private livenessWatch: Generation | null = null;
  private respawnTimer: ReturnType<typeof setTimeout> | null = null;
  private respawnAttempts = 0;
  private respawnWindowStart = 0;
  private respawnRevision = -1;
  private respawnSuspended = false;
  private hostDeaths = 0;

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

  /** Main-process lease for the session event pump. The bearer token is handed
   * to the pump only inside this process; retirement aborts the leased signal. */
  eventPumpLease(): { generationId: string; origin: string; token: string; sessionId: string; signal: AbortSignal } | null {
    const generation = this.current;
    if (this.view.state !== "ready" || !generation || generation.closed || generation.abort.signal.aborted
      || !generation.origin || !generation.sessionId) return null;
    return { generationId: generation.id, origin: generation.origin, token: generation.token,
      sessionId: generation.sessionId, signal: generation.abort.signal };
  }

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
    if (this.options.startupSignal?.aborted) return Promise.reject(new HostError("ASSISTANT_STOPPED"));
    // The bridge calls start() before request(). Lifecycle requests must reach
    // that owner to veto replacement or receive CLOSING, never wait invisibly.
    if (this.lifecycleAdmission) {
      if (this.view.state === "ready" && this.current && !this.current.abort.signal.aborted)
        return Promise.resolve(this.snapshot());
      return Promise.reject(new HostError("ASSISTANT_LIFECYCLE_CLOSING"));
    }
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
    if (this.options.startupSignal?.aborted) return Promise.reject(new HostError("ASSISTANT_STOPPED"));
    if (this.starting && this.startingRevision === this.revision) return this.starting;
    // Respawn budget exhausted: fail observably instead of hanging or spawning.
    // An in-flight start above is still joined; migration startup stays allowed.
    if (this.respawnSuspended && !migration) return Promise.reject(new HostError("ASSISTANT_HOST_UNAVAILABLE"));
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
    this.endLivenessWatch();
    if (this.respawnTimer !== null) { clearTimeout(this.respawnTimer); this.respawnTimer = null; }
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
   * Continuous alive-ness watch for one ready generation. The native Job
   * binding exposes no exit event, so this polls activeCount at a low fixed
   * rate; a zero count with no shell-initiated retirement in flight and no
   * held lifecycle admission is an unexpected death and arms the bounded
   * respawn path.
   */
  private beginLivenessWatch(generation: Generation): void {
    this.endLivenessWatch();
    this.livenessWatch = generation;
    this.livenessTimer = setInterval(() => this.livenessTick(generation), LIVENESS_POLL_MS);
    this.livenessTimer.unref?.();
  }

  private endLivenessWatch(): void {
    if (this.livenessTimer !== null) { clearInterval(this.livenessTimer); this.livenessTimer = null; }
    this.livenessWatch = null;
  }

  private livenessTick(generation: Generation): void {
    if (this.livenessWatch !== generation || generation.closed) { this.endLivenessWatch(); return; }
    let active: number;
    try { active = generation.native.activeCount(generation.job); }
    catch { this.endLivenessWatch(); return; }
    if (active !== 0) return;
    // A held lifecycle admission is a controlled lifecycle operation, like stop
    // and migration: an exit under it is never an unexpected death and never
    // respawns. Keep watching so a death that outlives a released (cancelled)
    // admission is still handled once the host reopens.
    if (this.lifecycleAdmission) return;
    this.endLivenessWatch();
    // Every shell-initiated path (stop, retire, migration retirement, registry
    // rejection) aborts the generation signal or requests retirement before or
    // while the Job ends; an un-aborted, unretired current generation that
    // reached zero is an unexpected death.
    if (generation.abort.signal.aborted || generation.migrationRetirementRequested
      || this.current !== generation || this.stopping) return;
    this.handleUnexpectedDeath(generation);
  }

  /** The liveness poll and the control pump can both observe one exit; the
   * first observer classifies it, once per generation. Evidence and the
   * failed view precede respawn scheduling. */
  private handleUnexpectedDeath(generation: Generation, detectedBy: HostDeathObserver = "liveness_poll"): void {
    if (generation.exitHandled) return;
    generation.exitHandled = true;
    this.hostDeaths += 1;
    this.recordHostDeathForensics(generation, detectedBy);
    this.view = { state: "failed", errorCode: "ASSISTANT_EXITED" };
    this.scheduleRespawn();
  }

  /** One greppable shell-log line plus a best-effort death-forensics.json in
   * the generation directory: packaged shells capture no main stdout. An
   * unexpected exit classifies a Job that died on its own; a control-failure
   * retire records the deliberate terminate of a live host that reached the
   * failure limit, whose failing RPC would otherwise stay unattributable. */
  private recordHostDeathForensics(generation: Generation, detectedBy: HostDeathObserver,
    controlFailure?: { consecutiveFailures: number; lastError: string }): void {
    let exitCode: number | null = null;
    try { exitCode = typeof generation.native.exitCode === "function" ? generation.native.exitCode(generation.job) : null; }
    catch { exitCode = null; }
    const uptimeMs = typeof generation.readyAt === "number" ? Math.max(0, Date.now() - generation.readyAt) : null;
    const stderrTail = this.stderrTail(generation);
    const phase = controlFailure ? "control_failure_retire" : "unexpected_exit";
    console.warn(`ASSISTANT_HOST_DEATH phase=${phase} detectedBy=${detectedBy} exitCode=${exitCode ?? "unknown"} `
      + `instanceId=${generation.id} pid=${generation.pid ?? "unknown"} uptimeMs=${uptimeMs ?? "unknown"} `
      + (controlFailure ? `consecutiveFailures=${controlFailure.consecutiveFailures} lastError=${JSON.stringify(controlFailure.lastError)} ` : "")
      + `stderrTail=${JSON.stringify(stderrTail)}`);
    try {
      writeFileSync(join(generation.directory, "death-forensics.json"), JSON.stringify({
        schemaVersion: 1, phase, detectedBy, recordedAt: new Date().toISOString(), exitCode,
        instanceId: generation.id, pid: generation.pid ?? null, hostPid: generation.hostPid ?? null, uptimeMs, revision: this.revision,
        deathsInSession: this.hostDeaths, stderrTail,
        ...(controlFailure ? { consecutiveControlFailures: controlFailure.consecutiveFailures, lastControlError: controlFailure.lastError } : {}),
      }), { encoding: "utf8", mode: 0o600 });
    } catch { /* Best-effort evidence never blocks classification or respawn. */ }
  }

  /** Bounded best-effort tail of this generation's stderr log; never throws. */
  private stderrTail(generation: Generation): string {
    try {
      const path = join(generation.directory, "stderr.log");
      const size = statSync(path).size;
      const start = Math.max(0, size - FORENSICS_STDERR_TAIL_BYTES);
      const length = size - start;
      if (length === 0) return "";
      const handle = openSync(path, "r");
      try {
        const buffer = Buffer.alloc(length);
        const read = readSync(handle, buffer, 0, length, start);
        return buffer.toString("utf8", 0, read).slice(-FORENSICS_STDERR_TAIL_BYTES);
      } finally { closeSync(handle); }
    } catch { return ""; }
  }

  /** Exponential backoff 2s..60s, at most RESPAWN_MAX_ATTEMPTS spawns per
   * rolling window; success resets the budget. Exhaustion leaves the host
   * observably unavailable instead of retrying forever. */
  private scheduleRespawn(): void {
    if (this.respawnSuspended) return;
    const now = Date.now();
    if (this.respawnAttempts === 0 || now - this.respawnWindowStart >= RESPAWN_WINDOW_MS) {
      this.respawnWindowStart = now;
      this.respawnAttempts = 0;
    }
    this.respawnAttempts += 1;
    this.respawnRevision = this.revision;
    if (this.respawnAttempts > RESPAWN_MAX_ATTEMPTS) {
      this.respawnSuspended = true;
      this.view = { state: "failed", errorCode: "ASSISTANT_HOST_UNAVAILABLE" };
      console.warn("ASSISTANT_HOST_RESPAWN phase=exhausted "
        + `attempts=${RESPAWN_MAX_ATTEMPTS} windowMs=${RESPAWN_WINDOW_MS}`);
      return;
    }
    const delay = Math.min(RESPAWN_MAX_DELAY_MS, RESPAWN_BASE_DELAY_MS * 2 ** (this.respawnAttempts - 1));
    if (this.respawnTimer !== null) clearTimeout(this.respawnTimer);
    this.respawnTimer = setTimeout(() => { this.respawnTimer = null; this.beginRespawn(); }, delay);
    this.respawnTimer.unref?.();
  }

  /** Reuses the renderer start path: an in-flight start is joined instead of
   * spawning a competing generation. The migration barrier and a held lifecycle
   * admission forbid automatic respawns entirely; their owners own recovery.
   * A start invalidated by stop() never re-arms: stop is final. */
  private beginRespawn(): void {
    if (this.respawnSuspended || this.revision !== this.respawnRevision || this.migrationAdmission
      || this.lifecycleAdmission) return;
    const revision = this.revision;
    this.startOwned(false).then(snapshot => {
      if (snapshot.state === "ready") this.resetRespawnState();
    }).catch(() => { if (this.revision === revision) this.scheduleRespawn(); });
  }

  private resetRespawnState(): void {
    if (this.respawnTimer !== null) { clearTimeout(this.respawnTimer); this.respawnTimer = null; }
    this.respawnAttempts = 0;
    this.respawnWindowStart = 0;
    this.respawnSuspended = false;
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
      generation.referenceDrained = this.configurationReferenceJobDrained(generation);
      generation.native.close(generation.job);
      if (this.livenessWatch === generation) this.endLivenessWatch();
      generation.closed = true;
      generation.token = "";
      if (this.current === generation) this.current = null;
      this.view = { state: "stopped", errorCode: null };
      return true;
    } catch { return false; }
  }

  /** The original barrier cannot reply after its Job dies. Only arm the
   * existing retirement path after all local producers and that exact Job
   * have independently drained; no remote work is retried here. */
  prepareDeadForMigrationRetirement(): boolean {
    const generation = this.current;
    if (!this.migrationAdmission?.sealed || !generation || generation.closed
      || this.mainControlUncertain || this.rendererRequests !== 0 || this.mainControlRequests !== 0) return false;
    try {
      if (generation.native.activeCount(generation.job) !== 0
        || typeof generation.native.exitCode !== "function" || generation.native.exitCode(generation.job) === null
        || !generation.native.drainStatus(generation.job).complete) return false;
    } catch { return false; }
    generation.migrationRetirementRequested = true;
    generation.abort.abort();
    return true;
  }

  /** Main-only cancelled-exit recovery. An approved exit sealed this stopped
   * host's lifecycle gates, and the retained lease release stayed blocked
   * because Main still counted as the shutdown owner; the exit was then
   * cancelled and the shell survived. Shutdown only owns the retained gates
   * while it is still exiting, so Main hands them back here exactly once per
   * cancelled exit, before rebuilding its resident stack: start() may admit a
   * new generation again instead of refusing forever with CLOSING. A completed
   * exit never reaches this — its gates stay shutdown-owned until the process
   * ends. */
  resumeAfterCancelledExit(): void {
    if (this.view.state !== "stopped") throw new HostError("ASSISTANT_NOT_READY");
    this.lifecycleAdmission = null;
    this.migrationAdmission?.release();
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

  /** Read-only native observation; this is not a held shutdown proof.
   * Producer ambiguity (a write in flight, an admission held, the host
   * leaving its ready generation, or the native side itself reporting
   * "unknown") stays "unknown" and always fails closed. A lost observation
   * (rpc timeout, unparsable payload) while this exact generation is still
   * ready is "unobservable": nothing suggests a producer, so it must not
   * poison another source's idle conclusion. */
  async lifecycleStatus(): Promise<"idle" | "active" | "unknown" | "unobservable"> {
    const generation = this.current;
    if (!generation && this.view.state === "stopped" && !this.starting) return "idle";
    const producerUncertain = () => !generation || this.current !== generation || generation.closed
      || generation.abort.signal.aborted || this.view.state !== "ready" || this.migrationAdmission
      || this.mainControlUncertain || this.rendererMutationRequests > 0 || this.mainControlRequests > 0;
    if (!generation || producerUncertain()) return "unknown";
    try {
      const result = await this.rpc(generation, "/api/assistant/lifecycle-status", "GET", undefined, 2_000, false, 8192);
      if (producerUncertain()) return "unknown";
      if (!object(result) || Object.keys(result).length !== 2 || result.schemaVersion !== 1
        || !["idle", "active", "unknown"].includes(String(result.state))) return "unobservable";
      return result.state as "idle" | "active" | "unknown";
    } catch {
      // A new writer or a host leaving its ready generation keeps the
      // observation ambiguous even if the native reply was lost.
      return producerUncertain() ? "unknown" : "unobservable";
    }
  }

  /** Refuse an in-flight producer instead of waiting while an automatic exit is armed. */
  beginLifecycleAdmission(): ReturnType<AssistantHost["beginMigrationAdmission"]> & { check(): void; commit(): void } {
    if (this.view.state !== "ready" || this.rendererRequests || this.mainControlRequests || this.mainControlUncertain)
      throw new HostError("ASSISTANT_LIFECYCLE_BUSY");
    const admission = this.beginMigrationAdmission();
    const lifecycle = { arrival: false, committed: false };
    this.lifecycleAdmission = lifecycle;
    const check = () => {
      if (this.lifecycleAdmission !== lifecycle || lifecycle.arrival) throw new HostError("ASSISTANT_LIFECYCLE_BUSY");
    };
    return { ...admission, check, commit: () => { check(); lifecycle.committed = true; }, release: () => {
      if (this.lifecycleAdmission === lifecycle) this.lifecycleAdmission = null;
      admission.release();
    } };
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
      const lifecycle = this.lifecycleAdmission;
      if (lifecycle && !LIFECYCLE_READ_OPERATIONS.has(captured.operation)) {
        // Before commit, preserve the original request and veto replacement.
        // Afterwards it was never admitted: the persistent composer retains it.
        if (lifecycle.committed) throw new HostError("ASSISTANT_LIFECYCLE_CLOSING");
        lifecycle.arrival = true;
      }
      const safeWhileWaiting = ["status", "detail", "dispatches", "teamRuns", "config", "approvals", "curation", "operatorAsset", "assistantAvatar", "setManagementPermissionPreset", "budgetParameters", "setBudgetParameters", "usageSummary", "resolveApproval", "previewDispatchApproval", "decideDispatchApproval", "declineDispatchApproval", "stop", "computerState"]
        .includes(captured.operation);
      // Confirmation only settles an existing native waiter; it remains a
      // counted writer in the host barrier even after admission is sealed.
      if (captured.operation === "computerConfirm" || captured.operation === "computerState"
        || (!admission.sealed && safeWhileWaiting)) break;
      await admission.released;
    }
    this.rendererRequests += 1;
    const mutation = !LIFECYCLE_READ_OPERATIONS.has(captured.operation);
    if (mutation) this.rendererMutationRequests += 1;
    try { return await this.requestNow(captured); }
    finally {
      this.rendererRequests -= 1;
      if (mutation) this.rendererMutationRequests -= 1;
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
      case "usageSummary": {
        if (Object.keys(payload).length !== 1 || !ownKeys(payload, ["operation"]))
          throw new HostError("ASSISTANT_USAGE_INVALID");
        const result = await this.rpc(generation, "/api/assistant/usage-summary", "GET", undefined, READ_MS, false, 8192);
        if (!validUsageSummary(result)) throw new HostError("ASSISTANT_RESPONSE_INVALID");
        if (result.sessionId !== generation.sessionId || result.agentId !== generation.agentId)
          throw new HostError("ASSISTANT_IDENTITY_INVALID");
        return result;
      }
      case "budgetParameters":
      case "setBudgetParameters": {
        const write = payload.operation === "setBudgetParameters";
        if (Object.keys(payload).length !== (write ? 3 : 1)
          || !ownKeys(payload, write ? ["operation", "revision", "maxCallsPerTurn"] : ["operation"])
          || write && (!Number.isSafeInteger(payload.revision) || payload.revision < 0
            || payload.maxCallsPerTurn !== null && (!Number.isSafeInteger(payload.maxCallsPerTurn)
              || payload.maxCallsPerTurn < 0 || payload.maxCallsPerTurn > 200)))
          throw new HostError("ASSISTANT_BUDGET_INVALID");
        const result = await this.rpc(generation, "/api/assistant/budget-parameters", write ? "PATCH" : "GET",
          write ? { revision: payload.revision, maxCallsPerTurn: payload.maxCallsPerTurn } : undefined,
          write ? REQUEST_MS : READ_MS, false, 8192);
        if (!object(result) || Object.keys(result).length !== 2 || !ownKeys(result, ["revision", "maxCallsPerTurn"])
          || !Number.isSafeInteger(result.revision) || (result.revision as number) < 0
          || result.maxCallsPerTurn !== null && (!Number.isSafeInteger(result.maxCallsPerTurn)
            || (result.maxCallsPerTurn as number) < 0 || (result.maxCallsPerTurn as number) > 200)
          || write && (result.maxCallsPerTurn !== payload.maxCallsPerTurn
            || (result.revision as number) <= payload.revision))
          throw new HostError("ASSISTANT_RESPONSE_INVALID");
        return result;
      }
      case "setManagementPermissionPreset": {
        if (Object.keys(payload).length !== 3 || !ownKeys(payload, ["operation", "preset", "expectedRevision"])
          || typeof payload.preset !== "string" || !["request_approval", "auto_review", "full_access"].includes(payload.preset)
          || !Number.isSafeInteger(payload.expectedRevision) || payload.expectedRevision < 0)
          throw new HostError("ASSISTANT_PERMISSION_INVALID");
        const result = await this.rpc(generation, "/api/assistant/management-permission", "POST",
          { preset: payload.preset, expectedRevision: payload.expectedRevision }, REQUEST_MS, false, 8192);
        if (!object(result) || Object.keys(result).length !== 2 || !ownKeys(result, ["preset", "revision"])
          || result.preset !== payload.preset || !Number.isSafeInteger(result.revision)
          || (result.revision !== payload.expectedRevision && (result.revision as number) - payload.expectedRevision !== 1))
          throw new HostError("ASSISTANT_RESPONSE_INVALID");
        return result;
      }
      case "setModel": {
        if (Object.keys(payload).length !== 2 || !ownKeys(payload, ["operation", "modelId"])
          || typeof payload.modelId !== "string" || !/^[^\s\x00-\x1f\x7f]{1,200}(?![\s\S])/.test(payload.modelId))
          throw new HostError("ASSISTANT_REQUEST_INVALID");
        const result = await this.rpc(generation, "/api/assistant/model", "POST", { modelId: payload.modelId });
        if (!object(result) || Object.keys(result).length !== 1 || result.modelId !== payload.modelId)
          throw new HostError("ASSISTANT_RESPONSE_INVALID");
        return result;
      }
      case "previewTaskCleanup":
      case "executeTaskCleanup": {
        const execute = payload.operation === "executeTaskCleanup";
        if (!ownKeys(payload, ["operation", "agentId", "directSessionId", "targets", ...(execute ? ["fingerprint"] : [])])
          || payload.agentId !== generation.agentId || payload.directSessionId !== generation.sessionId
          || !Array.isArray(payload.targets) || !payload.targets.length || payload.targets.length > 32
          || execute && (typeof payload.fingerprint !== "string" || !/^[a-f0-9]{64}$/.test(payload.fingerprint)))
          throw new HostError("ASSISTANT_REQUEST_INVALID");
        return await this.rpc(generation, `/api/assistant/task-cleanup/${execute ? "execute" : "preview"}`, "POST",
          { agentId: payload.agentId, directSessionId: payload.directSessionId, targets: payload.targets,
            ...(execute ? { fingerprint: payload.fingerprint } : {}) }, 60_000);
      }
      case "teamRuns": {
        if (!ownKeys(payload, ["operation", "cursor"])
          || Object.prototype.hasOwnProperty.call(payload, "cursor") && (typeof payload.cursor !== "string"
            || !/^[A-Za-z0-9_-]{1,256}(?![\s\S])/.test(payload.cursor))) throw new HostError("ASSISTANT_REQUEST_INVALID");
        const path = "/api/assistant/team-runs" + (payload.cursor === undefined ? "" : `?cursor=${encodeURIComponent(payload.cursor)}`);
        const result = await this.rpc(generation, path, "GET", undefined, READ_MS);
        if (identity(result) !== generation.sessionId
          || (result as { assistant: { agentId: string } }).assistant.agentId !== generation.agentId)
          throw new HostError("ASSISTANT_IDENTITY_INVALID");
        return result;
      }
      case "detail": {
        if (!ownKeys(payload, ["operation", "beforeMessageIndex"]) || payload.beforeMessageIndex !== undefined
          && (!Number.isSafeInteger(payload.beforeMessageIndex) || payload.beforeMessageIndex < 1 || payload.beforeMessageIndex > 2_147_483_647))
          throw new HostError("ASSISTANT_REQUEST_INVALID");
        const path = "/api/assistant/session" + (payload.beforeMessageIndex === undefined ? "" : `?before_message_index=${payload.beforeMessageIndex}`);
        const result = await this.rpc(generation, path, "GET", undefined, READ_MS);
        if (!object(result) || result.id !== generation.sessionId) throw new HostError("ASSISTANT_IDENTITY_INVALID");
        return result;
      }
      case "status":
      case "dispatches":
      case "approvals":
      case "config": {
        if (!ownKeys(payload, ["operation"])) throw new HostError("ASSISTANT_REQUEST_INVALID");
        const paths = { status: "/api/assistant", detail: "/api/assistant/session", dispatches: "/api/assistant/dispatches", config: "/api/assistant/config", approvals: "/api/assistant/approvals" };
        const result = await this.rpc(generation, paths[payload.operation], "GET",
          undefined, payload.operation === "status" ? STATUS_READ_MS : READ_MS);
        if (payload.operation === "status" && (identity(result) !== generation.sessionId || (result as { assistant: { agentId: string } }).assistant.agentId !== generation.agentId)) throw new HostError("ASSISTANT_IDENTITY_INVALID");
        if (payload.operation === "status" && object(result) && object(result.settings)
          && Object.prototype.hasOwnProperty.call(result.settings, "managementPermission")) {
          const permission = result.settings.managementPermission;
          if (!object(permission) || Object.keys(permission).length !== 2 || !ownKeys(permission, ["preset", "revision"])
            || typeof permission.preset !== "string" || !["request_approval", "auto_review", "full_access"].includes(permission.preset)
            || !Number.isSafeInteger(permission.revision) || (permission.revision as number) < 0)
            throw new HostError("ASSISTANT_RESPONSE_INVALID");
        }
        return result;
      }
      case "resolveApproval":
        if (!ownKeys(payload, ["operation", "requestId", "decision"])
          || typeof payload.requestId !== "string" || !/^[A-Za-z0-9_.:-]{1,160}$/.test(payload.requestId)
          || !["accept", "decline"].includes(payload.decision)) throw new HostError("ASSISTANT_REQUEST_INVALID");
        return await this.rpc(generation, "/api/assistant/approvals/decision", "POST",
          { requestId: payload.requestId, decision: payload.decision });
      case "declineDispatchApproval":
        if (Object.keys(payload).length !== 5 || !ownKeys(payload, ["operation", "dispatchId", "taskId", "approvalId", "revision"])
          || typeof payload.dispatchId !== "string" || !/^[A-Za-z0-9][A-Za-z0-9_-]{0,119}(?![\s\S])/.test(payload.dispatchId)
          || typeof payload.taskId !== "string" || !/^[A-Za-z0-9_.:-]{1,160}(?![\s\S])/.test(payload.taskId)
          || typeof payload.approvalId !== "string" || !/^[A-Za-z0-9_.:-]{1,160}(?![\s\S])/.test(payload.approvalId)
          || typeof payload.revision !== "string" || !/^[A-Za-z0-9_.:-]{1,200}(?![\s\S])/.test(payload.revision)) throw new HostError("ASSISTANT_REQUEST_INVALID");
        return await this.rpc(generation, "/api/assistant/dispatches/approval/decline", "POST",
          { dispatchId: payload.dispatchId, taskId: payload.taskId, approvalId: payload.approvalId, revision: payload.revision });
      case "previewDispatchApproval":
      case "decideDispatchApproval": {
        const preview = payload.operation === "previewDispatchApproval";
        const keys = preview ? ["operation", "dispatchId", "taskId", "approvalId"] : ["operation", "dispatchId", "taskId", "approvalId", "revision", "decision"];
        if (Object.keys(payload).length !== keys.length || !ownKeys(payload, keys)
          || typeof payload.dispatchId !== "string" || !/^[A-Za-z0-9][A-Za-z0-9_-]{0,119}(?![\s\S])/.test(payload.dispatchId)
          || typeof payload.taskId !== "string" || !/^[A-Za-z0-9_.:-]{1,160}(?![\s\S])/.test(payload.taskId)
          || typeof payload.approvalId !== "string" || !/^[A-Za-z0-9_.:-]{1,160}(?![\s\S])/.test(payload.approvalId)
          || (!preview && (!/^[a-f0-9]{64}(?![\s\S])/.test(payload.revision) || !["accept", "decline"].includes(payload.decision)))) throw new HostError("ASSISTANT_REQUEST_INVALID");
        const body = preview ? { dispatchId: payload.dispatchId, taskId: payload.taskId, approvalId: payload.approvalId }
          : { dispatchId: payload.dispatchId, taskId: payload.taskId, approvalId: payload.approvalId, revision: payload.revision, decision: payload.decision };
        return await this.rpc(generation, `/api/assistant/dispatches/approval/${preview ? "preview" : "decision"}`, "POST", body, REQUEST_MS, false, preview ? 4 * 1024 * 1024 : 8192);
      }
      case "assistantAvatar": {
        if (Object.keys(payload).length !== 1 || !ownKeys(payload, ["operation"])) throw new HostError("ASSISTANT_REQUEST_INVALID");
        const result = await this.rpc(generation, "/api/assistant/avatar", "GET", undefined, READ_MS);
        if (!object(result) || result.agentId !== generation.agentId) throw new HostError("ASSISTANT_IDENTITY_INVALID");
        return result;
      }
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
          if (!(exact(payload, ["operation", "selectionId", "allowVision"])
              || exact(payload, ["operation", "selectionId", "allowVision", "authorizationRequestId"]))
            || !token(payload.selectionId) || payload.allowVision !== true
            || ("authorizationRequestId" in payload && !token(payload.authorizationRequestId)))
            throw new HostError("ASSISTANT_REQUEST_INVALID");
          path += "/grant"; body = { selectionId: payload.selectionId, allowVision: true,
            ...("authorizationRequestId" in payload ? { authorizationRequestId: payload.authorizationRequestId } : {}) };
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
        if (!object(result) || !(exact(result, ["available", "status", "message", "grantId", "window", "pending"])
          || exact(result, ["available", "status", "message", "grantId", "window", "pending", "authorizationRequest"]))
          || typeof result.available !== "boolean" || typeof result.status !== "string"
          || !["idle", "ready", "working", "waiting_confirmation", "paused", "manual", "ended", "error"].includes(result.status)
          || !bounded(result.message, 2000) || !(result.grantId === null || token(result.grantId))
          || !(result.window === null || validWindow(result.window)) || (result.grantId === null) !== (result.window === null))
          throw new HostError("ASSISTANT_RESPONSE_INVALID");
        if (result.authorizationRequest !== undefined && result.authorizationRequest !== null
          && (!object(result.authorizationRequest) || !exact(result.authorizationRequest, ["id", "agentId", "sessionId", "turnId"])
            || !token(result.authorizationRequest.id) || !token(result.authorizationRequest.agentId)
            || !token(result.authorizationRequest.sessionId) || !token(result.authorizationRequest.turnId)
            || result.grantId !== null || result.pending !== null || !["idle", "ended"].includes(result.status)))
          throw new HostError("ASSISTANT_RESPONSE_INVALID");
        if (result.pending !== null && (!object(result.pending) || !exact(result.pending, ["id", "action", "targetLabel", "text"])
          || !token(result.pending.id) || typeof result.pending.action !== "string"
          || !["click", "set_value", "type_text", "scroll"].includes(result.pending.action)
          || !bounded(result.pending.targetLabel, 400) || !(result.pending.text === null || bounded(result.pending.text, 2000))
          || result.grantId === null || result.status !== "waiting_confirmation")) throw new HostError("ASSISTANT_RESPONSE_INVALID");
        return result;
      }
      case "send": {
        if (!ownKeys(payload, ["operation", "message", "requestId", "attachmentIds", "references", "controlContinuation"])
          || typeof payload.message !== "string" || payload.message.length > 64_000
          || (payload.attachmentIds !== undefined && (!Array.isArray(payload.attachmentIds) || payload.attachmentIds.length > 8
            || payload.attachmentIds.some(id => typeof id !== "string" || !/^[A-Za-z0-9_.-]{1,255}$/.test(id) || id === "." || id === "..")))
          || (payload.references !== undefined && (!Array.isArray(payload.references) || payload.references.length > 8
            || payload.references.some(reference => !object(reference) || JSON.stringify(reference).length > 16_000)))
          || (!payload.message.trim() && !payload.attachmentIds?.length)
          || typeof payload.requestId !== "string" || !/^[A-Za-z0-9_.:-]{1,128}$/.test(payload.requestId)) throw new HostError("ASSISTANT_REQUEST_INVALID");
        if ("controlContinuation" in payload) {
          const expected = payload.controlContinuation;
          if (!object(expected) || Object.keys(expected).length !== 5
            || !ownKeys(expected, ["agentId", "sessionId", "turnId", "headId", "ledgerSeq"])
            || ![expected.agentId, expected.sessionId, expected.turnId, expected.headId].every(value =>
              typeof value === "string" && value.trim() && value === value.trim() && value.length <= 200)
            || [expected.agentId, expected.sessionId, expected.turnId].some(value => value.length > 160)
            || !positiveInteger(expected.ledgerSeq)
            || payload.message !== "控制已交回，请先重新观察当前页面或授权窗口，再继续当前任务；不要重放未经确认的操作。"
            || payload.attachmentIds?.length || payload.references?.length) throw new HostError("ASSISTANT_REQUEST_INVALID");
          if (expected.agentId !== generation.agentId || expected.sessionId !== generation.sessionId)
            throw new HostError("ASSISTANT_IDENTITY_INVALID");
        }
        return await this.rpc(generation, "/api/assistant/messages", "POST", { message: payload.message, requestId: payload.requestId,
          ...(payload.attachmentIds?.length ? { attachmentIds: payload.attachmentIds } : {}),
          ...(payload.references?.length ? { references: payload.references } : {}),
          ...(payload.controlContinuation ? { controlContinuation: payload.controlContinuation } : {}) });
      }
      case "uploadAttachment": {
        if (!ownKeys(payload, ["operation", "filename", "contentType", "dataBase64"])
          || typeof payload.filename !== "string" || !payload.filename.length || payload.filename.length > 255
          || typeof payload.contentType !== "string" || !payload.contentType.length || payload.contentType.length > 128
          || typeof payload.dataBase64 !== "string" || !payload.dataBase64.length
          || payload.dataBase64.length > Math.ceil(8 * 1024 * 1024 / 3) * 4
          || !/^[A-Za-z0-9+/]*={0,2}$/.test(payload.dataBase64) || payload.dataBase64.length % 4 !== 0)
          throw new HostError("ASSISTANT_REQUEST_INVALID");
        const bytes = Buffer.from(payload.dataBase64, "base64");
        if (!bytes.length || bytes.length > 8 * 1024 * 1024 || bytes.toString("base64") !== payload.dataBase64)
          throw new HostError("ASSISTANT_REQUEST_INVALID");
        const result = await this.rpc(generation, "/api/assistant/attachments/upload", "POST",
          { filename: payload.filename, contentType: payload.contentType, dataBase64: payload.dataBase64 });
        if (!object(result) || Object.keys(result).length !== 6
          || !ownKeys(result, ["artifactId", "filename", "contentType", "sizeBytes", "kind", "status"])
          || typeof result.artifactId !== "string" || !/^[A-Za-z0-9_.-]{1,255}$/.test(result.artifactId)
          || result.artifactId === "." || result.artifactId === ".." || typeof result.filename !== "string"
          || typeof result.contentType !== "string" || result.sizeBytes !== bytes.length
          || !["user_image", "user_document"].includes(String(result.kind)) || result.status !== "ready")
          throw new HostError("ASSISTANT_RESPONSE_INVALID");
        return result;
      }
      case "upload_attachment": {
        // Privacy attachment staging: the secret value crosses only this
        // main-process dispatch and the host's closed HTTP link, is never
        // logged, and only the opaque sec_ reference comes back. secretKind
        // is optional: absent stays absent in the forwarded body and the
        // host defaults it to "secret".
        const requestKeys = Object.keys(payload);
        if (!(requestKeys.length === 3 && ownKeys(payload, ["operation", "kind", "value"]))
          && !(requestKeys.length === 4 && (ownKeys(payload, ["operation", "kind", "value", "secretKind"])
            || ownKeys(payload, ["operation", "kind", "value", "label"])))
          && !(requestKeys.length === 5 && ownKeys(payload, ["operation", "kind", "value", "secretKind", "label"])))
          throw new HostError("ASSISTANT_REQUEST_INVALID");
        if (payload.kind !== "user_secret"
          || typeof payload.value !== "string" || !payload.value.trim() || payload.value.length > 8192
          || (payload.secretKind !== undefined
            && !["api_key", "token", "password", "secret"].includes(String(payload.secretKind)))
          || (payload.label !== undefined
            && (typeof payload.label !== "string" || payload.label.length > 160 || /[\u0000-\u001f\u007f]/.test(payload.label))))
          throw new HostError("ASSISTANT_REQUEST_INVALID");
        const result = await this.rpc(generation, "/api/assistant/attachments/upload", "POST",
          { kind: "user_secret", value: payload.value,
            ...(payload.secretKind !== undefined ? { secretKind: payload.secretKind } : {}),
            ...(payload.label !== undefined && payload.label !== "" ? { label: payload.label } : {}) });
        const resultKeys = object(result) ? Object.keys(result) : [];
        if (!object(result) || (resultKeys.length !== 2 && resultKeys.length !== 3)
          || (resultKeys.length === 2 && !ownKeys(result, ["attachmentId", "kind"]))
          || (resultKeys.length === 3 && !ownKeys(result, ["attachmentId", "kind", "label"]))
          || result.kind !== "user_secret"
          || typeof result.attachmentId !== "string" || !/^sec_[A-Za-z0-9_-]{16,64}$/.test(result.attachmentId)
          || (resultKeys.length === 3
            && (typeof result.label !== "string" || result.label.length > 160 || /[\u0000-\u001f\u007f]/.test(result.label))))
          throw new HostError("ASSISTANT_RESPONSE_INVALID");
        return result;
      }
      case "readAttachment": {
        if (!ownKeys(payload, ["operation", "artifactId"]) || typeof payload.artifactId !== "string"
          || !/^[A-Za-z0-9_.-]{1,255}$/.test(payload.artifactId) || payload.artifactId === "." || payload.artifactId === "..")
          throw new HostError("ASSISTANT_REQUEST_INVALID");
        const result = await this.rpc(generation, "/api/assistant/attachments/read", "POST",
          { artifactId: payload.artifactId }, REQUEST_MS, false, 16 * 1024 * 1024);
        if (!object(result) || Object.keys(result).length !== 2 || !ownKeys(result, ["contentType", "dataBase64"])
          || typeof result.contentType !== "string" || !result.contentType.length || result.contentType.length > 128
          || typeof result.dataBase64 !== "string" || !result.dataBase64.length
          || result.dataBase64.length > Math.ceil(8 * 1024 * 1024 / 3) * 4
          || !/^[A-Za-z0-9+/]*={0,2}$/.test(result.dataBase64) || result.dataBase64.length % 4 !== 0)
          throw new HostError("ASSISTANT_RESPONSE_INVALID");
        const bytes = Buffer.from(result.dataBase64, "base64");
        if (!bytes.length || bytes.length > 8 * 1024 * 1024 || bytes.toString("base64") !== result.dataBase64)
          throw new HostError("ASSISTANT_RESPONSE_INVALID");
        return result;
      }
      case "stop":
        if (!ownKeys(payload, ["operation", "turnId"]) || typeof payload.turnId !== "string"
          || !payload.turnId.trim() || payload.turnId.length > 160) throw new HostError("ASSISTANT_REQUEST_INVALID");
        return await this.rpc(generation, "/api/assistant/stop", "POST", { turnId: payload.turnId });
      case "updateQueuedTurn":
      case "removeQueuedTurn":
      case "sendNowQueuedTurn": {
        if (!isAssistantQueuedTurnRequest(payload)) throw new HostError("ASSISTANT_REQUEST_INVALID");
        if (payload.sessionId !== generation.sessionId) throw new HostError("ASSISTANT_SESSION_FORBIDDEN");
        const path = payload.operation === "updateQueuedTurn" ? "update"
          : payload.operation === "removeQueuedTurn" ? "remove" : "send-now";
        const { operation: _operation, sessionId: _sessionId, ...body } = payload;
        const result = await this.rpc(generation, `/api/assistant/queued-turns/${path}`, "POST", body);
        const sendNow = payload.operation === "sendNowQueuedTurn";
        if (!object(result) || Object.keys(result).length !== (sendNow ? 2 : 1)
          || !ownKeys(result, sendNow ? ["queuedTurns", "stopRequested"] : ["queuedTurns"])
          || !Array.isArray(result.queuedTurns) || result.queuedTurns.some(row => !object(row)
            || typeof row.id !== "string" || !row.id)
          || sendNow && typeof result.stopRequested !== "boolean") throw new HostError("ASSISTANT_RESPONSE_INVALID");
        return result;
      }
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
      case "switchHead": {
        if (!ownKeys(payload, ["operation", "nodeId"])
          || typeof payload.nodeId !== "string" || !payload.nodeId.trim()
          || payload.nodeId.length > 200) throw new HostError("ASSISTANT_REQUEST_INVALID");
        const result = await this.rpc(generation, "/api/assistant/head", "POST", { nodeId: payload.nodeId });
        if (!object(result) || result.id !== generation.sessionId) throw new HostError("ASSISTANT_IDENTITY_INVALID");
        return result;
      }
      case "regenerate": {
        if (!ownKeys(payload, ["operation", "messageId", "requestId"])
          || typeof payload.messageId !== "string" || !payload.messageId.trim() || payload.messageId.length > 160
          || typeof payload.requestId !== "string" || !/^[A-Za-z0-9_.:-]{1,128}$/.test(payload.requestId))
          throw new HostError("ASSISTANT_REQUEST_INVALID");
        const result = await this.rpc(generation, "/api/assistant/messages/regenerate", "POST",
          { messageId: payload.messageId, requestId: payload.requestId });
        if (!object(result) || result.id !== generation.sessionId) throw new HostError("ASSISTANT_IDENTITY_INVALID");
        return result;
      }
      case "guidance": {
        if (!ownKeys(payload, ["operation", "content", "mode"])
          || typeof payload.content !== "string" || !payload.content.trim() || payload.content.length > 64_000
          || !["safe", "interrupt"].includes(payload.mode)) throw new HostError("ASSISTANT_REQUEST_INVALID");
        return await this.rpc(generation, "/api/assistant/guidance", "POST",
          { content: payload.content, mode: payload.mode });
      }
      case "curation":
      case "curate":
        if (payload.sessionId !== generation.sessionId) throw new HostError("ASSISTANT_SESSION_FORBIDDEN");
        if (payload.operation === "curation") {
          if (!ownKeys(payload, ["operation", "sessionId"])) throw new HostError("ASSISTANT_REQUEST_INVALID");
          return await this.rpc(generation, "/api/assistant/curation", "GET", undefined, READ_MS);
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
    if (this.options.startupSignal?.aborted || revision !== this.revision) throw new HostError("ASSISTANT_STOPPED");
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
      if (this.options.startupSignal?.aborted || revision !== this.revision) throw new HostError("ASSISTANT_STOPPED");
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
      const nativeAssistantRoot = realpathSync.native(this.options.profileRoot), profileIdentity = this.configurationReferenceProfileIdentity();
      if (this.options.startupSignal?.aborted || revision !== this.revision) throw new HostError("ASSISTANT_STOPPED");
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
        projectRevision: this.projectSnapshot.revision, nativeAssistantRoot, profileIdentity };
      this.current = generation;
      if (!positiveInteger(spawned.pid)) throw new HostError("ASSISTANT_SPAWN_INVALID");
      generation.pid = spawned.pid;
      const deadline = Date.now() + STARTUP_MS;
      while (Date.now() < deadline) {
        if (this.options.startupSignal?.aborted || revision !== this.revision || generation.abort.signal.aborted) throw new HostError("ASSISTANT_STOPPED");
        if (native.activeCount(generation.job) === 0) throw new HostError("ASSISTANT_EXITED");
        const ready = this.readReady(generation);
        if (ready) {
          generation.origin = `http://127.0.0.1:${ready.port}`;
          generation.hostPid = ready.pid;
          try {
            const timeout = Math.max(1, Math.min(2_000, deadline - Date.now()));
            const health = await this.rpc(generation, "/health", "GET", undefined, timeout,
              false, MAX_RESPONSE_BYTES, this.options.startupSignal);
            if (!object(health) || health.status !== "ok" || health.role !== "launcher_assistant" || health.protocolVersion !== 1) throw new HostError("ASSISTANT_HEALTH_INVALID");
            if (this.options.mainControl && health.mainControlVersion !== 1) throw new HostError("ASSISTANT_MAIN_CONTROL_UNAVAILABLE");
            if (this.options.appearanceControl && health.appearanceControlVersion !== 1) throw new HostError("ASSISTANT_APPEARANCE_CONTROL_UNAVAILABLE");
            if (this.options.browserControl && health.browserControlVersion !== 1) throw new HostError("ASSISTANT_BROWSER_CONTROL_UNAVAILABLE");
            if (this.options.initialMigrationControl && health.initialMigrationControlVersion !== 1) throw new HostError("ASSISTANT_INITIAL_MIGRATION_UNAVAILABLE");
            const status = await this.rpc(generation, "/api/assistant", "GET", undefined, Math.max(1, deadline - Date.now()),
              false, MAX_RESPONSE_BYTES, this.options.startupSignal);
            generation.sessionId = identity(status);
            generation.agentId = (status as { assistant: { agentId: string } }).assistant.agentId;
            if (this.options.startupSignal?.aborted || revision !== this.revision || generation.abort.signal.aborted) throw new HostError("ASSISTANT_STOPPED");
            this.view = { state: "ready", errorCode: null };
            if (this.options.mainControl) this.startMainControl(generation);
            generation.readyAt = Date.now();
            this.resetRespawnState();
            this.beginLivenessWatch(generation);
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
          // Startup is still fenced from user work. Ask the captured ready
          // origin to shut down once, even if its health response failed.
          // An unconfirmed request stays unknown; never force or replay it.
          generation.migrationRetirementRequested = true;
          generation.abort.abort();
          if (generation.origin) {
            try { await this.rpc(generation, "/api/assistant/shutdown", "POST", {}, 2_000, true); }
            catch { /* Retain the Job and observe natural exit and output drain. */ }
          }
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

  /** Main-only, read-only; caller owns the current registry lease. */
  async historyReceipt(input: { projectId: string; previewId: string; revision: number }): Promise<unknown> {
    const unknown = { schemaVersion: 1, projectId: input.projectId, previewId: input.previewId,
      state: "unknown", code: "unknown", readyForCutover: false };
    if (!/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$/.test(input.projectId) || !/^[a-f0-9]{64}$/.test(input.previewId)
      || !Number.isSafeInteger(input.revision) || input.revision < 0) return unknown;
    const generation = this.current;
    if (!generation || generation.closed || generation.abort.signal.aborted || this.view.state !== "ready"
      || this.projectsSuspended || generation.projectRevision !== input.revision) return unknown;
    try {
      return await this.rpc(generation, "/api/assistant/history-receipt", "POST", input, REQUEST_MS, false, 8192);
    } catch { return unknown; }
  }

  /** Main-only. Caller owns the registry lease and the native approval policy. */
  async importHistory(input: { projectId: string; previewId: string; turnId: string; operationId: string; revision: number; signal?: AbortSignal }): Promise<unknown> {
    if (!/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$/.test(input.projectId)
      || !/^[a-f0-9]{64}$/.test(input.previewId) || typeof input.turnId !== "string"
      || !/^\S{1,160}$/.test(input.turnId) || !/^[a-f0-9]{32}$/.test(input.operationId) || !Number.isSafeInteger(input.revision) || input.revision < 0) {
      throw new HostError("ASSISTANT_REQUEST_INVALID");
    }
    const generation = this.current;
    if (!generation || generation.closed || generation.abort.signal.aborted || this.view.state !== "ready"
      || this.projectsSuspended || generation.projectRevision !== input.revision) throw new HostError("ASSISTANT_NOT_READY");
    const operationId = input.operationId;
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
        || request.reauthorize !== undefined && (request.reauthorize !== true || request.category !== "reminder_handoff")
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
      ...(request.reauthorize === true ? { reauthorize: true } : {}),
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
    const contexts = new Map<string, ConfigurationReferenceHostContext>();
    if (!generation.controlPump) this.mainControlUncertain = false;
    const pump = new AbortController();
    generation.controlPump = pump;
    const current = () => this.current === generation && !generation.closed && this.view.state === "ready"
      && !generation.abort.signal.aborted && generation.controlPump === pump && !pump.signal.aborted;
    void runMainControlPump({
      signal: generation.abort.signal,
      isCurrent: current,
      invoke: (path, method, body) => this.rpc(generation, path, method, body, MAIN_CONTROL_RPC_MS, false, 8_192, pump.signal),
      onRequest: async (request, signal) => {
        const referenceSettlement = isConfigurationReferenceRequest(request) && request.action !== "configuration_reference_acquire";
        while (this.migrationAdmission && !referenceSettlement) {
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
        try {
          const context = this.configurationReferenceContext(generation);
          if (isConfigurationReferenceRequest(request) && request.action === "configuration_reference_acquire") contexts.set(request.deliveryId, context);
          return await onRequest(request, signal, context);
        }
        finally { this.mainControlRequests -= 1; this.settleMigrationAdmissionDrain(); }
      },
      onSettled: async (request, result, accepted) => {
        if (accepted === undefined && !isConfigurationReferenceRequest(request) && this.current === generation)
          this.mainControlUncertain = true;
        try { await this.options.mainControlSettled?.(request, result, accepted, contexts.get(request.deliveryId)); }
        finally { contexts.delete(request.deliveryId); }
      },
      onProgress: () => {
        if (!current()) return;
        generation.referenceRecovery = false;
        generation.controlRetryMs = 100;
        // A completed claim (or any settled RPC behind one) proves the channel
        // works again: the failure count is consecutive only.
        generation.controlFailures = 0;
      },
      onFailure: (uncertain, error) => {
        if (this.current !== generation || generation.abort.signal.aborted) return;
        generation.lastControlError = controlErrorName(error);
        if (uncertain?.some(request => !isConfigurationReferenceRequest(request))) this.mainControlUncertain = true;
        pump.abort();
        if (generation.referenceLeases?.size || generation.referenceRecovery
            || uncertain?.some(request => isConfigurationReferenceRequest(request))) {
          // A dead Job's leases died with their writer: never reconnect to it.
          if (this.jobExited(generation)) { this.concludeDeadControlRecovery(generation); return; }
          // Retain the exact native writer. Only the transport is replaced;
          // original deliveries are neither retried nor sent to another Job.
          generation.referenceRecovery = true;
          const retry = generation.controlRetryMs ?? 100;
          generation.controlRetryMs = Math.min(1000, retry * 2);
          void sleep(retry, generation.abort.signal).then(() => {
            if (this.current !== generation || generation.closed || generation.abort.signal.aborted
                || this.view.state !== "ready" || generation.controlPump !== pump) return;
            // The retry delay doubles as a settle window: never reconnect a
            // transport to a Job that died meanwhile.
            if (this.jobExited(generation)) { this.concludeDeadControlRecovery(generation); return; }
            this.startMainControl(generation);
          }).catch(() => undefined);
          return;
        }
        // A lifecycle admission always holds a migration admission today; the
        // explicit check keeps that a local guarantee if they are ever split.
        if (this.migrationAdmission || this.lifecycleAdmission) {
          // A failed control pump is not proof that its effects drained. Keep
          // the host and heartbeat alive; migration must remain unavailable.
          this.mainControlUncertain = true;
          return;
        }
        if (this.jobExited(generation)) { this.retireFailedGeneration(generation, true); return; }
        this.noteControlChannelFailure(generation, pump);
      },
    }).catch(() => undefined);
  }

  /** A live host's plain control-channel failure reconnects the transport
   * instead of the old first-failure terminate: tonight one healthy host was
   * killed three times on single RPC hiccups 5-13 minutes apart. The count
   * is consecutive (any successful claim clears it) and survives reconnects;
   * the limit-th failure falls through to the same settle window and
   * control-failure retire the old code ran on the first failure. */
  private noteControlChannelFailure(generation: Generation, pump: AbortController): void {
    generation.controlFailures = (generation.controlFailures ?? 0) + 1;
    const failures = generation.controlFailures;
    console.warn(`ASSISTANT_MAIN_CONTROL phase=channel_failure failures=${failures} limit=${MAIN_CONTROL_FAILURE_LIMIT} `
      + `instanceId=${generation.id} lastError=${JSON.stringify(generation.lastControlError ?? "unknown")}`);
    if (failures >= MAIN_CONTROL_FAILURE_LIMIT) { this.settleMainControlFailure(generation); return; }
    const retry = generation.controlRetryMs ?? 100;
    generation.controlRetryMs = Math.min(1000, retry * 2);
    void sleep(retry, generation.abort.signal).then(() => {
      if (this.current !== generation || generation.closed || generation.abort.signal.aborted
          || this.view.state !== "ready" || generation.controlPump !== pump) return;
      // The retry delay doubles as a settle window: never reconnect a
      // transport to a Job that died meanwhile.
      if (this.jobExited(generation)) { this.concludeDeadControlRecovery(generation); return; }
      this.startMainControl(generation);
    }).catch(() => undefined);
  }

  /** Host death evidence for this exact Job: no live process, or its root
   * handle signaled (a venv pythonw redirector root exits only after its host
   * child; lingering grandchildren can keep accounting above zero). A failed
   * native query is never death. */
  private jobExited(generation: Generation): boolean {
    try {
      return generation.native.activeCount(generation.job) === 0
        || (typeof generation.native.exitCode === "function" && generation.native.exitCode(generation.job) !== null);
    } catch { return false; }
  }

  /** rpc() and the instant probe can both still read a live Job while the host
   * dies, so a failed pump is re-probed for a bounded window. Every step first
   * revalidates ownership: a stopped, retired, already classified or
   * admission-held generation is never classified here. */
  private settleMainControlFailure(generation: Generation): void {
    const owned = () => this.current === generation && !generation.closed && !generation.abort.signal.aborted
      && this.view.state === "ready";
    void (async () => {
      for (let waited = 0; waited < CONTROL_FAILURE_SETTLE_MS; waited += CONTROL_FAILURE_SETTLE_POLL_MS) {
        await sleep(CONTROL_FAILURE_SETTLE_POLL_MS, generation.abort.signal);
        if (!owned()) return;
        if (this.migrationAdmission || this.lifecycleAdmission) { this.mainControlUncertain = true; return; }
        if (this.jobExited(generation)) { this.retireFailedGeneration(generation, true); return; }
      }
      this.retireFailedGeneration(generation, false);
    })().catch(() => undefined);
  }

  /** A held admission owns a Job the pump saw dead during recovery (reference
   * or plain control reconnect): never abort, retire or classify it here; the
   * liveness poll classifies it once the admission is released. Only a
   * lifecycle hold marks control uncertain, so migration's own dead-Job
   * retirement stays available. */
  private concludeDeadControlRecovery(generation: Generation): void {
    if (this.lifecycleAdmission) { this.mainControlUncertain = true; return; }
    if (this.migrationAdmission) return;
    this.retireFailedGeneration(generation, true);
  }

  /** abort, classify, then retire on the serialized Job owner. Classification
   * and any respawn scheduling complete first; a failed retirement only
   * leaves cleanup to the respawn's own previous-generation retirement. A
   * live host retired at the control-failure limit leaves the same on-disk
   * evidence as an unexpected exit: the terminate is deliberate, but without
   * a record the failing RPC stays unattributable. */
  private retireFailedGeneration(generation: Generation, exited: boolean): void {
    generation.abort.abort();
    if (exited) this.handleUnexpectedDeath(generation, "main_control");
    else {
      this.recordHostDeathForensics(generation, "main_control", {
        consecutiveFailures: generation.controlFailures ?? 0,
        lastError: generation.lastControlError ?? "unknown",
      });
      this.view = { state: "failed", errorCode: "ASSISTANT_MAIN_CONTROL_FAILED" };
    }
    // Reuse the same serialized Job owner; never race another retirement or
    // cancel a native project command when only the assistant channel failed.
    const operation = this.serial.then(async () => {
      if (this.current !== generation) return;
      try { await this.retire(generation, false); }
      finally { if (generation.closed && this.current === generation) this.current = null; }
    });
    this.serial = operation.catch(() => undefined);
  }

  private readReady(generation: Generation): { port: number; pid: number } | null {
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
    return { port: ready.port, pid: ready.pid };
  }

  private configurationReferenceContext(generation: Generation): ConfigurationReferenceHostContext {
    const agentId = generation.agentId, sessionId = generation.sessionId;
    const check = () => {
      if (this.current !== generation || generation.closed || generation.abort.signal.aborted || this.view.state !== "ready"
          || !agentId || !sessionId || generation.agentId !== agentId || generation.sessionId !== sessionId
          || realpathSync.native(this.options.profileRoot) !== generation.nativeAssistantRoot
          || this.configurationReferenceProfileIdentity() !== generation.profileIdentity)
        throw new HostError("ASSISTANT_NOT_READY");
    };
    check();
    const contextPath = (contextId: string) => {
      if (!/^cfg-[a-f0-9-]{32,64}$/.test(contextId)) throw new HostError("ASSISTANT_REQUEST_INVALID");
      return `/api/assistant/configuration-reference/contexts/${contextId}`;
    };
    return Object.freeze({ generationId: generation.id, agentId: agentId!, sessionId: sessionId!,
      nativeAssistantRoot: generation.nativeAssistantRoot, signal: generation.abort.signal, check,
      retainLease: () => {
        check(); const retention = Symbol();
        (generation.referenceLeases ??= new Set()).add(retention);
        return () => { generation.referenceLeases?.delete(retention); };
      },
      readWorkComplete: async (contextId: string) => {
        check();
        const result = await this.rpc(generation, contextPath(contextId), "GET", undefined, 1_000, false, 8192);
        check();
        if (!object(result) || Object.keys(result).length !== 4 || !ownKeys(result, ["schemaVersion", "contextId", "known", "workComplete"])
            || result.schemaVersion !== 1 || result.contextId !== contextId || typeof result.known !== "boolean"
            || typeof result.workComplete !== "boolean" || !result.known && result.workComplete)
          throw new HostError("ASSISTANT_RESPONSE_INVALID");
        return result.known && result.workComplete;
      },
      ackWorkComplete: async (contextId: string) => {
        check();
        const result = await this.rpc(generation, `${contextPath(contextId)}/ack`, "POST", { schemaVersion: 1 }, 1_000, false, 8192);
        check();
        if (!object(result) || Object.keys(result).length !== 3 || !ownKeys(result, ["schemaVersion", "contextId", "acknowledged"])
            || result.schemaVersion !== 1 || result.contextId !== contextId || result.acknowledged !== true)
          throw new HostError("ASSISTANT_RESPONSE_INVALID");
      },
      drain: async (signal?: AbortSignal) => {
        while (!generation.referenceDrained) {
          if (signal?.aborted) throw new HostError("ASSISTANT_STOPPED");
          if (this.configurationReferenceJobDrained(generation)) { generation.referenceDrained = true; break; }
          await new Promise<void>(done => { const timer = setTimeout(done, 20); timer.unref?.(); });
        }
      } });
  }

  private configurationReferenceProfileIdentity(): string {
    const stat = statSync(this.options.profileRoot, { bigint: true });
    if (!stat.isDirectory()) throw new HostError("ASSISTANT_NOT_READY");
    return JSON.stringify([stat.dev.toString(), stat.ino.toString(), stat.birthtimeNs.toString()]);
  }

  private configurationReferenceJobDrained(generation: Generation): boolean {
    try {
      const exit = generation.native.exitCode?.(generation.job);
      return generation.native.activeCount(generation.job) === 0 && generation.native.drainStatus(generation.job).complete === true
        && typeof exit === "number" && Number.isSafeInteger(exit);
    } catch { return false; }
  }

  private async rpc(generation: Generation, path: string, method: "GET" | "POST" | "PUT" | "PATCH", body?: object,
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
        // Backend failures carry a structured code that separates retryable
        // states from hard failures: host.py's session error handler responds
        // {"detail":{"code":...}} and its migration middleware responds with an
        // "error" key. Read a bounded error-body prefix; any read or parse
        // failure keeps the legacy status-only mapping below unchanged.
        const failureCode = await (async (): Promise<string | null> => {
          try {
            const reader = response.body?.getReader();
            if (!reader) return null;
            const chunks: Uint8Array[] = [];
            let size = 0;
            try {
              while (true) {
                const part = await reader.read();
                if (part.done) break;
                size += part.value.byteLength;
                if (size > MAX_ERROR_BODY_BYTES) return null;
                chunks.push(part.value);
              }
            } finally { await reader.cancel().catch(() => undefined); reader.releaseLock(); }
            const payload: unknown = JSON.parse(Buffer.concat(chunks).toString("utf8"));
            const code = (value: unknown) => object(value) && typeof value.code === "string" ? value.code : null;
            return object(payload) ? code(payload.detail) ?? code(payload.error) : null;
          } catch { return null; }
        })();
        if (failureCode === "SESSION_CONFLICT") {
          // host.py reports a changed native session as 409 SESSION_CONFLICT on
          // session commands. Message submission is idempotent by requestId, so
          // the renderer may safely retry after refreshing; the ASSISTANT_
          // prefix lets the code cross assistantBridge's renderer allowlist.
          throw new HostError("ASSISTANT_SESSION_CONFLICT");
        }
        // host.py's attachment-read 404 reports the unprefixed ATTACHMENT_NOT_
        // FOUND code. Pass it through under the same name, listed explicitly
        // instead of widening the prefix family: every unprefixed passthrough
        // stays a deliberate, consumed decision.
        if (failureCode === "ATTACHMENT_NOT_FOUND") throw new HostError(failureCode);
        if (failureCode !== null && /^ASSISTANT_[A-Z_]+$/.test(failureCode)) throw new HostError(failureCode);
        if (path === "/api/assistant/budget-parameters") {
          if (response.status === 409) throw new HostError("ASSISTANT_BUDGET_CONFLICT");
          if (response.status === 422) throw new HostError("ASSISTANT_BUDGET_INVALID");
          if (response.status === 503 || response.status === 404) throw new HostError("ASSISTANT_BUDGET_UNAVAILABLE");
        }
        if (path === "/api/assistant/usage-summary") {
          if (response.status === 422) throw new HostError("ASSISTANT_USAGE_INVALID");
          throw new HostError("ASSISTANT_USAGE_UNAVAILABLE");
        }
        if (path === "/api/assistant/management-permission") {
          if (response.status === 409) throw new HostError("ASSISTANT_PERMISSION_CONFLICT");
          if (response.status === 422) throw new HostError("ASSISTANT_PERMISSION_INVALID");
          if (response.status === 503 || response.status === 404) throw new HostError("ASSISTANT_PERMISSION_UNAVAILABLE");
        }
        if (path === "/api/assistant/model") {
          if (response.status === 409) throw new HostError("ASSISTANT_MODEL_BUSY");
          if (response.status === 422) throw new HostError("ASSISTANT_MODEL_INVALID");
          if (response.status === 503) throw new HostError("ASSISTANT_MODEL_UNAVAILABLE");
        }
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
      if (generation.native.activeCount(generation.job) === 0 && generation.native.drainStatus(generation.job).complete) {
        if (this.configurationReferenceJobDrained(generation)) generation.referenceDrained = true;
        return true;
      }
      if (Date.now() >= deadline) return false;
      await sleep(20);
    } while (true);
  }
}
