import type { ConfigBootstrap, SessionDetail, SessionMessageCurationAction, SessionMessageCurationMutationResponse, SessionMessageCurationResponse, SessionToolApprovalRequest } from "./types";
import type { DesktopPetPreferences } from "../routes/desktopPet/desktopPetPreferences";
import type { SessionContinuationExpectation } from "./chat";

export type LauncherOperatorProfile = {
  displayName: string;
  avatarPreset: "default" | "circle" | "spark" | "codex" | "minimal" | "initial";
};

export type LauncherAssistantStatus = {
  operatorProfile?: LauncherOperatorProfile;
  assistant: { agentId: string; directSessionId: string; displayName: string };
  settings?: { ok: boolean; preferences: DesktopPetPreferences; displayName: string; modelId: string };
};

export type LauncherAssistantAcceptance =
  | { turnId: string; queuedTurnId?: never; clientSubmissionId?: never }
  | { turnId: ""; queuedTurnId: string; clientSubmissionId: string };

export type LauncherAssistantDispatch = {
  dispatchId: string;
  projectId?: string;
  nativeTaskId?: string;
  receipt?: { status?: string; resultSummary?: string; shouldPoll?: boolean } | null;
  lastError?: { message?: string; code?: string } | null;
};

export type LauncherAssistantRequest =
  | { operation: "status" | "detail" | "dispatches" | "hide" | "approvals" }
  | { operation: "resolveApproval"; requestId: string; decision: "accept" | "decline" }
  | { operation: "send"; message: string; requestId: string }
  | { operation: "stop"; turnId: string }
  | { operation: "continue"; requestId: string; continuation: SessionContinuationExpectation }
  | { operation: "config" }
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

export async function getLauncherAssistantStatus(): Promise<LauncherAssistantStatus> {
  const result = await launcherAssistantBridge().invoke({ operation: "status" });
  if (!record(result) || !record(result.assistant)
    || ![result.assistant.agentId, result.assistant.directSessionId, result.assistant.displayName].every(value => typeof value === "string" && value.trim())) {
    throw new Error("Launcher 个人助理身份不可用。");
  }
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
  return result as LauncherAssistantStatus;
}

export async function getLauncherAssistantDetail(sessionId: string): Promise<SessionDetail> {
  const result = await launcherAssistantBridge().invoke({ operation: "detail" });
  if (!record(result) || result.id !== sessionId || !Array.isArray(result.messages)) {
    throw new Error("Launcher 返回的会话与个人助理身份不一致。");
  }
  return result as SessionDetail;
}

export async function sendLauncherAssistantMessage(message: string, requestId: string): Promise<LauncherAssistantAcceptance> {
  if (!message.trim() || !/^[A-Za-z0-9_.:-]{1,128}$/.test(requestId)) throw new Error("消息或请求标识无效。");
  const result = await launcherAssistantBridge().invoke({ operation: "send", message, requestId });
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

export async function getLauncherAssistantApprovals(sessionId: string): Promise<SessionToolApprovalRequest[]> {
  const result = await launcherAssistantBridge().invoke({ operation: "approvals" });
  if (!Array.isArray(result) || !result.every(request => isApproval(request, sessionId))) throw new Error("Launcher 待授权请求与个人助理身份不一致。");
  return result;
}

export async function resolveLauncherAssistantApproval(request: SessionToolApprovalRequest, decision: "accept" | "decline"): Promise<SessionToolApprovalRequest> {
  if (!["accept", "decline"].includes(decision) || request.status !== "pending" || !request.availableDecisions.includes(decision)) throw new Error("此授权决定不可用。");
  const result = await launcherAssistantBridge().invoke({ operation: "resolveApproval", requestId: request.requestId, decision });
  if (!isApproval(result, request.sessionId) || result.requestId !== request.requestId || result.turnId !== request.turnId || result.agentId !== request.agentId) throw new Error("Launcher 未确认本次授权结果。");
  return result;
}

export async function getLauncherAssistantDispatches(): Promise<LauncherAssistantDispatch[]> {
  const result = await launcherAssistantBridge().invoke({ operation: "dispatches" });
  if (!record(result) || !Array.isArray(result.dispatches)
    || result.dispatches.some(row => !record(row) || typeof row.dispatchId !== "string")) {
    throw new Error("Launcher 派发回执暂不可用。");
  }
  return result.dispatches;
}

export async function setLauncherAssistantExpanded(expanded: boolean): Promise<void> {
  const result = await launcherAssistantBridge().invoke({ operation: "setExpanded", expanded });
  if (!record(result) || result.expanded !== expanded) throw new Error("Launcher 未能调整个人助理窗口。");
}

export async function hideLauncherAssistant(): Promise<void> {
  await launcherAssistantBridge().invoke({ operation: "hide" });
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
