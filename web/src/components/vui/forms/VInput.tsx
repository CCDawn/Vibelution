import { forwardRef, type ComponentPropsWithoutRef } from "react";

import { type VuiDensity } from "../renderers/shared/buttonVariants";
import { ShadcnInput } from "../renderers/shadcn/ShadcnInput";

export type VInputProps = ComponentPropsWithoutRef<"input"> & {
  density?: VuiDensity;
  /** HeroUI-era disabled flag — mapped to native disabled. */
  isDisabled?: boolean;
  "data-vui"?: string;
};

/**
 * Product text input API. Implementation is the shadcn-style native renderer.
 */
export const VInput = forwardRef<HTMLInputElement, VInputProps>(function VInput(
  {
    density = "compact",
    className,
    isDisabled,
    disabled,
    "data-vui": dataVui,
    ...props
  },
  ref,
) {
  return (
    <ShadcnInput
      {...props}
      ref={ref}
      density={density}
      isDisabled={isDisabled}
      disabled={disabled}
      data-vui={dataVui ?? "input"}
      className={className}
    />
  );
});
