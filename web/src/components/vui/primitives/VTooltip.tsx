import {
  Tooltip,
  type TooltipContentProps,
  type TooltipProps,
} from "@heroui/react";
import { type ReactNode } from "react";

export type VTooltipProps = Omit<TooltipProps, "children"> & {
  children: ReactNode;
  content: ReactNode;
  className?: string;
};

export function VTooltip({
  delay = 250,
  closeDelay = 80,
  children,
  content,
  className,
  ...props
}: VTooltipProps) {
  const contentProps: TooltipContentProps = {
    className: [
      "max-w-72 border border-vui-border-soft bg-vui-surface-card px-2 py-1 text-xs text-vui-fg-secondary",
      className,
    ]
      .filter(Boolean)
      .join(" "),
    children: content,
  };

  return (
    <Tooltip {...props} delay={delay} closeDelay={closeDelay}>
      <Tooltip.Trigger>{children}</Tooltip.Trigger>
      <Tooltip.Content {...contentProps} />
    </Tooltip>
  );
}
