import {
  type VuiDensity,
  vuiControlDensityClass,
} from "../renderers/shared/buttonVariants";

/**
 * Shared form control chrome — solid flat face, fine edge, and visible keyboard focus.
 */
export function vuiFormControlClass(density: VuiDensity | undefined): string {
  return [
    vuiControlDensityClass(density),
    "w-full min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-control-border)]",
    "bg-[var(--vui-control-face)] px-2 [font-size:var(--vui-type-control-size)] text-vui-fg-primary shadow-[var(--vui-field-shadow)]",
    // Inherit document theme so native pickers/options follow light/dark tokens.
    "[color-scheme:inherit]",
    "transition-[color,background-color,border-color,box-shadow] duration-150 ease-out motion-reduce:transition-none",
    "placeholder:text-vui-fg-tertiary",
    "hover:border-[color-mix(in_srgb,var(--vui-control-border)_78%,var(--accent-cool))]",
    "focus-visible:outline-none focus-visible:border-[color-mix(in_srgb,var(--accent-cool)_45%,var(--vui-border-subtle))]",
    "focus-visible:ring-2 focus-visible:ring-[color-mix(in_srgb,var(--accent-cool)_40%,transparent)]",
    "focus-visible:ring-offset-1 focus-visible:ring-offset-[var(--vui-surface-panel)]",
    "disabled:cursor-not-allowed disabled:opacity-55 disabled:hover:border-[var(--vui-control-border)]",
    "aria-[invalid=true]:border-[color-mix(in_srgb,var(--state-error)_50%,var(--vui-border-subtle))]",
    "aria-[invalid=true]:focus-visible:ring-[color-mix(in_srgb,var(--state-error)_35%,transparent)]",
  ].join(" ");
}

export const vuiFormHelperClass =
  "[font-size:var(--vui-type-caption-size)] leading-[var(--vui-line-readable)] text-vui-fg-tertiary peer-aria-[invalid=true]:text-[var(--state-error)]";

export const vuiFormLabelClass =
  "[font-size:var(--vui-type-label-size)] leading-[var(--vui-type-label-line)] font-semibold tracking-normal text-vui-fg-secondary";

export const vuiFormErrorClass =
  "[font-size:var(--vui-type-caption-size)] leading-[var(--vui-line-readable)] text-[var(--state-error)]";
