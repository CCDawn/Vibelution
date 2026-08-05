/**
 * Minimal className merge helper (shadcn-style `cn` without extra deps).
 * Prefer this inside VUI renderers when composing density/variant slots.
 * Nested arrays are flattened (clsx-style) so callers can pass conditional groups.
 */
type ClassValue = string | false | null | undefined | ClassValue[];

export function cn(...parts: ClassValue[]): string {
  const flat: string[] = [];
  const walk = (value: ClassValue) => {
    if (!value) {
      return;
    }
    if (Array.isArray(value)) {
      for (const item of value) {
        walk(item);
      }
      return;
    }
    flat.push(value);
  };
  for (const part of parts) {
    walk(part);
  }
  return flat.join(" ");
}
