import type { SessionTurnItem } from "../../api/types";

/** Compact active-turn stage labels + heartbeat copy. Pure helpers only. */

/** Keep a stage label on screen at least this long before switching (anti-flicker). */
export const ACTIVE_TURN_STAGE_MIN_DWELL_MS = 700;

export type ActiveTurnStageBarPhase = "sent" | "prepare" | "request" | "thinking" | "respond";

export const ACTIVE_TURN_STAGE_BAR_PHASES: readonly ActiveTurnStageBarPhase[] = [
  "sent",
  "prepare",
  "request",
  "thinking",
  "respond",
] as const;

export type ActiveTurnStatusMessageLike = {
  turnItems?: readonly SessionTurnItem[] | null;
  status?: string | null;
  metadata?: {
    processStage?: unknown;
  } | null;
  /**
   * Optional backend contract field naming the model route this turn fell back
   * to. Absent on every current payload; rendered only when both ends exist.
   */
  routeFallback?: ActiveTurnRouteFallback | null;
};

/** Optional backend contract: the turn switched from one model route to another. */
export type ActiveTurnRouteFallback = { from: string; to: string };

/**
 * A running turn whose last applied assistant delta is this old gets an
 * explicit "no output — you can stop" upgrade. 90s comfortably covers long
 * tool runs and thinking phases that legitimately stream nothing; the backend
 * journal keeps generating through silence, so the honest UI move past this
 * point is to surface the stall instead of an endlessly counting heartbeat.
 */
export const ACTIVE_TURN_NO_DELTA_STALL_AFTER_MS = 90_000;

