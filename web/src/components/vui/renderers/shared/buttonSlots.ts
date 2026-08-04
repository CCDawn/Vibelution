/** Shared visual slots for VButton — shadcn-aligned, renderer-agnostic Tailwind contracts. */

import type { VuiButtonVariant } from "./buttonVariants";

/**
 * Base outline/muted control chrome (secondary default).
 * Hover uses semantic control tokens so light/dark themes stay consistent.
 */
export const vuiButtonBaseClass =
  "border border-vui-border-subtle bg-vui-control-muted text-vui-fg-secondary shadow-none";

export const vuiButtonHoverClass =
  "transition-[color,background-color,border-color,box-shadow,opacity] duration-150 ease-out motion-reduce:transition-none hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] hover:shadow-[var(--vui-control-hover-shadow)]";

/**
 * Solid primary — shadcn-style high-contrast CTA (ink fill, not washed border).
 * Works in light/dark via fg-primary / surface-base inversion.
 */
export const vuiButtonPrimaryClass =
  "border-[var(--fg-primary)] bg-[var(--fg-primary)] text-[var(--vui-surface-base)] shadow-none hover:border-[var(--fg-primary)] hover:bg-[color-mix(in_srgb,var(--fg-primary)_88%,var(--vui-surface-base))] hover:text-[var(--vui-surface-base)] hover:shadow-none active:bg-[color-mix(in_srgb,var(--fg-primary)_80%,var(--vui-surface-base))]";

/** Danger outline — readable on workbench surfaces without full solid wash. */
export const vuiButtonDangerClass =
  "border-[color-mix(in_srgb,var(--state-error)_42%,var(--vui-border-subtle))] bg-[var(--vui-status-danger-bg)] text-[var(--vui-status-danger-fg)] hover:border-[color-mix(in_srgb,var(--state-error)_55%,var(--vui-border-subtle))] hover:bg-[color-mix(in_srgb,var(--state-error)_12%,var(--vui-status-danger-bg))]";

/** Ghost — transparent idle; soft hover fill (shadcn ghost). */
export const vuiButtonGhostClass =
  "border border-transparent bg-transparent text-vui-fg-secondary shadow-none hover:border-transparent hover:bg-[color-mix(in_srgb,var(--vui-control-muted)_88%,transparent)] hover:text-[var(--fg-primary)] hover:shadow-none";

/**
 * Focus ring: shadcn-like ring + project focus shadow token for theme compatibility.
 */
export const vuiButtonFocusClass =
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color-mix(in_srgb,var(--accent-cool)_55%,transparent)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--vui-surface-panel)] focus-visible:shadow-[var(--vui-shadow-focus)]";

export const vuiButtonDisabledClass =
  "disabled:cursor-default disabled:opacity-55 disabled:pointer-events-none disabled:shadow-none";

export function vuiButtonVariantClass(variant: VuiButtonVariant | undefined): string {
  if (variant === "primary") {
    // Focus ring applied by ShadcnButton alongside this class.
    return vuiButtonPrimaryClass;
  }
  if (variant === "danger") {
    return `${vuiButtonBaseClass} ${vuiButtonHoverClass} ${vuiButtonDangerClass}`;
  }
  if (variant === "ghost") {
    return vuiButtonGhostClass;
  }
  // secondary (default)
  return `${vuiButtonBaseClass} ${vuiButtonHoverClass}`;
}

function classNameTokens(className: string | undefined): string[] {
  return className?.trim().split(/\s+/).filter(Boolean) ?? [];
}

function hasExplicitRootWidth(className: string | undefined): boolean {
  return classNameTokens(className).some((token) => {
    if (token.startsWith("[&")) {
      return false;
    }
    return /(?:^|:)!?w-(?:auto|fit|full|max|min|\[|[0-9])/.test(token);
  });
}

export function vuiButtonGeometryClass(
  className: string | undefined,
  contentLayout: "label" | "plain",
): string {
  return [
    "max-w-full shrink-0 justify-self-start",
    contentLayout === "label" ? "whitespace-nowrap" : null,
    hasExplicitRootWidth(className) ? null : "w-fit",
  ]
    .filter(Boolean)
    .join(" ");
}
