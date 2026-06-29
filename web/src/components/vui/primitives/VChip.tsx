import { Chip, type ChipProps } from "@heroui/react";

import { vuiChipBaseClass } from "../renderers/heroui/heroSlots";
import { type VuiTone, vuiToneClass } from "../renderers/heroui/heroVariants";

export type VChipProps = Omit<ChipProps, "variant" | "color" | "size"> & {
  tone?: VuiTone;
};

export function VChip({
  tone = "neutral",
  className,
  children,
  ...props
}: VChipProps) {
  return (
    <Chip
      {...props}
      data-vui="chip"
      size="sm"
      className={[
        vuiChipBaseClass,
        vuiToneClass(tone),
        "h-[24px] max-w-full px-1.5 text-[var(--vui-font-xs)] font-semibold",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {children}
    </Chip>
  );
}
