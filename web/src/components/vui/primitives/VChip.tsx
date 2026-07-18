import { type HTMLAttributes, type ReactNode } from "react";

import { type VuiTone } from "../renderers/shared/buttonVariants";
import { ShadcnChip } from "../renderers/shadcn/ShadcnChip";

export type VChipProps = Omit<HTMLAttributes<HTMLSpanElement>, "children"> & {
  tone?: VuiTone;
  children?: ReactNode;
  "data-vui"?: string;
};

/**
 * Product chip API. Implementation is the shadcn-style native renderer.
 */
export function VChip({
  tone = "neutral",
  className,
  children,
  "data-vui": dataVui,
  ...props
}: VChipProps) {
  return (
    <ShadcnChip
      {...props}
      tone={tone}
      data-vui={dataVui ?? "chip"}
      className={className}
    >
      {children}
    </ShadcnChip>
  );
}
