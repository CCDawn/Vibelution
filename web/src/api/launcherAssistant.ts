import type { ConfigBootstrap, SessionDetail, SessionMessageCurationAction, SessionMessageCurationMutationResponse, SessionMessageCurationResponse, SessionToolApprovalRequest } from "./types";
import type { DesktopPetPreferences } from "../routes/desktopPet/desktopPetPreferences";
import type { SessionContinuationExpectation } from "./chat";

export type LauncherOperatorProfile = {
  displayName: string;
  avatarPreset: "default" | "circle" | "spark" | "codex" | "minimal" | "initial";
};

export type LauncherAssistantStatus = {
  teamRunsVersion?: 1;
  assistantAvatarVersion?: 1;
  assistantAvatarRevision?: string | null;
  operatorAssetsVersion?: 1;
  operatorAssetRevisions?: { avatar: string | null; background: string | null };
  attachmentVersion?: 1;
  operatorProfile?: LauncherOperatorProfile;
  assistant: { agentId: string; directSessionId: string; displayName: string };
  settings?: { ok: boolean; preferences: DesktopPetPreferences; displayName: string; modelId: string };
  patrol?: { state: "ready" | "unavailable"; deliveryStates: Record<string, number> };
};

export type LauncherAssistantAcceptance =
  | { turnId: string; queuedTurnId?: never; clientSubmissionId?: never }
  | { turnId: ""; queuedTurnId: string; clientSubmissionId: string };

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
  | { operation: "status" | "detail" | "dispatches" | "hide" | "approvals" | "openLauncher" | "assistantAvatar" }
  | { operation: "resolveApproval"; requestId: string; decision: "accept" | "decline" }
  | { operation: "previewDispatchApproval"; dispatchId: string; taskId: string; approvalId: string }
  | { operation: "declineDispatchApproval"; dispatchId: string; taskId: string; approvalId: string; revision: string }
  | { operation: "decideDispatchApproval"; dispatchId: string; taskId: string; approvalId: string; revision: string; decision: "accept" | "decline" }
  | { operation: "send"; message: string; requestId: string; attachmentIds?: string[] }
  | { operation: "uploadAttachment"; filename: string; contentType: string; dataBase64: string }
  | { operation: "readAttachment"; artifactId: string }
  | { operation: "stop"; turnId: string }
  | { operation: "continue"; requestId: string; continuation: SessionContinuationExpectation }
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
  | { kind: "dispatch"; projectId: string; dispatchId: string }
  | { kind: "team_run"; projectId: string; requestId: string; originAction: "team_run" | "flow_start"; teamId: string; flowId: string; runId: string };

export function launcherAssistantInvoke(payload: LauncherAssistantRequest): Promise<unknown> {
  return launcherAssistantBridge().invoke(payload);
}

export function launcherAssistantBridge(source: unknown = globalThis): LauncherAssistantBridge {
  const bridge = (source as { vibelutionLauncherAssistant?: Partial<LauncherAssistantBridge> } | null)?.vibelutionLauncherAssistant;
  if (typeof bridge?.invoke !== "function") throw new Error("此页面需要在 Launcher 个人助理窗口中打开。");
  return bridge as LauncherAssistantBridge;
}

function record(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object";
}

/** Session event pushed by the Launcher host (frozen preload contract).
 * `session_detail` is an authoritative snapshot frame, `assistant_delta` an
 * incremental frame, `heartbeat` a ~15s channel-health signal; unknown types
 * are ignored by consumers. Any extra field (such as a delta's `done`) is not
 * part of the contract and must be probed, never assumed. */
export type LauncherAssistantSessionEvent = { type: string; sessionId: string; ledgerSeq?: number; at: number };

/** Progressive enhancement over the preload bridge: an older or degraded shell
 * exposes no `onSessionEvent`, in which case this returns null without throwing
 * so callers keep today's polling behaviour untouched. Malformed frames are
 * dropped at this trust boundary rather than handed to the page. */
export function subscribeLauncherAssistantSessionEvent(
  listener: (event: LauncherAssistantSessionEvent) => void,
  source: unknown = globalThis,
): (() => void) | null {
  const bridge = (source as { vibelutionLauncherAssistant?: { onSessionEvent?: unknown } } | null)?.vibelutionLauncherAssistant;
  const subscribe = bridge?.onSessionEvent;
  if (typeof subscribe !== "function") return null;
  const guarded = (event: unknown) => {
    if (!record(event) || typeof event.type !== "string" || typeof event.sessionId !== "string") return;
    listener(event as LauncherAssistantSessionEvent);
  };
  try {
    const unsubscribe: unknown = subscribe.call(bridge, guarded);
    if (typeof unsubscribe !== "function") return () => {};
    // Teardown runs inside React cleanup; a shell that is already gone must not
    // turn an unmount into an error.
    return () => { try { unsubscribe(); } catch { /* channel already closed */ } };
  } catch {
    return null;
  }
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
  if (result.settings !== undefined) {
    const settings = result.settings;
    if (!record(settings) || typeof settings.ok !== "boolean" || !record(settings.preferences)
      || !["dafeiyu", "xiaoluo"].includes(String(settings.preferences.characterId))
      || ![settings.preferences.showStatus, settings.preferences.showTitles, settings.preferences.showCompletion].every(value => typeof value === "boolean")
      || typeof settings.preferences.idleMessage !== "string" || typeof settings.displayName !== "string" || typeof settings.modelId !== "string") {
      throw new Error("Launcher 个人助理外观设置不可用。");
    }
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

export async function getLauncherAssistantDetail(sessionId: string): Promise<SessionDetail> {
  const result = await launcherAssistantBridge().invoke({ operation: "detail" });
  if (!record(result) || result.id !== sessionId || !Array.isArray(result.messages)) {
    throw new Error("Launcher 返回的会话与个人助理身份不一致。");
  }
  return result as SessionDetail;
}

export async function sendLauncherAssistantMessage(message: string, requestId: string, attachmentIds: string[] = []): Promise<LauncherAssistantAcceptance> {
  if ((!message.trim() && !attachmentIds.length) || !attachmentIds.every(validArtifactId) || !/^[A-Za-z0-9_.:-]{1,128}$/.test(requestId)) throw new Error("消息或请求标识无效。");
  const result = await launcherAssistantBridge().invoke(attachmentIds.length
    ? { operation: "send", message, requestId, attachmentIds } : { operation: "send", message, requestId });
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
      || [row.stepCount, row.attemptCount].some(value => value !== undefined && (!Number.isSafeInteger(value) || (value as number) < 0))
      || row.current !== undefined && row.current !== null && !(typeof row.current === "string" && row.current.length <= 160 || Number.isSafeInteger(row.current) && (row.current as number) >= 0)
      || [row.teamName, row.projectName, row.currentAgentName].some(value => value !== undefined && (typeof value !== "string" || value.length > 160 || /[\u0000-\u001f\u007f-\u009f]/.test(value)))
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
  return { ...result, teamRuns: result.teamRuns.map(row => ({ ...row,
    title: typeof row.title === "string" && Array.from(row.title).length <= 160
      ? row.title.replace(/[\u0000-\u001f\u007f-\u009f\u202a-\u202e\u2066-\u2069]/g, " ") : "",
  })) } as LauncherAssistantTeamRunsPage;
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
