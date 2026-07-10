import { type ReactNode } from "react";

import { VButton, type VButtonProps } from "./VButton";
import { VTooltip } from "./VTooltip";

export type VIconButtonProps = Omit<
  VButtonProps,
  "children" | "icon" | "isIconOnly" | "aria-label"
> & {
  label: string;
  icon: ReactNode;
  title?: string;
  tooltip?: ReactNode;
};

export function VIconButton({ label, icon, title, tooltip, ...props }: VIconButtonProps) {
  return (
    <VTooltip content={tooltip ?? label}>
      <VButton
        {...props}
        data-vui="icon-button"
        isIconOnly
        aria-label={label}
        title={title ?? label}
        className={[
          "h-[var(--vui-control-height-sm)] w-[var(--vui-control-height-sm)] min-w-[var(--vui-control-height-sm)] aspect-square flex-none shrink-0 px-0",
          props.className,
        ]
          .filter(Boolean)
          .join(" ")}
      >
        {icon}
      </VButton>
    </VTooltip>
  );
}
