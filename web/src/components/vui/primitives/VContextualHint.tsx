import { CircleHelp } from "lucide-react";
import { type ReactNode } from "react";

import { VNativeButton } from "./VNativeButton";
import { VTooltip, type VTooltipTone, type VTooltipWidth } from "./VTooltip";

export type VContextualHintProps = {
  label: string;
  content: ReactNode;
  className?: string;
  tone?: VTooltipTone;
  width?: VTooltipWidth;
};

export function VContextualHint({
  label,
  content,
  className,
  tone = "neutral",
  width = "default",
}: VContextualHintProps) {
  return (
    <VTooltip content={content} tone={tone} width={width}>
      <VNativeButton
        type="button"
        data-vui="contextual-hint"
        aria-label={label}
        className={[
          "inline-flex size-[18px] min-h-[18px] min-w-[18px] shrink-0 items-center justify-center rounded-full border border-transparent p-0 text-vui-fg-tertiary transition-[color,background,border-color,box-shadow] duration-150 hover:border-vui-border-subtle hover:bg-vui-control-muted hover:text-vui-fg-secondary focus-visible:outline-none focus-visible:border-[var(--accent-cool)] focus-visible:bg-vui-control-muted focus-visible:text-vui-fg-primary focus-visible:shadow-[var(--vui-shadow-focus)]",
          className,
        ]
          .filter(Boolean)
          .join(" ")}
      >
        <CircleHelp size={13} strokeWidth={1.8} aria-hidden="true" />
      </VNativeButton>
    </VTooltip>
  );
}
