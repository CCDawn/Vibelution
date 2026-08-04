import { forwardRef, type ComponentPropsWithoutRef } from "react";

import { type VuiDensity } from "../shared/buttonVariants";
import { vuiFormControlClass } from "../../forms/formClasses";

/**
 * Shadcn-style native input renderer.
 * Pages must not import this — only VUI form primitives consume it.
 */
export type ShadcnInputProps = ComponentPropsWithoutRef<"input"> & {
  density?: VuiDensity;
  /** HeroUI-era disabled flag. */
  isDisabled?: boolean;
  "data-vui"?: string;
};

export const ShadcnInput = forwardRef<HTMLInputElement, ShadcnInputProps>(function ShadcnInput(
  {
    density = "compact",
    className,
    type,
    isDisabled = false,
    disabled,
    "data-vui": dataVui,
    ...props
  },
  ref,
) {
  const inputType = type ?? "text";
  const isBox = inputType === "checkbox" || inputType === "radio";
  const isRange = inputType === "range";
  const controlClass = isBox
    ? [
        "h-4 w-4 min-w-4 rounded-[4px] border border-vui-border-subtle",
        "bg-[var(--vui-surface-panel)] text-[var(--fg-primary)] shadow-none",
        "accent-[var(--fg-primary)]",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color-mix(in_srgb,var(--accent-cool)_45%,transparent)]",
        "focus-visible:ring-offset-1 focus-visible:ring-offset-[var(--vui-surface-panel)]",
        "disabled:cursor-not-allowed disabled:opacity-55",
      ].join(" ")
    : isRange
      ? [
          "w-full min-w-0 accent-[var(--fg-primary)]",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color-mix(in_srgb,var(--accent-cool)_45%,transparent)]",
          "disabled:cursor-not-allowed disabled:opacity-55",
        ].join(" ")
      : vuiFormControlClass(density);

  return (
    <input
      {...props}
      ref={ref}
      type={inputType}
      disabled={Boolean(disabled || isDisabled)}
      data-vui={dataVui ?? "input"}
      data-density={density}
      data-renderer="shadcn"
      className={[controlClass, className].filter(Boolean).join(" ")}
    />
  );
});
