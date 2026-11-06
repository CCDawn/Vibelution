import type { AgentPermissionPreset, ConfigBootstrap, SessionBudgetParameters, SessionDetail, SessionMessageCurationAction, SessionMessageCurationMutationResponse, SessionMessageCurationResponse, SessionQueuedTurn, SessionReferenceAttachment, SessionToolApprovalRequest, TokenUsageRollup, TokenUsageSample } from "./types";
import type { DesktopPetPreferences } from "../routes/desktopPet/desktopPetPreferences";
import type { SessionContinuationExpectation } from "./chat";

export type LauncherAssistantControlContinuation = {
  agentId: string; sessionId: string; turnId: string; headId: string; ledgerSeq: number;
};
export const LAUNCHER_ASSISTANT_CONTROL_CONTINUATION_MESSAGE = "控制已交回，请先重新观察当前页面或授权窗口，再继续当前任务；不要重放未经确认的操作。";

export function validLauncherAssistantControlContinuation(value: unknown): value is LauncherAssistantControlContinuation {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const fields = value as Record<string, unknown>;
  return Object.keys(fields).length === 5
    && ["agentId", "sessionId", "turnId", "headId"].every(key => typeof fields[key] === "string"
      && Boolean((fields[key] as string).trim()) && fields[key] === (fields[key] as string).trim()
      && (fields[key] as string).length <= (key === "headId" ? 200 : 160))
    && Number.isSafeInteger(fields.ledgerSeq) && (fields.ledgerSeq as number) >= 1;
}

export type LauncherOperatorProfile = {
  displayName: string;
  avatarPreset: "default" | "circle" | "spark" | "codex" | "minimal" | "initial";
};

export type LauncherAssistantModelChoice = {
  modelId: string; label: string; providerLabel: string; isDefault: boolean;
  providerHealthy: boolean; missingApiKey: boolean; availability: string;
};

export type LauncherManagementPermission = { preset: AgentPermissionPreset; revision: number };

export type LauncherAssistantStatus = {
  followupQueueVersion?: 1;
  teamRunsVersion?: 1;
  assistantAvatarVersion?: 1;
  assistantAvatarRevision?: string | null;
  operatorAssetsVersion?: 1;
  operatorAssetRevisions?: { avatar: string | null; background: string | null };
  attachmentVersion?: 1;
  operatorProfile?: LauncherOperatorProfile;
  assistant: { agentId: string; directSessionId: string; displayName: string };
  settings?: { ok: boolean; preferences: DesktopPetPreferences; displayName: string; modelId: string;
    modelChoices?: LauncherAssistantModelChoice[];
    managementPermission?: LauncherManagementPermission;
    /** Dialogue-model image-input capability for the attach gate; null or
     * absent means unknown, which never blocks a send (chat-page parity). */
    supportsImageInput?: boolean | null };
  patrol?: { state: "ready" | "unavailable"; deliveryStates: Record<string, number> };
};

export type LauncherAssistantAcceptance =
  | { turnId: string; queuedTurnId?: never; clientSubmissionId?: never }
  | { turnId: ""; queuedTurnId: string; clientSubmissionId: string };

/** Renderer-side send validation refused the request before any transport or
 * queue use: nothing was sent, so the composer may unlock immediately instead
 * of entering the conservative unconfirmed lock. */
export class LauncherAssistantRejectedError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "LauncherAssistantRejectedError";
  }
}

export type LauncherAssistantDispatch = {
  dispatchId: string;
  title?: string;
  projectId?: string;
  agentId?: string;
  agentName?: string;
  projectName?: string;
  createdAt?: string;
  updatedAt?: string;
  cleanupPending?: boolean;
  nativeTaskId?: string;
  receipt?: { taskId?: string; status?: string; resultSummary?: string; shouldPoll?: boolean; pendingApprovals?: LauncherDispatchApproval[]; error?: string | { message?: string; code?: string } | null } | null;
  lastError?: { message?: string; code?: string } | null;
};

export type LauncherDispatchApproval = {
  approvalId: string;
  toolName: string;
  risk: string;
  targetSummary: Record<string, unknown>;
  revision: string;
  availableDecisions: string[];
};

export type LauncherDispatchApprovalPreview = {
  taskId: string; sessionId: string; agentId: string; requestId: string; turnId: string; callId: string;
  toolName: string; revision: string; approval: string; risk: string; permissionPreset: string;
  decisionFingerprint: string; configRevision: number; configHash: string;
  argumentsJson: string; executionArgumentsJson: string;
};

export type LauncherAssistantRequest =
  | { operation: "previewTaskCleanup" | "executeTaskCleanup"; agentId: string; directSessionId: string; targets: LauncherTaskCleanupTarget[]; fingerprint?: string }
  | { operation: "teamRuns"; cursor?: string }
  | { operation: "setModel"; modelId: string }
  | { operation: "budgetParameters" }
  | { operation: "usageSummary" }
  | { operation: "setBudgetParameters"; revision: number; maxCallsPerTurn: number | null }
  | { operation: "setManagementPermissionPreset"; preset: AgentPermissionPreset; expectedRevision: number }
  | { operation: "detail"; beforeMessageIndex?: number }
  | { operation: "status" | "dispatches" | "hide" | "approvals" | "openLauncher" | "assistantAvatar" }
  | { operation: "resolveApproval"; requestId: string; decision: "accept" | "decline" }
  | { operation: "previewDispatchApproval"; dispatchId: string; taskId: string; approvalId: string }
  | { operation: "declineDispatchApproval"; dispatchId: string; taskId: string; approvalId: string; revision: string }
  | { operation: "decideDispatchApproval"; dispatchId: string; taskId: string; approvalId: string; revision: string; decision: "accept" | "decline" }
  | { operation: "send"; message: string; requestId: string; attachmentIds?: string[]; references?: SessionReferenceAttachment[]; controlContinuation?: LauncherAssistantControlContinuation }
  | { operation: "uploadAttachment"; filename: string; contentType: string; dataBase64: string }
  /** Privacy attachments ride their own closed verb: plaintext never becomes a
   * base64 body, a URL, or any persisted renderer state — the response carries
   * only the staged `sec_` reference (plus the echoed label when one was sent). */
  | { operation: "upload_attachment"; kind: "user_secret"; value: string; label?: string }
  | { operation: "readAttachment"; artifactId: string }
  | { operation: "stop"; turnId: string }
  | { operation: "continue"; requestId: string; continuation: SessionContinuationExpectation }
  | { operation: "switchHead"; nodeId: string }
  | { operation: "regenerate"; messageId: string; requestId: string }
  | { operation: "guidance"; content: string; mode: "safe" | "interrupt" }
  | { operation: "updateQueuedTurn"; sessionId: string; queuedTurnId: string; content?: string; position?: number; status?: "paused" | "queued" }
  | { operation: "removeQueuedTurn"; sessionId: string; queuedTurnId: string }
  | { operation: "sendNowQueuedTurn"; sessionId: string; queuedTurnId: string; expectedTurnId?: string }
  | { operation: "config" }
  | { operation: "operatorAsset"; kind: LauncherOperatorAssetKind }
  | { operation: "computerState" | "computerWindows" }
  | { operation: "computerGrant"; selectionId: string; allowVision: true; authorizationRequestId?: string }
  | { operation: "computerControl"; grantId: string; action: "pause" | "resume" | "takeover" | "return" | "end" }
  | { operation: "computerConfirm"; grantId: string; pendingId: string; approved: boolean }
  | { operation: "curation"; sessionId: string }
  | { operation: "curate"; sessionId: string; messageId: string; action: SessionMessageCurationAction }
  | { operation: "setExpanded"; expanded: boolean };

type LauncherAssistantBridge = { invoke: (payload: LauncherAssistantRequest) => Promise<unknown> };