function compactText(value: unknown) {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

function normalizeStage(value: unknown) {
  return compactText(value).toLowerCase();
}

export type ActiveTurnRetryProgress = {
  attempt: number;
  maxAttempts: number;
};

/**
 * ZCode-aligned retry visibility: the first two short recoveries are
 * indistinguishable from a normal load for the user, so they stay silent on
 * the heartbeat. Only from the third attempt onward does the turn surface a
 * visible "第 X/N 次重试" counter.
 */
export const MIN_VISIBLE_API_RETRY_ATTEMPT = 3;

const RETRY_STAGE_NAMES = ["model_retry", "retrying"];

function turnItemLooksLikeRetry(item: SessionTurnItem) {
  if (item.type === "retry") {
    return true;
  }
  if (item.type !== "status") {
    return false;
  }
  const haystack = [item.code, item.title, item.summary, item.text]
    .map(normalizeStage)
    .join(" ");
  return RETRY_STAGE_NAMES.some((stage) => haystack.includes(stage))
    || haystack.includes("模型连接正在重试")
    || haystack.includes("请求重试");
}

function parseRetryProgress(...values: unknown[]): ActiveTurnRetryProgress | null {
  const content = values.map((value) => String(value ?? "")).join("\n");
  const zh = content.match(/第\s*(\d+)\s*\/\s*(\d+)\s*次/);
  if (zh) {
    return { attempt: Number(zh[1]), maxAttempts: Number(zh[2]) };
  }
  const en = content.match(/attempt\s+(\d+)\s*\/\s*(\d+)/i);
  if (en) {
    return { attempt: Number(en[1]), maxAttempts: Number(en[2]) };
  }
  const loose = content.match(/(\d+)\s*\/\s*(\d+)/);
  if (loose) {
    return { attempt: Number(loose[1]), maxAttempts: Number(loose[2]) };
  }
  return null;
}

/**
 * Latest retry attempt carried by the active turn items.  Structured fields
 * win; text parsing is the compatibility path for older emitters.
 */
export function resolveActiveTurnRetryProgress(
  message: ActiveTurnStatusMessageLike,
): ActiveTurnRetryProgress | null {
  const items = [...(message.turnItems ?? [])]
    .sort((left, right) => left.sequence - right.sequence || left.revision - right.revision);
  for (let index = items.length - 1; index >= 0; index -= 1) {
    const item = items[index];
    if (!item || !turnItemLooksLikeRetry(item)) {
      continue;
    }
    const metadata = item.metadata ?? {};
    const structuredAttempt = item.type === "retry"
      ? Number(item.attempt)
      : Number(metadata.attempt ?? 0);
    const structuredMax = Number(metadata.maxAttempts ?? metadata.max_attempts ?? 0);
    if (structuredAttempt > 0) {
      return {
        attempt: structuredAttempt,
        maxAttempts: structuredMax >= structuredAttempt ? structuredMax : structuredAttempt,
      };
    }
    const parsed = parseRetryProgress(
      item.summary,
      item.title,
      item.type === "retry"
        ? item.reason
        : item.type === "status" || item.type === "error" || item.type === "agent_message" || item.type === "reasoning"
          ? item.text
          : "",
    );
    if (parsed) {
      return parsed;
    }
  }
  return null;
}

/**
 * Retry progress worth showing on the heartbeat, or null while the current
 * retry is still inside the silent first-attempts window. `null` progress
 * (no attempt number known) stays silent too: an uncounted "retrying" line is
 * exactly the noise this gate exists to remove.
 */
export function visibleActiveTurnRetryProgress(
  progress: ActiveTurnRetryProgress | null | undefined,
): ActiveTurnRetryProgress | null {
  return progress && progress.attempt >= MIN_VISIBLE_API_RETRY_ATTEMPT ? progress : null;
}

function isRetryStageName(stage: string) {
  return RETRY_STAGE_NAMES.includes(normalizeStage(stage));
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
    case "working":
      return "prepare";
    case "model_request":
    case "model_retry":
    case "retrying":
      return "request";
    case "model_thinking":
    case "server_thinking":
    case "reasoning":
    case "thinking":
      return "thinking";
    // The backend emits a `responding` status row on the first answer delta;
    // `assistant_response` is the legacy transport stage the live-output state
    // keeps during answer streaming — both belong to the respond phase.
    case "responding":
    case "assistant_response":
      return "respond";
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
    case "respond":
      return zh ? "回答" : "Respond";
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
      return zh ? "排队中" : "Queued";
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
    case "thinking":
      return zh ? "思考中" : "Thinking";
    case "working":
      return zh ? "处理中" : "Working";
    case "tool_running":
    case "tooling":
      return zh ? "执行工具" : "Running tools";
    case "responding":
    // Legacy transport stage for answer streaming (backend keeps it on the
    // live-output state; the visible responding row drives the chip).
    case "assistant_response":
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

/**
 * Anti-flicker plan for switching the displayed stage.  A stage that just
 * appeared stays visible until the minimum dwell elapses; only then may the
 * next stage replace it.
 */
export function planActiveTurnStageSwitch(
  currentStage: string,
  incomingStage: string,
  shownForMs: number,
  minDwellMs: number = ACTIVE_TURN_STAGE_MIN_DWELL_MS,
) {
  if (incomingStage === currentStage) {
    return { stage: currentStage, delayMs: 0 };
  }
  if (shownForMs >= minDwellMs) {
    return { stage: incomingStage, delayMs: 0 };
  }
  return { stage: currentStage, delayMs: minDwellMs - shownForMs };
}

export function formatActiveTurnHeartbeatText(
  stage: string,
  elapsedSeconds: number | null,
  lang: "zh" | "en" | string,
  retryProgress?: ActiveTurnRetryProgress | null,
) {
  const zh = lang !== "en";
  // Only counted retries from the third attempt onward earn a visible counter;
  // the silent early attempts keep the plain request wording so the heartbeat
  // does not advertise recoveries the user never needed to know about.
  const visibleRetry = visibleActiveTurnRetryProgress(retryProgress ?? null);
  let head: string;
  if (visibleRetry) {
    // Stable count only — backend pushes a point-in-time snapshot, never a
    // per-second countdown, so no delay seconds are invented here.
    head = zh
      ? `第 ${visibleRetry.attempt}/${Math.max(visibleRetry.attempt, visibleRetry.maxAttempts)} 次重试`
      : `Retrying (attempt ${visibleRetry.attempt}/${Math.max(visibleRetry.attempt, visibleRetry.maxAttempts)})`;
  } else if (isRetryStageName(stage)) {
    head = activeTurnStageLabel("model_request", lang);
  } else {
    head = activeTurnStageLabel(stage, lang);
  }
  if (elapsedSeconds == null || !Number.isFinite(elapsedSeconds)) {
    return head;
  }
  return `${head} · ${Math.max(0, Math.floor(elapsedSeconds))}s`;
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

/**
 * Normalized route-fallback notice for the active turn, or null when the
 * optional backend field is missing/incomplete (must render nothing).
 */
export function resolveActiveTurnRouteFallback(
  message: Pick<ActiveTurnStatusMessageLike, "routeFallback">,
): ActiveTurnRouteFallback | null {
  const from = compactText(message.routeFallback?.from);
  const to = compactText(message.routeFallback?.to);
  return from && to ? { from, to } : null;
}

/**
 * Seconds since the guarded stream dropped, while it is reconnecting.
 * `streamConnected !== false` (healthy or unknown) renders nothing; a missing
 * timestamp still yields 0s so the "reconnecting" copy can show immediately.
 */
export function resolveActiveTurnDisconnectSeconds(input: {
  streamConnected?: boolean;
  streamDisconnectedSinceMs?: number | null;
  nowMs: number;
}): number | null {
  if (input.streamConnected !== false) {
    return null;
  }
  const sinceMs = Number(input.streamDisconnectedSinceMs);
  if (!Number.isFinite(sinceMs) || sinceMs <= 0) {
    return 0;
  }
  return Math.max(0, Math.floor((input.nowMs - sinceMs) / 1000));
}

/**
 * Cooldown after a manual reconnect click: the button stays disabled so a
 * stuck transport cannot be hammered; the state flipping back to connected
 * clears it earlier through the advisory unmounting.
 */
export const ACTIVE_TURN_RECONNECT_ACTION_COOLDOWN_MS = 2_000;

/**
 * Whether the disconnect advisory earns its manual "reconnect now" affordance:
 * only a real reconnect loop (disconnectSeconds from
 * `resolveActiveTurnDisconnectSeconds`) with the stream-owner callback wired
 * through ActiveTurnStreamState. Without the callback there is nothing to
 * invoke, so the chip stays informational.
 */
export function shouldShowActiveTurnReconnectAction(input: {
  disconnectSeconds: number | null;
  hasReconnectHandler: boolean;
}): boolean {
  return input.disconnectSeconds !== null && input.hasReconnectHandler;
}

/**
 * Seconds the running turn has produced no assistant delta, once past the
 * stall threshold; null while output is fresh (or before the threshold).
 * The baseline is the fresher of the last applied delta and the turn start,
 * so a turn that never streamed a delta still escalates off its start time.
 */
export function resolveActiveTurnStallSeconds(input: {
  lastAssistantDeltaAtMs?: number | null;
  turnStartedAt?: string | null;
  nowMs: number;
  stallAfterMs?: number;
}): number | null {
  const candidates: number[] = [];
  const deltaAtMs = Number(input.lastAssistantDeltaAtMs);
  if (Number.isFinite(deltaAtMs) && deltaAtMs > 0) {
    candidates.push(deltaAtMs);
  }
  const startedRaw = compactText(input.turnStartedAt);
  if (startedRaw) {
    const startedMs = Date.parse(startedRaw);
    if (Number.isFinite(startedMs)) {
      candidates.push(startedMs);
    }
  }
  if (candidates.length === 0) {
    return null;
  }
  const lastActivityMs = Math.max(...candidates);
  const stalledForMs = input.nowMs - lastActivityMs;
  const thresholdMs = input.stallAfterMs ?? ACTIVE_TURN_NO_DELTA_STALL_AFTER_MS;
  if (stalledForMs <= thresholdMs) {
    return null;
  }
  return Math.max(0, Math.floor(stalledForMs / 1000));
}

/**
 * Stage gate for the no-output stall advisory: only the body-streaming stages
 * earn the "can stop" hint. Silence during thinking / tool / queue phases is
 * the normal shape of an agentic turn (ZCode itself renders no user-visible
 * stall warning, only stream-drop recovery; the backend idle watchdog owns
 * real dead-stream detection), so warning there would be noise.
 */
export function shouldShowNoOutputStall(stage: string): boolean {
  const normalized = normalizeStage(stage);
  return normalized === "responding" || normalized === "assistant_response";
}

/**
 * Seconds elapsed inside the current thinking segment (ZCode reasoning-block
 * semantics: each segment starts counting when the stage enters the thinking
 * family and freezes when it leaves — the heartbeat never bills the whole turn
 * to one "thinking" label). Null outside the thinking family, or when no
 * usable segment start exists.
 */
export function activeTurnStageSegmentSeconds(input: {
  stage: string;
  segmentStartedAtMs?: number | null;
  nowMs: number;
}): number | null {
  if (activeTurnStageBarPhase(input.stage) !== "thinking") {
    return null;
  }
  const startedMs = Number(input.segmentStartedAtMs);
  if (!Number.isFinite(startedMs) || startedMs <= 0) {
    return null;
  }
  return Math.max(0, Math.floor((input.nowMs - startedMs) / 1000));
}
