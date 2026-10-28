import type { ConfigBootstrap, SessionDetail, SessionMessageCurationAction, SessionMessageCurationMutationResponse, SessionMessageCurationResponse, SessionToolApprovalRequest } from "./types";
import type { DesktopPetPreferences } from "../routes/desktopPet/desktopPetPreferences";
import type { SessionContinuationExpectation } from "./chat";

export type LauncherOperatorProfile = {
  displayName: string;
  avatarPreset: "default" | "circle" | "spark" | "codex" | "minimal" | "initial";
};

export type LauncherAssistantStatus = {
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
  projectId?: string;
  agentId?: string;
  nativeTaskId?: string;
  receipt?: { taskId?: string; status?: string; resultSummary?: string; shouldPoll?: boolean; pendingApprovals?: LauncherDispatchApproval[] } | null;
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

export type LauncherAssistantRequest =
  | { operation: "status" | "detail" | "dispatches" | "hide" | "approvals" | "openLauncher" }
  | { operation: "resolveApproval"; requestId: string; decision: "accept" | "decline" }
  | { operation: "declineDispatchApproval"; dispatchId: string; taskId: string; approvalId: string; revision: string }
  | { operation: "send"; message: string; requestId: string; attachmentIds?: string[] }
  | { operation: "uploadAttachment"; filename: string; contentType: string; dataBase64: string }
  | { operation: "readAttachment"; artifactId: string }
  | { operation: "stop"; turnId: string }
  | { operation: "continue"; requestId: string; continuation: SessionContinuationExpectation }
  | { operation: "config" }
  | { operation: "operatorAsset"; kind: LauncherOperatorAssetKind }
  | { operation: "computerState" | "computerWindows" }
  | { operation: "computerGrant"; selectionId: string; allowVision: true }
  | { operation: "computerControl"; grantId: string; action: "pause" | "resume" | "takeover" | "return" | "end" }
  | { operation: "computerConfirm"; grantId: string; pendingId: string; approved: boolean }
  | { operation: "curation"; sessionId: string }
  | { operation: "curate"; sessionId: string; messageId: string; action: SessionMessageCurationAction }
  | { operation: "setExpanded"; expanded: boolean };

type LauncherAssistantBridge = { invoke: (payload: LauncherAssistantRequest) => Promise<unknown> };

export function launcherAssistantBridge(source: unknown = globalThis): LauncherAssistantBridge {
  const bridge = (source as { vibelutionLauncherAssistant?: Partial<LauncherAssistantBridge> } | null)?.vibelutionLauncherAssistant;
  if (typeof bridge?.invoke !== "function") throw new Error("此页面需要在 Launcher 个人助理窗口中打开。");
  return bridge as LauncherAssistantBridge;
}

function record(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object";
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
  const image = result.image;
  if (!exactFields(image, ["contentType", "dataBase64", "sha256"])
    || typeof image.contentType !== "string" || !["image/png", "image/jpeg", "image/webp"].includes(image.contentType)
    || typeof image.sha256 !== "string" || !/^[a-fA-F0-9]{64}$/.test(image.sha256)
    || typeof image.dataBase64 !== "string") throw invalid();
  const data = image.dataBase64;
  const limit = (kind === "avatar" ? 5 : 10) * 1024 * 1024;
  if (!data.length || data.length > Math.ceil(limit / 3) * 4 || data.length % 4 !== 0
    || !/^[A-Za-z0-9+/]*={0,2}$/.test(data)) throw invalid();
  const padding = data.endsWith("==") ? 2 : data.endsWith("=") ? 1 : 0;
  const decodedLength = data.length / 4 * 3 - padding;
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  // Reject non-canonical padding bits instead of silently normalizing input.
  if (!decodedLength || decodedLength > limit
    || (padding === 2 && alphabet.indexOf(data[data.length - 3]) % 16 !== 0)
    || (padding === 1 && alphabet.indexOf(data[data.length - 2]) % 4 !== 0)) throw invalid();
  try { if (atob(data).length !== decodedLength) throw invalid(); } catch { throw invalid(); }
  options?.signal?.throwIfAborted();
  return { schemaVersion: 1, kind, readability,
    image: { url: `data:${image.contentType};base64,${data}`, sha256: image.sha256 } };
}

export async function getLauncherAssistantStatus(): Promise<LauncherAssistantStatus> {
  const result = await launcherAssistantBridge().invoke({ operation: "status" });
  if (!record(result) || !record(result.assistant)
    || ![result.assistant.agentId, result.assistant.directSessionId, result.assistant.displayName].every(value => typeof value === "string" && value.trim())) {
    throw new Error("Launcher 个人助理身份不可用。");
  }
  if (Object.prototype.hasOwnProperty.call(result, "operatorAssetsVersion") && result.operatorAssetsVersion !== 1) {
    throw new Error("Launcher 图片资源版本不可用。");
  }
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
  return result.dispatches;
}

export function launcherDispatchRevisionIsValid(revision: unknown): revision is string {
  return typeof revision === "string" && /^[A-Za-z0-9_.:-]{1,200}(?![\s\S])/.test(revision);
}

/** Target-side summaries are not complete action proofs; only decline is exposed. */
export async function declineLauncherDispatchApproval(row: LauncherAssistantDispatch, approval: LauncherDispatchApproval): Promise<void> {
  if (!row.nativeTaskId || row.receipt?.taskId !== row.nativeTaskId
    || !Array.isArray(row.receipt.pendingApprovals) || !row.receipt.pendingApprovals.includes(approval)
    || !approval.approvalId || !launcherDispatchRevisionIsValid(approval.revision)
    || !Array.isArray(approval.availableDecisions) || !approval.availableDecisions.includes("decline")) {
    throw new Error("此派遣审批已变化，请刷新后重试。");
  }
  const result = await launcherAssistantBridge().invoke({ operation: "declineDispatchApproval", dispatchId: row.dispatchId,
    taskId: row.nativeTaskId, approvalId: approval.approvalId, revision: approval.revision });
  if (!record(result) || result.dispatchId !== row.dispatchId || result.nativeTaskId !== row.nativeTaskId) {
    throw new Error("Launcher 未确认本次拒绝，请刷新回执核对。");
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