export type LauncherTaskCleanupTarget =
  | { kind: "dispatch"; projectId: string; dispatchId: string; localOnly?: boolean }
  | { kind: "team_run"; projectId: string; requestId: string; originAction: "team_run" | "flow_start"; teamId?: string; flowId?: string; runId?: string; localOnly?: boolean };

export function launcherAssistantInvoke(payload: LauncherAssistantRequest): Promise<unknown> {
  return launcherAssistantBridge().invoke(payload);
}

export type LauncherAssistantUsageSummary = {
  sessionId: string;
  agentId: string;
  sessionTokenUsage: TokenUsageRollup;
  lastTokenUsage: TokenUsageSample;
};

const usageNumberFields = ["inputTokens", "cachedInputTokens", "cacheReadInputTokens", "cacheCreationInputTokens",
  "uncachedInputTokens", "outputTokens", "reasoningOutputTokens", "totalTokens", "latencyMs"];
const usageRollupCountFields = ["callCount", "observedCallCount", "estimatedCallCount", "missingCallCount",
  "notCalledCount", "cacheObservedInputTokens", "cacheObservedCallCount", "cacheUnobservedCallCount"];
function validUsageProjection(value: unknown, rollup: boolean): boolean {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const row = value as Record<string, unknown>;
  const fields = [...usageNumberFields, "cacheHitRate", "cacheUsageObserved", "cacheUsageMissingReason",
    ...(rollup ? [...usageRollupCountFields, "cacheUsageComplete"] : ["source"])];
  return Object.keys(row).length === fields.length && Object.keys(row).every(key => fields.includes(key))
    && [...usageNumberFields, ...(rollup ? usageRollupCountFields : [])].every(key =>
      Number.isSafeInteger(row[key]) && (row[key] as number) >= 0)
    && typeof row.cacheHitRate === "number" && Number.isFinite(row.cacheHitRate) && row.cacheHitRate >= 0 && row.cacheHitRate <= 1
    && typeof row.cacheUsageObserved === "boolean" && typeof row.cacheUsageMissingReason === "string"
    && ["", "not_called", "provider_cache_usage_missing", "partial_provider_cache_usage"].includes(row.cacheUsageMissingReason)
    && (rollup ? typeof row.cacheUsageComplete === "boolean"
      : typeof row.source === "string" && ["provider_usage", "estimated", "missing", "not_called"].includes(row.source));
}

export async function getLauncherAssistantUsageSummary(): Promise<LauncherAssistantUsageSummary> {
  const result = await launcherAssistantInvoke({ operation: "usageSummary" });
  if (!result || typeof result !== "object" || Array.isArray(result)) throw new Error("ASSISTANT_RESPONSE_INVALID");
  const row = result as Record<string, unknown>;
  if (Object.keys(row).length !== 4
    || !Object.keys(row).every(key => ["sessionId", "agentId", "sessionTokenUsage", "lastTokenUsage"].includes(key))
    || ![row.sessionId, row.agentId].every(id => typeof id === "string" && /^[A-Za-z0-9_-]{1,160}$/.test(id))
    || !validUsageProjection(row.sessionTokenUsage, true) || !validUsageProjection(row.lastTokenUsage, false))
    throw new Error("ASSISTANT_RESPONSE_INVALID");
  return result as LauncherAssistantUsageSummary;
}

function validBudget(value: unknown): value is SessionBudgetParameters {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const row = value as Record<string, unknown>;
  return Object.keys(row).length === 2 && Number.isSafeInteger(row.revision) && (row.revision as number) >= 0
    && (row.maxCallsPerTurn === null || Number.isSafeInteger(row.maxCallsPerTurn)
      && (row.maxCallsPerTurn as number) >= 0 && (row.maxCallsPerTurn as number) <= 200);
}

export async function getLauncherAssistantBudget(): Promise<SessionBudgetParameters> {
  const result = await launcherAssistantInvoke({ operation: "budgetParameters" });
  if (!validBudget(result)) throw new Error("ASSISTANT_RESPONSE_INVALID");
  return result;
}

export const launcherAssistantBudgetQueryKey = (agentId: string, sessionId: string) =>
  ["launcher-assistant", "budget", agentId, sessionId] as const;

export async function setLauncherAssistantBudget(parameters: SessionBudgetParameters): Promise<SessionBudgetParameters> {
  if (!validBudget(parameters)) throw new Error("ASSISTANT_BUDGET_INVALID");
  const result = await launcherAssistantInvoke({ operation: "setBudgetParameters", ...parameters });
  if (!validBudget(result) || result.maxCallsPerTurn !== parameters.maxCallsPerTurn || result.revision <= parameters.revision)
    throw new Error("ASSISTANT_RESPONSE_INVALID");
  return result;
}

export function launcherAssistantBridge(source: unknown = globalThis): LauncherAssistantBridge {
  const bridge = (source as { vibelutionLauncherAssistant?: Partial<LauncherAssistantBridge> } | null)?.vibelutionLauncherAssistant;
  if (typeof bridge?.invoke !== "function") throw new Error("此页面需要在 Launcher 个人助理窗口中打开。");
  return bridge as LauncherAssistantBridge;
}

function record(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object";
}

/** Closed, bounded transport of native assistant deltas. Detail and Journal
 * remain authoritative; missing/oversized delta content requires a refresh. */
export type LauncherAssistantSessionEvent = {
  type: string;
  sessionId: string;
  ledgerSeq?: number;
  connectionEpoch?: number;
  at: number;
  needsRefresh?: true;
} & Partial<Omit<import("./types").SessionAssistantDeltaStreamEvent, "type" | "sessionId" | "ledgerSeq">>;

const assistantEventSequence = (value: unknown): value is number => Number.isSafeInteger(value) && (value as number) >= 0;
const assistantEventIdentity = (value: unknown): value is string => typeof value === "string" && value.length > 0 && value.length <= 256;
const assistantEventRecord = (value: unknown): value is Record<string, unknown> => record(value) && !Array.isArray(value);

function assistantEventItem(value: unknown, sessionId: string, turnId: string): boolean {
  if (!assistantEventRecord(value) || value.version !== 3 || !assistantEventIdentity(value.id)
    || !assistantEventIdentity(value.itemId) || value.sessionId !== sessionId || value.turnId !== turnId
    || !assistantEventSequence(value.revision) || !assistantEventSequence(value.sequence)
    || !["pending", "running", "completed", "failed"].includes(String(value.status))) return false;
  switch (value.type) {
    case "agent_message": return ["commentary", "final_answer"].includes(String(value.phase)) && typeof value.text === "string";
    case "reasoning": return typeof value.text === "string";
    case "tool_call": return assistantEventIdentity(value.callId) && typeof value.toolName === "string";
    case "retry": return assistantEventSequence(value.attempt) && assistantEventIdentity(value.targetItemId) && typeof value.reason === "string";
    case "status": case "error": return typeof value.code === "string" && typeof value.text === "string";
    default: return false;
  }
}

