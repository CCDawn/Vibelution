import { type HTMLAttributes, type ReactNode } from "react";

import { type VuiTone } from "../shared/buttonVariants";
import {
  vuiChipBaseClass,
  vuiChipSizeClass,
  vuiChipToneClass,
} from "../shared/chipSlots";

/**
 * Shadcn-style native chip/badge renderer.
 * Pages must not import this — only VUI primitives consume it.
 */
export type ShadcnChipProps = Omit<HTMLAttributes<HTMLSpanElement>, "children"> & {
  tone?: VuiTone;
  children?: ReactNode;
  "data-vui"?: string;
};

export function ShadcnChip({
  tone = "neutral",
  className,
  children,
  "data-vui": dataVui,
  ...props
}: ShadcnChipProps) {
  return (
    <span
      {...props}
      data-vui={dataVui ?? "chip"}
      data-tone={tone}
      data-renderer="shadcn"
      className={[
        vuiChipBaseClass,
        vuiChipSizeClass,
        vuiChipToneClass(tone),
        "min-w-0 truncate",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {children}
    </span>
  );
}
