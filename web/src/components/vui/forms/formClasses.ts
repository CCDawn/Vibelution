import {
  type VuiDensity,
  vuiControlDensityClass,
} from "../renderers/shared/buttonVariants";

/**
 * Shared form control chrome — shadcn Input/Select baseline:
 * surface fill, subtle border, ring focus with offset, reduced-motion safe transitions.
 */
export function vuiFormControlClass(density: VuiDensity | undefined): string {
  return [
    vuiControlDensityClass(density),
    "w-full min-w-0 rounded-[var(--radius-control)] border border-vui-border-subtle",
    "bg-[var(--vui-surface-panel)] px-2.5 text-sm text-vui-fg-primary shadow-none",
    // Inherit document theme so native pickers/options follow light/dark tokens.
    "[color-scheme:inherit]",
    "transition-[color,background-color,border-color,box-shadow] duration-150 ease-out motion-reduce:transition-none",
    "placeholder:text-vui-fg-tertiary",
    "hover:border-[color-mix(in_srgb,var(--vui-border-subtle)_70%,var(--fg-tertiary))]",
    "focus-visible:outline-none focus-visible:border-[color-mix(in_srgb,var(--accent-cool)_45%,var(--vui-border-subtle))]",
    "focus-visible:ring-2 focus-visible:ring-[color-mix(in_srgb,var(--accent-cool)_40%,transparent)]",
    "focus-visible:ring-offset-1 focus-visible:ring-offset-[var(--vui-surface-panel)]",
    "disabled:cursor-not-allowed disabled:opacity-55 disabled:hover:border-vui-border-subtle",
    "aria-[invalid=true]:border-[color-mix(in_srgb,var(--state-error)_50%,var(--vui-border-subtle))]",
    "aria-[invalid=true]:focus-visible:ring-[color-mix(in_srgb,var(--state-error)_35%,transparent)]",
  ].join(" ");
}

export const vuiFormHelperClass =
  "text-[11px] leading-4 text-vui-fg-tertiary peer-aria-[invalid=true]:text-[var(--state-error)]";

export const vuiFormLabelClass =
  "text-[11px] font-semibold tracking-normal text-vui-fg-secondary";

export const vuiFormErrorClass =
  "text-[11px] leading-4 text-[var(--state-error)]";
