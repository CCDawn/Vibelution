import { forwardRef, type ComponentPropsWithoutRef } from "react";

import { type VuiDensity } from "../renderers/shared/buttonVariants";
import { ShadcnTextarea } from "../renderers/shadcn/ShadcnTextarea";

export type VTextareaProps = ComponentPropsWithoutRef<"textarea"> & {
  density?: VuiDensity;
  minRows?: number;
  /** HeroUI-era disabled flag — mapped to native disabled. */
  isDisabled?: boolean;
  "data-vui"?: string;
};

/**
 * Product textarea API. Implementation is the shadcn-style native renderer.
 */
export const VTextarea = forwardRef<HTMLTextAreaElement, VTextareaProps>(function VTextarea(
  {
    density = "compact",
    className,
    minRows,
    rows,
    isDisabled,
    disabled,
    "data-vui": dataVui,
    ...props
  },
  ref,
) {
  return (
    <ShadcnTextarea
      {...props}
      ref={ref}
      density={density}
      minRows={minRows}
      rows={rows}
      isDisabled={isDisabled}
      disabled={disabled}
      data-vui={dataVui ?? "textarea"}
      className={className}
    />
  );
});
