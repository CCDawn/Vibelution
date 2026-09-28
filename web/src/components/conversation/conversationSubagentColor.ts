/**
 * Stable colored names for subagent rows, aligned with ZCode's subagentColors
 * idea (name-hash → one of 8 fixed hues) but derived from theme tokens instead
 * of a hardcoded palette: each bucket rotates the accent hue by 45° via CSS
 * relative color syntax, so light/dark/accent-theme changes flow through
 * automatically and no literal color ships in this module.
 */
export const CONVERSATION_SUBAGENT_COLOR_BUCKET_COUNT = 8;

const HUE_DEG_PER_BUCKET = 360 / CONVERSATION_SUBAGENT_COLOR_BUCKET_COUNT;

/**
 * Same shape as ZCode's subagent name hash: an unsigned 32-bit accumulate of
 * `hash * 31 + charCode`, so equal names always land on one bucket and near
 * names scatter across the wheel.
 */
export function conversationSubagentColorHash(name: string): number {
  let hash = 0;
  const value = String(name ?? "");
  for (let index = 0; index < value.length; index += 1) {
    hash = (hash * 31 + value.charCodeAt(index)) >>> 0;
  }
  return hash;
}

/** Bucket index in `[0, 8)`; empty names collapse onto bucket 0. */
export function conversationSubagentColorBucket(name: string): number {
  const trimmed = String(name ?? "").trim();
  if (!trimmed) {
    return 0;
  }
  return conversationSubagentColorHash(trimmed) % CONVERSATION_SUBAGENT_COLOR_BUCKET_COUNT;
}

/**
 * CSS color value for one bucket: the theme accent hue rotated by
 * `bucket * 45deg`, keeping the accent's saturation/lightness so every bucket
 * stays readable in whichever theme supplies `--accent-cool`.
 */
export function conversationSubagentAccentColor(bucket: number): string {
  const safeBucket = ((Math.trunc(bucket) % CONVERSATION_SUBAGENT_COLOR_BUCKET_COUNT)
    + CONVERSATION_SUBAGENT_COLOR_BUCKET_COUNT) % CONVERSATION_SUBAGENT_COLOR_BUCKET_COUNT;
  const hueStep = safeBucket * HUE_DEG_PER_BUCKET;
  return `hsl(from var(--accent-cool) calc(h + ${hueStep}deg) s l)`;
}

/** Custom-property payload the colored-name span consumes via inline style. */
export function conversationSubagentAccentStyle(bucket: number): Record<string, string> {
  return { "--subagent-accent": conversationSubagentAccentColor(bucket) };
}
