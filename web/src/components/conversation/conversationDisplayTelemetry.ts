import type {
  ConversationDisplayDiscardReason,
  ConversationDisplayPipelineResult,
} from "./conversationDisplayPipeline";

/**
 * In-process display telemetry. No persistence, no network, no side channel:
 * a bounded ring buffer plus counters that answer three questions during a
 * repeated-projection or a scroll-jank report:
 *
 *   1. how many rows did each pipeline stage drop, and why;
 *   2. how many rows did the pipeline see and keep on the last frame;
 *   3. how many message surfaces were rebuilt (P3 baseline, see
 *      `recordConversationSurfaceBuild`).
 *
 * The buffer is intentionally small: this is a debugging aid, not an audit log.
 */
const MAX_FRAMES = 240;

const DISCARD_REASONS: readonly ConversationDisplayDiscardReason[] = [
  "runtime_notice",
  "recovery_superseded",
  "hot_restart_resume",
];

export type ConversationDisplayFrame = {
  at: string;
  inputCount: number;
  visibleCount: number;
  foldedCount: number;
  discardedCount: number;
  discarded: Record<ConversationDisplayDiscardReason, number>;
  durationMs: number;
};

export type ConversationSurfaceBuildFrame = {
  at: string;
  totalMessages: number;
  rebuiltMessages: number;
  durationMs: number;
};

export type ConversationDisplayTelemetrySnapshot = {
  frameTotal: number;
  surfaceBuildTotal: number;
  /**
   * Frames where the pipeline rebuilt every message instead of only the active
   * turn. This is the P3 signal: a steady non-zero value during streaming means
   * history rows are still being re-projected on every drain.
   */
  fullRebuildFrames: number;
  lastFrame: ConversationDisplayFrame | null;
  lastSurfaceBuild: ConversationSurfaceBuildFrame | null;
  frames: ConversationDisplayFrame[];
  surfaceBuilds: ConversationSurfaceBuildFrame[];
};

let frameTotal = 0;
let surfaceBuildTotal = 0;
let fullRebuildFrames = 0;
let lastFrame: ConversationDisplayFrame | null = null;
let lastSurfaceBuild: ConversationSurfaceBuildFrame | null = null;
let frames: ConversationDisplayFrame[] = [];
let surfaceBuilds: ConversationSurfaceBuildFrame[] = [];

function emptyDiscarded(): Record<ConversationDisplayDiscardReason, number> {
  return {
    runtime_notice: 0,
    recovery_superseded: 0,
    hot_restart_resume: 0,
  };
}

function push<T>(buffer: T[], entry: T): T[] {
  const next = [...buffer, entry];
  return next.length > MAX_FRAMES ? next.slice(next.length - MAX_FRAMES) : next;
}

function nowIso() {
  return new Date().toISOString();
}

/**
 * Record one completed display pipeline run.
 *
 * `rebuiltMessages` is the number of messages the caller actually re-projected
 * this frame. Callers that can only rebuild the active turn pass the smaller
 * number; passing `inputCount` marks the frame as a full rebuild for P3.
 */
export function recordConversationDisplayFrame(
  result: ConversationDisplayPipelineResult,
  options: {
    durationMs: number;
    inputCount: number;
    rebuiltMessages?: number;
  },
): ConversationDisplayFrame {
  const discarded = emptyDiscarded();
  for (const decision of result.decisions) {
    discarded[decision.reason] += 1;
  }

  const foldedCount = result.stages.reduce(
    (total, stage) => total + Math.max(0, stage.inputCount - stage.outputCount),
    0,
  );
  const discardedCount = result.decisions.length;

  const frame: ConversationDisplayFrame = {
    at: nowIso(),
    inputCount: Math.max(0, options.inputCount),
    visibleCount: result.messages.length,
    foldedCount,
    discardedCount,
    discarded,
    durationMs: Math.max(0, options.durationMs),
  };

  frameTotal += 1;
  lastFrame = frame;
  frames = push(frames, frame);

  const rebuilt = options.rebuiltMessages;
  if (typeof rebuilt === "number" && rebuilt >= frame.inputCount) {
    fullRebuildFrames += 1;
  }

  return frame;
}

/**
 * Record one message-surface build pass (the P3 baseline).
 *
 * `rebuiltMessages` should count only the surfaces computed from scratch; a
 * cached/reused history surface must not be counted, otherwise the metric
 * cannot show the win from rebuilding only the active turn.
 */
export function recordConversationSurfaceBuild(options: {
  totalMessages: number;
  rebuiltMessages: number;
  durationMs: number;
}): ConversationSurfaceBuildFrame {
  const frame: ConversationSurfaceBuildFrame = {
    at: nowIso(),
    totalMessages: Math.max(0, options.totalMessages),
    rebuiltMessages: Math.max(0, options.rebuiltMessages),
    durationMs: Math.max(0, options.durationMs),
  };
  surfaceBuildTotal += 1;
  lastSurfaceBuild = frame;
  surfaceBuilds = push(surfaceBuilds, frame);
  return frame;
}

export function readConversationDisplayTelemetry(): ConversationDisplayTelemetrySnapshot {
  return {
    frameTotal,
    surfaceBuildTotal,
    fullRebuildFrames,
    lastFrame,
    lastSurfaceBuild,
    frames: [...frames],
    surfaceBuilds: [...surfaceBuilds],
  };
}

export function resetConversationDisplayTelemetry(): void {
  frameTotal = 0;
  surfaceBuildTotal = 0;
  fullRebuildFrames = 0;
  lastFrame = null;
  lastSurfaceBuild = null;
  frames = [];
  surfaceBuilds = [];
}

export function discardReasons(): readonly ConversationDisplayDiscardReason[] {
  return DISCARD_REASONS;
}
