/**
 * Minimal className merge helper (shadcn-style `cn` without extra deps).
 * Prefer this inside VUI renderers when composing density/variant slots.
 */
export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}