export function parseLauncherAssistantSessionEvent(value: unknown): LauncherAssistantSessionEvent | null {
  if (!assistantEventRecord(value) || !assistantEventIdentity(value.sessionId) || typeof value.type !== "string"
    || !value.type || value.type.length > 80 || typeof value.at !== "number" || !Number.isFinite(value.at)
    || value.ledgerSeq !== undefined && !assistantEventSequence(value.ledgerSeq)
    || value.connectionEpoch !== undefined && (!assistantEventSequence(value.connectionEpoch) || value.connectionEpoch < 1)) return null;
  const base: LauncherAssistantSessionEvent = { type: value.type, sessionId: value.sessionId, at: value.at,
    ...(value.ledgerSeq !== undefined ? { ledgerSeq: value.ledgerSeq as number } : {}),
    ...(value.connectionEpoch !== undefined ? { connectionEpoch: value.connectionEpoch as number } : {}) };
  if (value.needsRefresh === true) base.needsRefresh = true;
  if (value.type !== "assistant_delta") return base;
  const fallback: LauncherAssistantSessionEvent = { ...base, needsRefresh: true,
    ...(assistantEventIdentity(value.turnId) ? { turnId: value.turnId } : {}) };
  if (value.needsRefresh === true || !assistantEventIdentity(value.turnId) || typeof value.done !== "boolean"
    || typeof value.stage !== "string" || value.stage.length > 256 || typeof value.updatedAt !== "string" || value.updatedAt.length > 80
    || !Array.isArray(value.turnItems) || !value.turnItems.every(item => assistantEventItem(item, value.sessionId as string, value.turnId as string))
    || [value.deltaSeq, value.deltaSeqFrom].some(seq => seq !== undefined && !assistantEventSequence(seq))
    || value.streamEncoding !== undefined && value.streamEncoding !== "append-v1"
    || value.turnItemAppends !== undefined && (!Array.isArray(value.turnItemAppends)
      || value.turnItemAppends.some(entry => !assistantEventRecord(entry) || entry.kind !== "append"
        || !assistantEventIdentity(entry.itemId) || !["agent_message", "reasoning"].includes(String(entry.itemType))
        || !assistantEventSequence(entry.baseLength) || !assistantEventSequence(entry.appendedLength)
        || typeof entry.appendedText !== "string" || !entry.appendedText)
      || value.turnItemAppends.length > 0 && value.streamEncoding !== "append-v1")) return fallback;
  const event = { ...base, turnId: value.turnId, stage: value.stage, done: value.done, updatedAt: value.updatedAt,
    turnItems: value.turnItems } as LauncherAssistantSessionEvent;
  for (const key of ["deltaSeq", "deltaSeqFrom", "turnItemAppends", "streamEncoding"] as const) {
    if (value[key] !== undefined) Object.assign(event, { [key]: value[key] });
  }
  try {
    return new TextEncoder().encode(JSON.stringify(event)).byteLength <= 256 * 1024 ? event : fallback;
  } catch { return fallback; }
}

/** An older shell without this verb keeps the existing polling fallback. */
export function subscribeLauncherAssistantSessionEvent(
  listener: (event: LauncherAssistantSessionEvent) => void,
  source: unknown = globalThis,
): (() => void) | null {
  const bridge = (source as { vibelutionLauncherAssistant?: { onSessionEvent?: unknown } } | null)?.vibelutionLauncherAssistant;
  const subscribe = bridge?.onSessionEvent;
  if (typeof subscribe !== "function") return null;
  const guarded = (value: unknown) => {
    const event = parseLauncherAssistantSessionEvent(value);
    if (event) listener(event);
  };
  try {
    const unsubscribe: unknown = subscribe.call(bridge, guarded);
    if (typeof unsubscribe !== "function") return () => {};
    return () => { try { unsubscribe(); } catch { /* channel already closed */ } };
  } catch { return null; }
}

export type LauncherOperatorAssetKind = "avatar" | "background";
export type LauncherOperatorAsset = {
  schemaVersion: 1;
  kind: LauncherOperatorAssetKind;
  image: { url: string; sha256: string } | null;
  readability: "soft" | "standard" | "strong";
};

function exactFields(value: unknown, fields: string[]): value is Record<string, unknown> {
  return record(value) && !Array.isArray(value) && Object.keys(value).length === fields.length
    && fields.every(field => Object.prototype.hasOwnProperty.call(value, field));
}

export function isLauncherManagementPermission(value: unknown): value is LauncherManagementPermission {
  return exactFields(value, ["preset", "revision"])
    && typeof value.preset === "string" && ["request_approval", "auto_review", "full_access"].includes(value.preset)
    && Number.isSafeInteger(value.revision) && (value.revision as number) >= 0;
}

function parseImage(image: unknown, limit: number, allowedTypes: string[]): { url: string; sha256: string } {
  const invalid = () => new Error("Launcher 图片资源不可用，请重试。");
  if (!exactFields(image, ["contentType", "dataBase64", "sha256"])
    || typeof image.contentType !== "string" || !allowedTypes.includes(image.contentType)
    || typeof image.sha256 !== "string" || !/^[a-fA-F0-9]{64}$/.test(image.sha256)
    || typeof image.dataBase64 !== "string") throw invalid();
  const data = image.dataBase64;
  if (!data.length || data.length > Math.ceil(limit / 3) * 4 || data.length % 4 !== 0
    || !/^[A-Za-z0-9+/]*={0,2}$/.test(data)) throw invalid();
  const padding = data.endsWith("==") ? 2 : data.endsWith("=") ? 1 : 0;
  const decodedLength = data.length / 4 * 3 - padding;
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  if (!decodedLength || decodedLength > limit
    || (padding === 2 && alphabet.indexOf(data[data.length - 3]) % 16 !== 0)
    || (padding === 1 && alphabet.indexOf(data[data.length - 2]) % 4 !== 0)) throw invalid();
  try { if (atob(data).length !== decodedLength) throw invalid(); } catch { throw invalid(); }
  return { url: `data:${image.contentType};base64,${data}`, sha256: image.sha256 };
}

/** Only the host-selected native assistant can supply this image. */
export async function getLauncherAssistantAvatar(expectedAgentId: string, options?: { signal?: AbortSignal }): Promise<{ image: { url: string; sha256: string } | null }> {
  options?.signal?.throwIfAborted();
  if (!expectedAgentId.trim()) throw new Error("Launcher 个人助理身份不可用。");
  const result = await launcherAssistantBridge().invoke({ operation: "assistantAvatar" });
  options?.signal?.throwIfAborted();
  if (!exactFields(result, ["schemaVersion", "agentId", "image"]) || result.schemaVersion !== 1 || result.agentId !== expectedAgentId)
    throw new Error("Launcher 图片资源不可用，请重试。");
  const image = result.image === null ? null : parseImage(result.image, 5 * 1024 * 1024, ["image/png", "image/jpeg", "image/webp", "image/svg+xml"]);
  options?.signal?.throwIfAborted();
  return { image };
}

/** Images cross only the fixed-kind Launcher IPC; no URL/path or HTTP fallback. */
export async function getLauncherOperatorAsset(kind: LauncherOperatorAssetKind, options?: { signal?: AbortSignal }): Promise<LauncherOperatorAsset> {
  options?.signal?.throwIfAborted();
  if (kind !== "avatar" && kind !== "background") throw new Error("Launcher 图片类型不可用。");
  const result = await launcherAssistantBridge().invoke({ operation: "operatorAsset", kind });
  options?.signal?.throwIfAborted();
  const invalid = () => new Error("Launcher 图片资源不可用，请重试。");
  if (!exactFields(result, ["schemaVersion", "kind", "image", "readability"])
    || result.schemaVersion !== 1 || result.kind !== kind
    || typeof result.readability !== "string" || !["soft", "standard", "strong"].includes(result.readability)) throw invalid();
  const readability = result.readability as LauncherOperatorAsset["readability"];
  if (result.image === null) return { schemaVersion: 1, kind, image: null, readability };
  const limit = (kind === "avatar" ? 5 : 10) * 1024 * 1024;
  const image = parseImage(result.image, limit, ["image/png", "image/jpeg", "image/webp"]);
  options?.signal?.throwIfAborted();
  return { schemaVersion: 1, kind, readability, image };
}

