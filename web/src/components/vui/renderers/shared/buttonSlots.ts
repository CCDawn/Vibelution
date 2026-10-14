/** Shared visual slots for VButton — renderer-agnostic Tailwind contracts. */

import type { VuiButtonVariant } from "./buttonVariants";

/**
 * Flat secondary control chrome: a fine edge and a solid semantic face.
 */
export const vuiButtonBaseClass =
  "border border-[var(--vui-control-border)] text-vui-fg-secondary bg-[var(--vui-control-face)] shadow-[var(--vui-control-shadow)]";

export const vuiButtonHoverClass =
  "transition-[color,background,border-color,box-shadow,opacity] duration-150 ease-out motion-reduce:transition-none hover:border-[color-mix(in_srgb,var(--vui-control-border)_78%,var(--fg-primary))] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--fg-primary)]";

/**
 * Solid blue primary — visually clear default action in both themes.
 */
export const vuiButtonPrimaryClass =
  "border border-[var(--vui-primary-border)] text-white bg-[var(--vui-primary-face)] shadow-none hover:brightness-[0.97] active:brightness-90";

/** Quiet danger treatment keeps both the error meaning and label readable. */
export const vuiButtonDangerClass =
  "border border-[color-mix(in_srgb,var(--state-error)_42%,var(--vui-control-border))] bg-[var(--vui-status-danger-bg)] text-[var(--vui-status-danger-fg)] shadow-none hover:border-[color-mix(in_srgb,var(--state-error)_55%,var(--vui-control-border))] hover:bg-[color-mix(in_srgb,var(--state-error)_12%,var(--vui-status-danger-bg))]";

/** Ghost — transparent idle with a quiet hover tint. */
export const vuiButtonGhostClass =
  "border border-transparent bg-transparent text-vui-fg-secondary shadow-none hover:border-transparent hover:bg-[color-mix(in_srgb,var(--fg-primary)_6%,transparent)] hover:text-[var(--fg-primary)] hover:shadow-none";

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
    return vuiButtonDangerClass;
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
