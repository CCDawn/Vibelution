/** Shared visual slots for VButton — renderer-agnostic Tailwind contracts. */

import type { VuiButtonVariant } from "./buttonVariants";

export const vuiButtonBaseClass =
  "border border-vui-border-subtle bg-vui-control-muted text-vui-fg-secondary shadow-none";

export const vuiButtonHoverClass =
  "transition-colors duration-150 hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] hover:shadow-[var(--vui-control-hover-shadow)]";

export const vuiButtonPrimaryClass =
  "border-vui-accent-cool bg-vui-surface-panel text-vui-fg-primary";

export const vuiButtonDangerClass =
  "border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] bg-[var(--vui-status-danger-bg)] text-[var(--vui-status-danger-fg)]";

export const vuiButtonFocusClass =
  "focus-visible:outline-none focus-visible:shadow-[var(--vui-shadow-focus)]";

export const vuiButtonDisabledClass =
  "disabled:cursor-default disabled:opacity-55 disabled:pointer-events-none";

export function vuiButtonVariantClass(variant: VuiButtonVariant | undefined): string {
  if (variant === "primary") {
    return `${vuiButtonBaseClass} ${vuiButtonHoverClass} ${vuiButtonPrimaryClass}`;
  }
  if (variant === "danger") {
    return `${vuiButtonBaseClass} ${vuiButtonHoverClass} ${vuiButtonDangerClass}`;
  }
  if (variant === "ghost") {
    return `border border-transparent bg-transparent text-vui-fg-secondary shadow-none ${vuiButtonHoverClass}`;
  }
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