export async function getLauncherAssistantStatus(): Promise<LauncherAssistantStatus> {
  const result = await launcherAssistantBridge().invoke({ operation: "status" });
  if (!record(result) || !record(result.assistant)
    || ![result.assistant.agentId, result.assistant.directSessionId, result.assistant.displayName].every(value => typeof value === "string" && value.trim())) {
    throw new Error("Launcher 个人助理身份不可用。");
  }
  if (result.teamRunsVersion !== undefined && result.teamRunsVersion !== 1) throw new Error("Launcher 团队运行版本不可用。");
  if (Object.prototype.hasOwnProperty.call(result, "operatorAssetsVersion") && result.operatorAssetsVersion !== 1) {
    throw new Error("Launcher 图片资源版本不可用。");
  }
  if (Object.prototype.hasOwnProperty.call(result, "assistantAvatarVersion") && result.assistantAvatarVersion !== 1)
    throw new Error("Launcher 图片资源版本不可用。");
  if (Object.prototype.hasOwnProperty.call(result, "assistantAvatarRevision")
    && result.assistantAvatarRevision !== null && (typeof result.assistantAvatarRevision !== "string" || !/^[a-f0-9]{64}$/.test(result.assistantAvatarRevision)))
    throw new Error("Launcher 图片资源版本不可用。");
  if (result.operatorAssetRevisions !== undefined) {
    const revisions = result.operatorAssetRevisions;
    if (!record(revisions) || Array.isArray(revisions) || !exactFields(revisions, ["avatar", "background"])
      || ![revisions.avatar, revisions.background].every(value => value === null || (typeof value === "string" && /^[a-f0-9]{64}$/.test(value)))) {
      throw new Error("Launcher 图片资源版本不可用。");
    }
  }
  if (result.attachmentVersion !== undefined && result.attachmentVersion !== 1) throw new Error("Launcher 附件版本不可用。");
  if (result.followupQueueVersion !== undefined && result.followupQueueVersion !== 1) throw new Error("Launcher 队列版本不可用。");
  if (result.settings !== undefined) {
    const settings = result.settings;
    if (!record(settings) || typeof settings.ok !== "boolean" || !record(settings.preferences)
      || !["dafeiyu", "xiaoluo"].includes(String(settings.preferences.characterId))
      || ![settings.preferences.showStatus, settings.preferences.showTitles, settings.preferences.showCompletion].every(value => typeof value === "boolean")
      || typeof settings.preferences.idleMessage !== "string" || typeof settings.displayName !== "string" || typeof settings.modelId !== "string") {
      throw new Error("Launcher 个人助理外观设置不可用。");
    }
    if (settings.modelChoices !== undefined && (!Array.isArray(settings.modelChoices)
      || settings.modelChoices.some(choice => !record(choice) || Array.isArray(choice)
        || !exactFields(choice, ["modelId", "label", "providerLabel", "isDefault", "providerHealthy", "missingApiKey", "availability"])
        || ![choice.modelId, choice.label, choice.providerLabel, choice.availability].every(value => typeof value === "string")
        || ![choice.isDefault, choice.providerHealthy, choice.missingApiKey].every(value => typeof value === "boolean")
        || typeof choice.modelId !== "string" || !choice.modelId.trim()))) {
      throw new Error("Launcher 个人助理模型列表不可用。");
    }
    if (Object.prototype.hasOwnProperty.call(settings, "managementPermission") && !isLauncherManagementPermission(settings.managementPermission))
      throw new Error("Launcher 助理操作权限不可用。");
  }
  if (result.operatorProfile !== undefined) {
    const profile = result.operatorProfile;
    if (!record(profile) || Array.isArray(profile)
      || Object.keys(profile).length !== 2 || !Object.prototype.hasOwnProperty.call(profile, "displayName") || !Object.prototype.hasOwnProperty.call(profile, "avatarPreset")
      || typeof profile.displayName !== "string" || Array.from(profile.displayName).length > 120
      || /[\u0000-\u001f\u007f-\u009f]/.test(profile.displayName)
      || typeof profile.avatarPreset !== "string" || !["default", "circle", "spark", "codex", "minimal", "initial"].includes(profile.avatarPreset)) {
      throw new Error("Launcher operator profile is unavailable.");
    }
  }
  if (result.patrol !== undefined) {
    const patrol = result.patrol;
    if (!record(patrol) || !["ready", "unavailable"].includes(String(patrol.state))
      || !record(patrol.deliveryStates) || Array.isArray(patrol.deliveryStates)
      || Object.values(patrol.deliveryStates).some(value => !Number.isSafeInteger(value) || (value as number) < 0)) {
      throw new Error("Launcher 回执自动汇报状态不可用。");
    }
  }
  return result as LauncherAssistantStatus;
}

/** A CAS write is sent once. Conflicts require a fresh explicit choice. */
export async function setLauncherManagementPermissionPreset(preset: AgentPermissionPreset, expectedRevision: number): Promise<LauncherManagementPermission> {
  if (!isLauncherManagementPermission({ preset, revision: expectedRevision })) throw new Error("ASSISTANT_PERMISSION_INVALID");
  const result = await launcherAssistantBridge().invoke({ operation: "setManagementPermissionPreset", preset, expectedRevision });
  if (!isLauncherManagementPermission(result) || result.preset !== preset
    || result.revision !== expectedRevision && result.revision - expectedRevision !== 1)
    throw new Error("ASSISTANT_RESPONSE_INVALID");
  return result;
}

export async function setLauncherAssistantModel(modelId: string): Promise<{ modelId: string }> {
  if (typeof modelId !== "string" || !/^[^\s\x00-\x1f\x7f]{1,200}(?![\s\S])/.test(modelId))
    throw new Error("请选择可用的助理模型。");
  let result: unknown;
  try { result = await launcherAssistantBridge().invoke({ operation: "setModel", modelId }); }
  catch (error) {
    const message = error instanceof Error ? error.message : "";
    if (message.includes("ASSISTANT_MODEL_BUSY")) throw new Error("请等待助理当前回复完成后再切换模型。");
    if (message.includes("ASSISTANT_MODEL_CONFLICT")) throw new Error("模型设置已在别处更新，请刷新后重新选择。");
    if (message.includes("ASSISTANT_IDENTITY_INVALID")) throw new Error("助理会话身份已失效，本次未切换模型；请刷新或重建助理会话后重试。");
    if (message.includes("ASSISTANT_MODEL_INVALID")) throw new Error("所选模型当前不可用，请刷新后重新选择。");
    throw new Error("助理模型切换尚未确认，请刷新后核对当前模型。");
  }
  if (!record(result) || Array.isArray(result) || !exactFields(result, ["modelId"]) || result.modelId !== modelId)
    throw new Error("助理模型切换尚未确认，请刷新后核对当前模型。");
  return { modelId };
}

export async function getLauncherAssistantDetail(sessionId: string, beforeMessageIndex?: number): Promise<SessionDetail> {
  if (beforeMessageIndex !== undefined && (!Number.isSafeInteger(beforeMessageIndex) || beforeMessageIndex < 1 || beforeMessageIndex > 2_147_483_647))
    throw new Error("历史分页位置无效。");
  const result = await launcherAssistantBridge().invoke(beforeMessageIndex === undefined
    ? { operation: "detail" } : { operation: "detail", beforeMessageIndex });
  if (!record(result) || result.id !== sessionId || !Array.isArray(result.messages)) {
    throw new Error("Launcher 返回的会话与个人助理身份不一致。");
  }
  return result as SessionDetail;
}

/** Reference chips ride the same closed send verb; each entry keeps the chat
 * payload's SessionReferenceAttachment shape, bounded like the chat composer. */
export function validLauncherAssistantReferences(references: SessionReferenceAttachment[] | undefined): references is SessionReferenceAttachment[] {
  return Array.isArray(references) && references.length <= 8 && references.every(reference =>
    record(reference) && typeof reference.kind === "string" && reference.kind.length <= 40
    && typeof (reference.referenceId || reference.sessionId || reference.knowledgeItemId
      || reference.knowledgeBaseId || reference.artifactId || reference.sourceMessageId || "") === "string"
    && String(reference.referenceId || reference.sessionId || reference.knowledgeItemId
      || reference.knowledgeBaseId || reference.artifactId || reference.sourceMessageId || "").trim().length > 0
    && String(reference.referenceId || reference.sessionId || reference.knowledgeItemId
      || reference.knowledgeBaseId || reference.artifactId || reference.sourceMessageId || "").length <= 255);
}

