import { type ReactNode } from "react";

import { VButton, type VButtonProps } from "./VButton";

export type VIconButtonProps = Omit<
  VButtonProps,
  "children" | "icon" | "isIconOnly" | "aria-label"
> & {
  label: string;
  icon: ReactNode;
  title?: string;
};

export function VIconButton({ label, icon, title, ...props }: VIconButtonProps) {
  return (
    <VButton
      {...props}
      data-vui="icon-button"
      isIconOnly
      aria-label={label}
      title={title ?? label}
      className={[
        "h-[var(--vui-control-height-sm)] w-[var(--vui-control-height-sm)] min-w-0 px-0",
        props.className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {icon}
    </VButton>
  );
}
