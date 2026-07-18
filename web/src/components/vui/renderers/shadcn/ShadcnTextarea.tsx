import { forwardRef, type ComponentPropsWithoutRef } from "react";

import { type VuiDensity } from "../shared/buttonVariants";
import { vuiFormControlClass } from "../../forms/formClasses";

/**
 * Shadcn-style native textarea renderer.
 * Pages must not import this — only VUI form primitives consume it.
 */
export type ShadcnTextareaProps = ComponentPropsWithoutRef<"textarea"> & {
  density?: VuiDensity;
  /** HeroUI-era min rows helper. */
  minRows?: number;
  /** HeroUI-era disabled flag. */
  isDisabled?: boolean;
  "data-vui"?: string;
};

export const ShadcnTextarea = forwardRef<HTMLTextAreaElement, ShadcnTextareaProps>(
  function ShadcnTextarea(
    {
      density = "compact",
      className,
      minRows,
      rows,
      isDisabled = false,
      disabled,
      "data-vui": dataVui,
      ...props
    },
    ref,
  ) {
    return (
      <textarea
        {...props}
        ref={ref}
        rows={rows ?? minRows}
        disabled={Boolean(disabled || isDisabled)}
        data-vui={dataVui ?? "textarea"}
        data-density={density}
        data-renderer="shadcn"
        className={[
          vuiFormControlClass(density),
          "min-h-20 resize-y py-1.5 leading-5",
          className,
        ]
          .filter(Boolean)
          .join(" ")}
      />
    );
  },
);