export async function sendLauncherAssistantMessage(message: string, requestId: string, attachmentIds: string[] = [],
                                                   references: SessionReferenceAttachment[] = [],
                                                   controlContinuation?: LauncherAssistantControlContinuation): Promise<LauncherAssistantAcceptance> {
  if ((!message.trim() && !attachmentIds.length && !references.length) || !attachmentIds.every(validArtifactId)
    || !validLauncherAssistantReferences(references)
    || !/^[A-Za-z0-9_.:-]{1,128}$/.test(requestId)
    || (controlContinuation !== undefined && (!validLauncherAssistantControlContinuation(controlContinuation)
      || message !== LAUNCHER_ASSISTANT_CONTROL_CONTINUATION_MESSAGE || attachmentIds.length || references.length))) throw new LauncherAssistantRejectedError("消息或请求标识无效。");
  let result: unknown;
  try { result = await launcherAssistantBridge().invoke({
    operation: "send", message, requestId,
    ...(attachmentIds.length ? { attachmentIds } : {}),
    ...(references.length ? { references } : {}),
    ...(controlContinuation ? { controlContinuation } : {}),
  }); } catch (error) {
    if (controlContinuation && error instanceof Error && (error.message === "ASSISTANT_IDENTITY_INVALID"
      || /^Error invoking remote method '[^']+': (?:Error: )?ASSISTANT_IDENTITY_INVALID$/.test(error.message))) {
      throw new LauncherAssistantRejectedError("会话已变化，本次接续未发送。请在当前会话重新发出指令。");
    }
    throw error;
  }
  if (record(result) && (result.status === "queued" || result.queuedTurnId !== undefined)) {
    if (result.accepted !== true || result.status !== "queued" || result.turnId !== ""
      || typeof result.queuedTurnId !== "string" || !result.queuedTurnId.trim() || result.clientSubmissionId !== requestId) {
      throw new Error("Launcher 尚未确认消息所属队列。");
    }
    return { turnId: "", queuedTurnId: result.queuedTurnId, clientSubmissionId: requestId };
  }
  if (!record(result) || result.accepted !== true || typeof result.turnId !== "string" || !result.turnId.trim()) throw new Error("Launcher 尚未确认消息所属轮次。");
  return { turnId: result.turnId };
}


function validArtifactId(id: string): boolean {
  return typeof id === "string" && /^[A-Za-z0-9_.-]{1,255}$/.test(id) && id !== "." && id !== "..";
}

/** Bytes travel only through the fixed Launcher assistant identity. */
export async function uploadLauncherAttachment(file: File): Promise<string> {
  const dataBase64 = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("无法读取附件。"));
    reader.onload = () => {
      const value = reader.result;
      if (typeof value !== "string" || !value.includes(",")) return reject(new Error("无法读取附件。"));
      resolve(value.slice(value.indexOf(",") + 1));
    };
    reader.readAsDataURL(file);
  });
  const result = await launcherAssistantBridge().invoke({ operation: "uploadAttachment", filename: file.name, contentType: file.type || "application/octet-stream", dataBase64 });
  if (!exactFields(result, ["artifactId", "filename", "contentType", "sizeBytes", "kind", "status"])
    || !validArtifactId(result.artifactId as string) || typeof result.filename !== "string"
    || typeof result.contentType !== "string" || !Number.isSafeInteger(result.sizeBytes)
    || result.sizeBytes !== file.size || !["user_image", "user_document"].includes(String(result.kind)) || result.status !== "ready") {
    throw new Error("Launcher 未确认附件上传。");
  }
  return result.artifactId as string;
}

/** The dialog's optional display name is the only renderer-visible copy — the
 * plaintext value itself never leaves this call's argument position and is
 * never stored, logged or re-read. */
function validSecretReference(id: string): boolean {
  return validArtifactId(id) && /^sec_/.test(id);
}

/** Stages a user secret through its dedicated IPC verb and returns only the
 * opaque `sec_` reference. The response shape is exact-checked so a value can
 * never ride back into the renderer; the host echoes the label as a third key
 * when one was sent, and both shapes are accepted. */
