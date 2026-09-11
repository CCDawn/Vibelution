/**
 * Canonical tool input parsing.
 *
 * A tool's input travels as a JSON string on the wire (`ToolCallTurnItem.input`).
 * Two layers need to read it — the agent-thread adapter and the turn-item
 * transcript projection — so the tolerant parse lives here rather than being
 * copied per caller.
 *
 * Anything that is not a JSON object (absent, empty, still streaming and thus
 * truncated, or a bare scalar) yields `undefined`: callers then omit the field
 * instead of rendering garbage.
 */
export function parseToolCallInput(value: unknown): Record<string, unknown> | undefined {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  const source = String(value ?? "").trim();
  if (!source.startsWith("{")) {
    return undefined;
  }
  try {
    const parsed = JSON.parse(source);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? parsed as Record<string, unknown>
      : undefined;
  } catch {
    return undefined;
  }
}
