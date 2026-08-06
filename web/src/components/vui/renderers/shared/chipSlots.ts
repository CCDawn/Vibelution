import { type VuiTone } from "./buttonVariants";

/** Shared visual slots for VChip — renderer-agnostic Tailwind contracts. */

/** Compact shadcn Badge-like label with Apple-style restrained geometry. */
export const vuiChipBaseClass =
  "inline-flex max-w-full items-center justify-center gap-1 rounded-[6px] border border-vui-border-subtle bg-vui-control-muted text-vui-fg-secondary shadow-none";

export const vuiChipSizeClass =
  "h-[22px] min-h-[22px] max-h-[22px] px-1.5 [font-size:var(--vui-font-xs)] font-[650] leading-none tracking-[-0.004em]";

/** Tone changes meaning, never makes a non-interactive label look like a button. */
export function vuiChipToneClass(tone: VuiTone | undefined): string {
  const resolved = tone ?? "neutral";
  if (resolved === "warning") {
    return "border-[color-mix(in_srgb,var(--state-warning)_34%,var(--vui-border-subtle))] text-[var(--state-warning)]";
  }
  if (resolved === "danger") {
    return "border-[color-mix(in_srgb,var(--state-error)_30%,var(--vui-border-subtle))] text-[var(--state-error)]";
  }
  if (resolved === "accent" || resolved === "info") {
    return "border-[color-mix(in_srgb,var(--fg-primary)_18%,var(--vui-border-subtle))] text-[var(--fg-primary)]";
  }
  return "border-vui-border-subtle text-vui-fg-secondary";
}