export async function uploadLauncherUserSecret(value: string,
                                              label?: string): Promise<{ attachmentId: string; kind: "user_secret" }> {
  const normalizedValue = String(value ?? "");
  const normalizedLabel = String(label ?? "").trim();
  if (!normalizedValue) throw new Error("请粘贴隐私内容后再提交。");
  if (normalizedLabel.length > 160 || /[\u0000-\u001f\u007f]/.test(normalizedLabel)) throw new Error("显示名无效。");
  let result: unknown;
  try {
    result = await launcherAssistantBridge().invoke({
      operation: "upload_attachment", kind: "user_secret", value: normalizedValue,
      ...(normalizedLabel ? { label: normalizedLabel } : {}),
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "";
    if (message.includes("ASSISTANT_SECRET_")) throw new Error(message);
    throw new Error("隐私附件暂存失败，请重试。");
  }
  if (!record(result) || Array.isArray(result) || result.kind !== "user_secret"
    || typeof result.attachmentId !== "string" || !validSecretReference(result.attachmentId)
    || ![["attachmentId", "kind"], ["attachmentId", "kind", "label"]].some(fields =>
      Object.keys(result).length === fields.length
      && fields.every(field => Object.prototype.hasOwnProperty.call(result, field))
      && (fields.length === 2 || typeof result.label === "string" && result.label.length <= 160))) {
    throw new Error("Launcher 未确认隐私附件暂存。");
  }
  return { attachmentId: result.attachmentId, kind: "user_secret" };
}

/** Never expose native URLs or arbitrary MIME types to the conversation. */
export async function readLauncherAttachment(artifactId: string): Promise<string> {
  if (!validArtifactId(artifactId)) throw new Error("附件标识无效。");
  const result = await launcherAssistantBridge().invoke({ operation: "readAttachment", artifactId });
  if (!exactFields(result, ["contentType", "dataBase64"]) || typeof result.contentType !== "string"
    || typeof result.dataBase64 !== "string" || !result.dataBase64.length || result.dataBase64.length > Math.ceil(8 * 1024 * 1024 / 3) * 4
    || result.dataBase64.length % 4 !== 0 || !/^[A-Za-z0-9+/]*={0,2}$/.test(result.dataBase64)) throw new Error("附件暂不可用。");
  const data = result.dataBase64;
  const padding = data.endsWith("==") ? 2 : data.endsWith("=") ? 1 : 0;
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  const decodedLength = data.length / 4 * 3 - padding;
  if (!decodedLength || decodedLength > 8 * 1024 * 1024
    || (padding === 2 && alphabet.indexOf(data[data.length - 3]) % 16 !== 0)
    || (padding === 1 && alphabet.indexOf(data[data.length - 2]) % 4 !== 0)) throw new Error("附件暂不可用。");
  const mime = ["image/png", "image/jpeg", "image/webp", "image/gif"].includes(result.contentType) ? result.contentType : "application/octet-stream";
  return `data:${mime};base64,${result.dataBase64}`;
}

export async function stopLauncherAssistantTurn(sessionId: string, turnId: string): Promise<SessionDetail> {
  if (!turnId.trim()) throw new Error("停止轮次不可用，请刷新原生会话。");
  const result = await launcherAssistantBridge().invoke({ operation: "stop", turnId });
  if (!record(result) || result.id !== sessionId) throw new Error("Launcher 未确认停止请求所属会话。");
  return result as SessionDetail;
}

export async function continueLauncherAssistantTurn(continuation: SessionContinuationExpectation, requestId: string): Promise<{ turnId: string }> {
  if (!/^[A-Za-z0-9_.:-]{1,128}$/.test(requestId)) throw new Error("继续请求标识无效。");
  const result = await launcherAssistantBridge().invoke({ operation: "continue", requestId, continuation });
  if (!record(result) || result.accepted !== true || result.status === "queued" || result.queuedTurnId !== undefined
    || typeof result.turnId !== "string" || !result.turnId.trim()) throw new Error("Launcher 尚未确认继续请求，请核对同一请求。");
  return { turnId: result.turnId };
}

/** Switch the fixed native conversation to a version leaf. The host returns the
 * republished full snapshot; identity mismatch fails closed like stop. */
export async function switchLauncherAssistantHead(sessionId: string, nodeId: string): Promise<SessionDetail> {
  const normalized = String(nodeId || "").trim();
  if (!normalized || normalized.length > 200) throw new Error("对话版本标识无效。");
  const result = await launcherAssistantBridge().invoke({ operation: "switchHead", nodeId: normalized });
  if (!record(result) || result.id !== sessionId || !Array.isArray(result.messages)) throw new Error("Launcher 未确认版本切换所属会话。");
  return result as SessionDetail;
}

/** Rerun the last user request at the target turn. The request id keeps the
 * send-acceptance contract: a lost ACK replays the same id, never a new one. */
export async function regenerateLauncherAssistantMessage(sessionId: string, messageId: string, requestId: string): Promise<SessionDetail> {
  const normalizedMessageId = String(messageId || "").trim();
  if (!normalizedMessageId || normalizedMessageId.length > 160) throw new Error("消息标识无效。");
  if (!/^[A-Za-z0-9_.:-]{1,128}$/.test(requestId || "")) throw new Error("请求标识无效。");
  const result = await launcherAssistantBridge().invoke({ operation: "regenerate", messageId: normalizedMessageId, requestId });
  if (!record(result) || result.id !== sessionId || !Array.isArray(result.messages)) throw new Error("Launcher 未确认重新生成所属会话。");
  return result as SessionDetail;
}

/** Steer the running native turn (safe) or interrupt it with guidance. */
export async function guideLauncherAssistantTurn(sessionId: string, content: string, mode: "safe" | "interrupt"): Promise<SessionDetail> {
  const normalized = String(content || "");
  if (!normalized.trim() || normalized.length > 64000) throw new Error("引导内容无效。");
  if (!["safe", "interrupt"].includes(mode)) throw new Error("引导模式无效。");
  const result = await launcherAssistantBridge().invoke({ operation: "guidance", content: normalized, mode });
  if (!record(result) || result.id !== sessionId) throw new Error("Launcher 未确认引导所属会话。");
  return result as SessionDetail;
}

function assertQueuedTurnIdentity(sessionId: string, queuedTurnId: string): void {
  if (![sessionId, queuedTurnId].every(value => typeof value === "string"
    && /^[A-Za-z0-9_-]{1,160}(?![\s\S])/.test(value))) throw new Error("ASSISTANT_REQUEST_INVALID");
}

function readLauncherQueuedTurns(result: unknown, sendNow = false): SessionQueuedTurn[] {
  if (!record(result) || Array.isArray(result) || !Array.isArray(result.queuedTurns)
    || Object.keys(result).some(key => key !== "queuedTurns" && !(sendNow && key === "stopRequested"))
    || !result.queuedTurns.every(row => record(row) && !Array.isArray(row)
      && typeof row.id === "string" && /^[A-Za-z0-9_-]{1,160}(?![\s\S])/.test(row.id)
      && Number.isSafeInteger(row.position) && Number(row.position) >= 1 && typeof row.status === "string" && Boolean(row.status)
      && typeof row.content === "string")) throw new Error("ASSISTANT_RESPONSE_INVALID");
  return result.queuedTurns as SessionQueuedTurn[];
}

/** Native queue writes stay behind the Launcher-owned, session-scoped IPC. */
export async function updateLauncherAssistantQueuedTurn(sessionId: string, queuedTurnId: string,
  payload: { content?: string; position?: number; status?: "paused" | "queued" }): Promise<SessionQueuedTurn[]> {
  assertQueuedTurnIdentity(sessionId, queuedTurnId);
  if (!record(payload) || Array.isArray(payload) || !Object.values(payload).some(value => value !== undefined)
    || Object.keys(payload).some(key => !["content", "position", "status"].includes(key))
    || (payload.content !== undefined && (typeof payload.content !== "string" || payload.content.length > 64_000))
    || (payload.position !== undefined && (!Number.isSafeInteger(payload.position) || payload.position < 1))
    || (payload.status !== undefined && !["paused", "queued"].includes(payload.status))) throw new Error("ASSISTANT_REQUEST_INVALID");
  const fields = Object.fromEntries(Object.entries(payload).filter(([, value]) => value !== undefined));
  const result = await launcherAssistantBridge().invoke({ operation: "updateQueuedTurn", sessionId, queuedTurnId, ...fields });
  return readLauncherQueuedTurns(result);
}

export async function removeLauncherAssistantQueuedTurn(sessionId: string, queuedTurnId: string): Promise<SessionQueuedTurn[]> {
  assertQueuedTurnIdentity(sessionId, queuedTurnId);
  return readLauncherQueuedTurns(await launcherAssistantBridge().invoke({ operation: "removeQueuedTurn", sessionId, queuedTurnId }));
}

export async function sendNowLauncherAssistantQueuedTurn(sessionId: string, queuedTurnId: string,
  payload: { expectedTurnId?: string } = {}): Promise<{ queuedTurns: SessionQueuedTurn[]; stopRequested: boolean }> {
  assertQueuedTurnIdentity(sessionId, queuedTurnId);
  if (!record(payload) || Array.isArray(payload) || Object.keys(payload).some(key => key !== "expectedTurnId")
    || (payload.expectedTurnId !== undefined && (typeof payload.expectedTurnId !== "string"
      || !/^[A-Za-z0-9_-]{1,160}(?![\s\S])/.test(payload.expectedTurnId))))
    throw new Error("ASSISTANT_REQUEST_INVALID");
  const result = await launcherAssistantBridge().invoke({ operation: "sendNowQueuedTurn", sessionId, queuedTurnId,
    ...(payload.expectedTurnId === undefined ? {} : { expectedTurnId: payload.expectedTurnId }) });
  const queuedTurns = readLauncherQueuedTurns(result, true);
  if (!record(result) || typeof result.stopRequested !== "boolean") throw new Error("ASSISTANT_RESPONSE_INVALID");
  return { queuedTurns, stopRequested: result.stopRequested };
}

function isApproval(value: unknown, sessionId: string): value is SessionToolApprovalRequest {
  return record(value) && value.sessionId === sessionId && typeof value.requestId === "string" && Boolean(value.requestId)
    && typeof value.turnId === "string" && typeof value.agentId === "string" && typeof value.toolName === "string"
    && typeof value.status === "string" && typeof value.risk === "string" && record(value.argumentSummary)
    && Array.isArray(value.availableDecisions) && value.availableDecisions.every(decision => typeof decision === "string");
}

// Preserve the decline path for a management request whose summary is absent.
// The route must treat the empty summary as unsafe to approve.
function normalizeApprovalSummary(value: unknown): unknown {
  if (record(value) && value.toolName === "personal_assistant_manage_tool" && value.argumentSummary == null) {
    return { ...value, argumentSummary: {} };
  }
  return value;
}

export async function getLauncherAssistantApprovals(sessionId: string): Promise<SessionToolApprovalRequest[]> {
  const result = await launcherAssistantBridge().invoke({ operation: "approvals" });
  if (!Array.isArray(result)) throw new Error("Launcher 待授权请求与个人助理身份不一致。");
  const requests = result.map(normalizeApprovalSummary);
  if (!requests.every(request => isApproval(request, sessionId))) throw new Error("Launcher 待授权请求与个人助理身份不一致。");
  return requests;
}

export async function resolveLauncherAssistantApproval(request: SessionToolApprovalRequest, decision: "accept" | "decline"): Promise<SessionToolApprovalRequest> {
  if (!["accept", "decline"].includes(decision) || request.status !== "pending" || !request.availableDecisions.includes(decision)) throw new Error("此授权决定不可用。");
  const result = normalizeApprovalSummary(await launcherAssistantBridge().invoke({ operation: "resolveApproval", requestId: request.requestId, decision }));
  if (!isApproval(result, request.sessionId) || result.requestId !== request.requestId || result.turnId !== request.turnId || result.agentId !== request.agentId) throw new Error("Launcher 未确认本次授权结果。");
  return result;
}

export type LauncherAssistantTeamRun = {
  teamName?: string;
  projectName?: string;
  current?: number | string | null;
  stepCount?: number;
  attemptCount?: number;
  currentAgentName?: string;
  createdAt?: string;
  updatedAt?: string;
  resultSummary?: string;
  error?: string | { message?: string; code?: string } | null;
  projectId: string;
  requestId: string;
  originAction: "team_run" | "flow_start";
  teamId: string | null;
  flowId: string | null;
  runId: string | null;
  status: string | null;
  revision: string | null;
  title: string;
  readState: "ready" | "unknown";
  observedAt: string | null;
  businessAcceptance: "not_evaluated";
};

export type LauncherAssistantTeamRunsPage = {
  schemaVersion: 1;
  assistant: { agentId: string; directSessionId: string };
  teamRuns: LauncherAssistantTeamRun[];
  offset: number;
  total: number;
  nextCursor: string | null;
  coverage: { kind: "local_associations"; historyComplete: false; legacyUnrecoverable: number; invalidRecords: number };
  state: "ready" | "partial";
};

function teamRunsCursor(value: unknown): { snapshot: string; offset: number } | null {
  if (typeof value !== "string" || !/^[A-Za-z0-9_-]{1,256}$/.test(value)) return null;
  try {
    const decoded: unknown = JSON.parse(atob(value.replace(/-/g, "+").replace(/_/g, "/")));
    if (!exactFields(decoded, ["snapshot", "offset"]) || typeof decoded.snapshot !== "string"
      || !/^[a-f0-9]{64}$/.test(decoded.snapshot) || !Number.isSafeInteger(decoded.offset)
      || (decoded.offset as number) < 0) return null;
    return decoded as { snapshot: string; offset: number };
  } catch { return null; }
}

/** A closed, identity-bound read. Run names are display metadata, never instructions. */
export async function getLauncherAssistantTeamRuns(
  expectedIdentity: { agentId: string; directSessionId: string }, cursor?: string,
): Promise<LauncherAssistantTeamRunsPage> {
  const invalid = () => new Error("Launcher 团队运行暂不可用，请刷新核对。");
  const previous = cursor === undefined ? null : teamRunsCursor(cursor);
  if (!expectedIdentity.agentId || !expectedIdentity.directSessionId || cursor !== undefined && !previous) throw invalid();
  const result = await launcherAssistantBridge().invoke(cursor === undefined ? { operation: "teamRuns" } : { operation: "teamRuns", cursor });
  const count = (value: unknown): value is number => Number.isSafeInteger(value) && (value as number) >= 0;
  const id = (value: unknown): value is string => typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$/.test(value);
  if (!exactFields(result, ["schemaVersion", "assistant", "teamRuns", "offset", "total", "nextCursor", "coverage", "state"])
    || result.schemaVersion !== 1 || !exactFields(result.assistant, ["agentId", "directSessionId"])
    || result.assistant.agentId !== expectedIdentity.agentId || result.assistant.directSessionId !== expectedIdentity.directSessionId
    || !Array.isArray(result.teamRuns) || result.teamRuns.length > 16 || !count(result.offset) || !count(result.total)
    || result.offset !== (previous?.offset ?? 0) || result.offset + result.teamRuns.length > result.total
    || !exactFields(result.coverage, ["kind", "historyComplete", "legacyUnrecoverable", "invalidRecords"])
    || result.coverage.kind !== "local_associations" || result.coverage.historyComplete !== false
    || !count(result.coverage.legacyUnrecoverable) || !count(result.coverage.invalidRecords)
    || !["ready", "partial"].includes(String(result.state))) throw invalid();
  const next = result.nextCursor === null ? null : teamRunsCursor(result.nextCursor);
  if (result.offset + result.teamRuns.length < result.total
    ? !next || !result.teamRuns.length || next.offset !== result.offset + result.teamRuns.length
      || previous !== null && next.snapshot !== previous.snapshot
    : result.nextCursor !== null) throw invalid();
  const keys = ["projectId", "requestId", "originAction", "teamId", "flowId", "runId", "status", "revision", "title", "readState", "observedAt", "businessAcceptance"];
  const optionalKeys = ["teamName", "projectName", "current", "stepCount", "attemptCount", "currentAgentName", "createdAt", "updatedAt", "resultSummary", "error"];
  for (const row of result.teamRuns) {
    if (!record(row) || keys.some(key => !(key in row)) || Object.keys(row).some(key => !keys.includes(key) && !optionalKeys.includes(key)) || !id(row.projectId) || typeof row.requestId !== "string"
      || [row.stepCount, row.attemptCount].some(value => value != null && (!Number.isSafeInteger(value) || (value as number) < 0))
      || row.current !== undefined && row.current !== null && !(typeof row.current === "string" && row.current.length <= 160 || Number.isSafeInteger(row.current) && (row.current as number) >= 0)
      || [row.teamName, row.projectName, row.currentAgentName].some(value => value != null && (typeof value !== "string" || value.length > 160 || /[\u0000-\u001f\u007f-\u009f]/.test(value)))
      || !/^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$/.test(row.requestId) || !["team_run", "flow_start"].includes(String(row.originAction))
      || [row.teamId, row.flowId, row.runId].some(value => value !== null && !id(value))
      || row.status !== null && !id(row.status)
      || row.revision !== null && (typeof row.revision !== "string" || !row.revision.length || row.revision.length > 160 || /[\u0000-\u001f\u007f-\u009f]/.test(row.revision))
      || !["ready", "unknown"].includes(String(row.readState)) || row.businessAcceptance !== "not_evaluated"
      || row.observedAt !== null && (typeof row.observedAt !== "string" || !/^\d{4}-\d{2}-\d{2}T[\d:.]+(?:Z|\+00:00)$/.test(row.observedAt) || !Number.isFinite(Date.parse(row.observedAt)))
      || row.readState === "ready" && (!row.teamId || !row.flowId || !row.runId || !row.status || !row.observedAt)
      || row.readState === "unknown" && (row.status !== null || row.observedAt !== null)) throw invalid();
  }
  // A bad optional label cannot hide an otherwise usable native run reference.
  return { ...result, teamRuns: result.teamRuns.map(row => {
    const normalized = { ...row };
    // Native response models emit null for absent optional display metadata.
    // Keep required nullable run references; UI metadata uses omitted values.
    for (const key of optionalKeys) if (normalized[key] === null) delete normalized[key];
    return { ...normalized, title: typeof row.title === "string" && Array.from(row.title).length <= 160
      ? row.title.replace(/[\u0000-\u001f\u007f-\u009f\u202a-\u202e\u2066-\u2069]/g, " ") : "" };
  }) } as LauncherAssistantTeamRunsPage;
}

export async function getLauncherAssistantDispatches(): Promise<LauncherAssistantDispatch[]> {
  const result = await launcherAssistantBridge().invoke({ operation: "dispatches" });
  if (!record(result) || !Array.isArray(result.dispatches)
    || result.dispatches.some(row => {
      if (!record(row) || typeof row.dispatchId !== "string") return true;
      if (row.receipt == null) return false;
      if (!record(row.receipt) || Array.isArray(row.receipt)) return true;
      const pending = row.receipt.pendingApprovals;
      if (pending === undefined) return false;
      if (!Array.isArray(pending)) return true;
      if (pending.length && (typeof row.nativeTaskId !== "string" || !row.nativeTaskId || row.receipt.taskId !== row.nativeTaskId)) return true;
      return pending.some(item => !record(item) || Array.isArray(item)
        || typeof item.approvalId !== "string" || !item.approvalId || typeof item.toolName !== "string"
        || typeof item.risk !== "string" || !record(item.targetSummary) || Array.isArray(item.targetSummary)
        || typeof item.revision !== "string" || !Array.isArray(item.availableDecisions)
        || item.availableDecisions.some((decision: unknown) => typeof decision !== "string"));
    })) {
    throw new Error("Launcher 派发回执暂不可用。");
  }
  // Titles are optional display metadata. A legacy or malformed title must not
  // hide otherwise valid task identities and receipts.
  return result.dispatches.map(row => {
    if (row.title === undefined || typeof row.title === "string" && row.title.length <= 160) return row;
    const { title: _title, ...reference } = row;
    return reference;
  });
}

export async function previewLauncherDispatchApproval(row: LauncherAssistantDispatch, approval: LauncherDispatchApproval): Promise<LauncherDispatchApprovalPreview> {
  if (!row.nativeTaskId || row.receipt?.taskId !== row.nativeTaskId || !row.agentId
    || !row.receipt.pendingApprovals?.includes(approval)) throw new Error("派遣审批已变化，请刷新回执。");
  const result = await launcherAssistantBridge().invoke({ operation: "previewDispatchApproval", dispatchId: row.dispatchId,
    taskId: row.nativeTaskId, approvalId: approval.approvalId });
  const fields = ["taskId", "sessionId", "agentId", "requestId", "turnId", "callId", "toolName", "revision", "approval", "risk", "permissionPreset", "decisionFingerprint", "configRevision", "configHash", "argumentsJson", "executionArgumentsJson"];
  if (!exactFields(result, fields) || result.taskId !== row.nativeTaskId || result.requestId !== approval.approvalId
    || result.agentId !== row.agentId || result.toolName !== approval.toolName
    || typeof result.revision !== "string" || !/^[a-f0-9]{64}(?![\s\S])/.test(result.revision)
    || typeof result.configRevision !== "number" || !Number.isSafeInteger(result.configRevision) || result.configRevision < 1
    || fields.filter(field => field !== "configRevision").some(field => typeof result[field] !== "string" || !(result[field] as string).length)) {
    throw new Error("完整审批预览不可核对，请刷新回执。");
  }
  try {
    for (const field of ["argumentsJson", "executionArgumentsJson"]) {
      const value: unknown = JSON.parse(result[field] as string);
      if (!record(value) || Array.isArray(value)) throw new Error();
    }
  } catch { throw new Error("完整审批预览不可核对，请刷新回执。"); }
  return result as LauncherDispatchApprovalPreview;
}

export async function decideLauncherDispatchApproval(row: LauncherAssistantDispatch, approval: LauncherDispatchApproval,
  preview: LauncherDispatchApprovalPreview, decision: "accept" | "decline"): Promise<void> {
  if (!row.nativeTaskId || row.receipt?.taskId !== row.nativeTaskId || !row.receipt.pendingApprovals?.includes(approval)
    || preview.taskId !== row.nativeTaskId || preview.requestId !== approval.approvalId || preview.agentId !== row.agentId
    || preview.toolName !== approval.toolName || !/^[a-f0-9]{64}(?![\s\S])/.test(preview.revision)
    || !["accept", "decline"].includes(decision)) throw new Error("派遣审批已变化，请刷新回执。");
  const result = await launcherAssistantBridge().invoke({ operation: "decideDispatchApproval", dispatchId: row.dispatchId,
    taskId: row.nativeTaskId, approvalId: approval.approvalId, revision: preview.revision, decision });
  if (!record(result) || result.dispatchId !== row.dispatchId || result.taskId !== row.nativeTaskId
    || result.approvalId !== approval.approvalId || result.revision !== preview.revision || result.decision !== decision) {
    throw new Error("审批结果未确认，请刷新回执核对。");
  }
}

export function launcherDispatchDeclineRevisionIsValid(revision: unknown): revision is string {
  return typeof revision === "string" && /^[A-Za-z0-9_.:-]{1,200}(?![\s\S])/.test(revision);
}

/** No approval can use this path; the host checks the live task and revision. */
export async function declineLauncherDispatchSummary(row: LauncherAssistantDispatch, approval: LauncherDispatchApproval): Promise<void> {
  if (!row.nativeTaskId || row.receipt?.taskId !== row.nativeTaskId || !row.receipt.pendingApprovals?.includes(approval)
    || !approval.approvalId || !launcherDispatchDeclineRevisionIsValid(approval.revision)
    || !approval.availableDecisions.includes("decline")) throw new Error("派遣审批已变化，请刷新回执。");
  const result = await launcherAssistantBridge().invoke({ operation: "declineDispatchApproval", dispatchId: row.dispatchId,
    taskId: row.nativeTaskId, approvalId: approval.approvalId, revision: approval.revision });
  if (!record(result) || result.dispatchId !== row.dispatchId || result.nativeTaskId !== row.nativeTaskId) {
    throw new Error("审批结果未确认，请刷新回执核对。");
  }
}

export async function setLauncherAssistantExpanded(expanded: boolean): Promise<void> {
  const result = await launcherAssistantBridge().invoke({ operation: "setExpanded", expanded });
  if (!record(result) || result.expanded !== expanded) throw new Error("Launcher 未能调整个人助理窗口。");
}

export async function hideLauncherAssistant(): Promise<void> {
  await launcherAssistantBridge().invoke({ operation: "hide" });
}

export async function openLauncherFromAssistant(): Promise<boolean> {
  const result = await launcherAssistantBridge().invoke({ operation: "openLauncher" });
  if (!exactFields(result, ["opened"]) || typeof result.opened !== "boolean") {
    throw new Error("Launcher 暂时未能打开，请重试。");
  }
  return result.opened;
}

/** The native conversation keeps its normal DTOs, with Launcher as its sole data source. */
export const launcherConversationApi = {
  cacheKey: "launcher-assistant",
  async fetchConfigBootstrap(options?: { signal?: AbortSignal }): Promise<ConfigBootstrap> {
    options?.signal?.throwIfAborted();
    const result = await launcherAssistantBridge().invoke({ operation: "config" });
    options?.signal?.throwIfAborted();
    if (!record(result) || Array.isArray(result) || (result.language !== "zh" && result.language !== "en")) {
      throw new Error("Launcher 配置暂不可用。");
    }
    return result as ConfigBootstrap;
  },
  async fetchMessageCuration(sessionId: string): Promise<SessionMessageCurationResponse> {
    const result = await launcherAssistantBridge().invoke({ operation: "curation", sessionId });
    if (!record(result) || result.sessionId !== sessionId || !Array.isArray(result.items)) throw new Error("Launcher 标注暂不可用。");
    return result as SessionMessageCurationResponse;
  },
  async setMessageCuration(sessionId: string, messageId: string, action: SessionMessageCurationAction): Promise<SessionMessageCurationMutationResponse> {
    const result = await launcherAssistantBridge().invoke({ operation: "curate", sessionId, messageId, action });
    if (!record(result) || result.sessionId !== sessionId || result.messageId !== messageId || result.action !== action) throw new Error("Launcher 未确认标注结果。");
    return result as SessionMessageCurationMutationResponse;
  },
};
