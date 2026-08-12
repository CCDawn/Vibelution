import type { SessionTurnItem } from "../../api/types";

/** Compact active-turn stage labels + heartbeat copy. Pure helpers only. */

export type ActiveTurnStageBarPhase = "sent" | "prepare" | "request" | "thinking";

export const ACTIVE_TURN_STAGE_BAR_PHASES: readonly ActiveTurnStageBarPhase[] = [
  "sent",
  "prepare",
  "request",
  "thinking",
] as const;

export type ActiveTurnStatusMessageLike = {
  turnItems?: readonly SessionTurnItem[] | null;
  status?: string | null;
  metadata?: {
    processStage?: unknown;
  } | null;
};

function compactText(value: unknown) {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

function normalizeStage(value: unknown) {
  return compactText(value).toLowerCase();
}

export function resolveActiveTurnProgressStage(message: ActiveTurnStatusMessageLike): string {
  const items = [...(message.turnItems ?? [])]
    .sort((left, right) => left.sequence - right.sequence || left.revision - right.revision);
  for (let index = items.length - 1; index >= 0; index -= 1) {
    const item = items[index];
    if (item?.type === "status" && normalizeStage(item.code)) {
      return normalizeStage(item.code);
    }
    if (item?.type === "retry") {
      return "model_retry";
    }
    if (item?.type === "tool_call" && item.status === "running") {
      return "tool_running";
    }
  }
  const fromMetadata = normalizeStage(message.metadata?.processStage);
  if (fromMetadata) {
    return fromMetadata;
  }
  // Optimistic pending shells often have empty turnItems + processStage on metadata;
  // fall back to user_submit while pending, otherwise running.
  if (String(message.status ?? "").trim().toLowerCase() === "pending") {
    return "user_submit";
  }
  return "running";
}

export function activeTurnStageBarPhase(stage: string): ActiveTurnStageBarPhase | "other" {
  switch (normalizeStage(stage)) {
    case "user_submit":
      return "sent";
    case "context_prepare":
    case "queued":
    case "agent_prepare":
    case "history_restore":
    case "followup_prepare":
      return "prepare";
    case "model_request":
    case "model_retry":
    case "retrying":
      return "request";
    case "model_thinking":
    case "server_thinking":
    case "reasoning":
      return "thinking";
    default:
      return "other";
  }
}

export function activeTurnStageBarPhaseLabel(
  phase: ActiveTurnStageBarPhase,
  lang: "zh" | "en" | string,
) {
  const zh = lang !== "en";
  switch (phase) {
    case "sent":
      return zh ? "发送" : "Sent";
    case "prepare":
      return zh ? "准备" : "Prepare";
    case "request":
      return zh ? "请求" : "Request";
    case "thinking":
      return zh ? "思考" : "Think";
    default:
      return zh ? "处理" : "Work";
  }
}

export function activeTurnStageLabel(stage: string, lang: "zh" | "en" | string) {
  const zh = lang !== "en";
  switch (normalizeStage(stage)) {
    case "user_submit":
      return zh ? "已发送" : "Sent";
    case "context_prepare":
      return zh ? "准备上下文" : "Preparing context";
    case "queued":
      return zh ? "等待执行" : "Queued";
    case "agent_prepare":
      return zh ? "准备 Agent" : "Preparing agent";
    case "history_restore":
      return zh ? "恢复会话" : "Restoring session";
    case "followup_prepare":
      return zh ? "准备下一步" : "Preparing next step";
    case "model_request":
      return zh ? "请求模型" : "Requesting model";
    case "model_retry":
    case "retrying":
      return zh ? "请求重试" : "Retrying request";
    case "model_thinking":
    case "server_thinking":
    case "reasoning":
      return zh ? "思考中" : "Thinking";
    case "tool_running":
    case "tooling":
      return zh ? "执行工具" : "Running tools";
    case "responding":
      return zh ? "生成回答" : "Generating";
    case "model_failed":
      return zh ? "请求失败" : "Request failed";
    case "running":
      return zh ? "处理中" : "Working";
    default:
      return zh ? "处理中" : "Working";
  }
}

/** Short durable summary for the optimistic status TurnItem. */
export function activeTurnOptimisticStageSummary(stage: string, lang: "zh" | "en" | string = "zh") {
  const zh = lang !== "en";
  switch (normalizeStage(stage)) {
    case "user_submit":
      return zh ? "已发送，正在连接" : "Sent, connecting";
    case "context_prepare":
      return zh ? "正在准备上下文" : "Preparing context";
    case "agent_prepare":
      return zh ? "正在准备 Agent" : "Preparing agent";
    case "model_request":
      return zh ? "正在请求模型" : "Requesting model";
    case "model_thinking":
    case "server_thinking":
    case "reasoning":
      return zh ? "思考中，等待模型输出" : "Thinking, waiting for model output";
    default:
      return activeTurnStageLabel(stage, lang);
  }
}

export function activeTurnElapsedSeconds(startedAt: string | undefined | null, nowMs: number) {
  const raw = compactText(startedAt);
  if (!raw) {
    return null;
  }
  const startedMs = Date.parse(raw);
  if (!Number.isFinite(startedMs)) {
    return null;
  }
  return Math.max(0, Math.floor((nowMs - startedMs) / 1000));
}

export function formatActiveTurnHeartbeatText(
  stage: string,
  elapsedSeconds: number | null,
  lang: "zh" | "en" | string,
) {
  const label = activeTurnStageLabel(stage, lang);
  if (elapsedSeconds == null || !Number.isFinite(elapsedSeconds)) {
    return label;
  }
  return `${label} · ${Math.max(0, Math.floor(elapsedSeconds))}s`;
}

export function buildActiveTurnStageBarItems(
  stage: string,
  lang: "zh" | "en" | string,
): Array<{ phase: ActiveTurnStageBarPhase; label: string; current: boolean; reached: boolean }> {
  const currentPhase = activeTurnStageBarPhase(stage);
  const currentIndex = currentPhase === "other"
    ? -1
    : ACTIVE_TURN_STAGE_BAR_PHASES.indexOf(currentPhase);
  return ACTIVE_TURN_STAGE_BAR_PHASES.map((phase, index) => ({
    phase,
    label: activeTurnStageBarPhaseLabel(phase, lang),
    current: currentIndex >= 0 && index === currentIndex,
    reached: currentIndex >= 0 && index <= currentIndex,
  }));
}
