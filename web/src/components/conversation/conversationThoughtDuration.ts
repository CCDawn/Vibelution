/**
 * Settled thinking-duration derivation (ZCode reasoning-parity).
 *
 * 口径 (honest, derivable facts only — no invented fields):
 * The only server facts a reasoning segment can carry are the canonical turn
 * item's `createdAt` (first revision ≈ thinking start) and `updatedAt` (last
 * revision ≈ thinking end). `updatedAt - createdAt` is that one reasoning
 * item's own lifetime — never the turn span, never the final LLM call
 * (`usageStats.elapsedMs` bills answer generation), so it is the only honest
 * settled duration. Backend projections do not populate these stamps today
 * (`conversationTurnWorkStatus.ts` documents the same gap), so callers must
 * treat `null` as "no honest duration" and render nothing rather than fall
 * back to a whole-turn number.
 *
 * Seconds follow the ZCode reference (`ConversationRowView` reasoning row):
 * `Math.max(1, Math.ceil(durationMs / 1000))` — sub-second thinking still
 * reads "1s", never a fraction. Clock-skewed inputs (end before start) yield
 * null instead of a negative or clamped guess.
 */
export function settledThoughtDurationSeconds(
  createdAt: unknown,
  updatedAt: unknown,
): number | null {
  const start = parseEpochMs(createdAt);
  const end = parseEpochMs(updatedAt);
  if (start === null || end === null || end < start) {
    return null;
  }
  return Math.max(1, Math.ceil((end - start) / 1000));
}

function parseEpochMs(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value) && value > 0) {
    return value;
  }
  if (typeof value === "string" && value.trim()) {
    const parsed = Date.parse(value);
    if (Number.isFinite(parsed) && parsed > 0) {
      return parsed;
    }
  }
  return null;
}
