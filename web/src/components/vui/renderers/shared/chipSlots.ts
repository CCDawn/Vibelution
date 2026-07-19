import { type VuiTone } from "./buttonVariants";

/** Shared visual slots for VChip — renderer-agnostic Tailwind contracts. */

export const vuiChipBaseClass =
  "inline-flex max-w-full items-center justify-center gap-1 rounded-full border border-vui-border-subtle bg-vui-control-muted text-vui-fg-secondary shadow-none";

export const vuiChipSizeClass =
  "h-6 min-h-6 max-h-6 px-1.5 [font-size:var(--vui-font-xs)] font-semibold leading-none";

/** Tone classes (paired with heroui-theme.css .vui-tone-* under the app provider). */
export function vuiChipToneClass(tone: VuiTone | undefined): string {
  const resolved = tone ?? "neutral";
  if (resolved === "accent") {
    return "vui-tone-accent border-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-control-muted))] text-[var(--accent-cool)]";
  }
  if (resolved === "info") {
    return "vui-tone-info";
  }
  if (resolved === "success") {
    return "vui-tone-success";
  }
  if (resolved === "warning") {
    return "vui-tone-warning";
  }
  if (resolved === "danger") {
    return "vui-tone-danger";
  }
  return "vui-tone-neutral";
}
