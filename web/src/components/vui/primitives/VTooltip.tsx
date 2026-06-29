import { Tooltip, type TooltipProps } from "@heroui/react";

export type VTooltipProps = TooltipProps & {
  className?: string;
};

export function VTooltip({
  delay = 250,
  closeDelay = 80,
  className,
  ...props
}: VTooltipProps) {
  const tooltipProps = {
    ...props,
    delay,
    closeDelay,
    className: [
      "max-w-72 border border-vui-border-soft bg-vui-surface-card px-2 py-1 text-xs text-vui-fg-secondary",
      className,
    ]
      .filter(Boolean)
      .join(" "),
  } as TooltipProps;

  return <Tooltip {...tooltipProps} />;
}
