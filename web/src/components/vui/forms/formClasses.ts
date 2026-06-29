import { type VuiDensity } from "../renderers/heroui/heroVariants";

export function vuiFormControlClass(density: VuiDensity | undefined): string {
  const heightClass = density === "normal" ? "min-h-9" : "min-h-8";

  return [
    heightClass,
    "w-full min-w-0 rounded-md border border-vui-border-subtle",
    "bg-vui-control-muted px-2 text-sm text-vui-fg-primary shadow-none",
    "transition-colors placeholder:text-vui-fg-tertiary",
    "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-vui-accent-cool",
    "disabled:cursor-not-allowed disabled:opacity-55",
  ].join(" ");
}

export const vuiFormHelperClass = "text-[11px] leading-4 text-vui-fg-tertiary";

export const vuiFormLabelClass = "text-[11px] font-semibold uppercase tracking-normal text-vui-fg-secondary";
