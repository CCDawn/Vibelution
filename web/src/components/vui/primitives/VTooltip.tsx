import type { ReactNode } from "react";

import {
  ShadcnTooltip,
  type ShadcnTooltipTriggerRender,
  type ShadcnTooltipTone,
  type ShadcnTooltipWidth,
} from "../renderers/shadcn/ShadcnTooltip";

/** @deprecated Alias kept for existing imports; renderer is Radix/shadcn. */
export type VTooltipTriggerRender = ShadcnTooltipTriggerRender;

export type VTooltipTone = ShadcnTooltipTone;
export type VTooltipWidth = ShadcnTooltipWidth;

export type VTooltipProps = {
  children: ReactNode;
  content: ReactNode;
  className?: string;
  /** Open delay in ms (maps to Radix delayDuration). */
  delay?: number;
  /** Skip-delay window after close (maps to Radix skipDelayDuration). */
  closeDelay?: number;
  renderTrigger?: VTooltipTriggerRender;
  showArrow?: boolean;
  tone?: VTooltipTone;
  width?: VTooltipWidth;
  open?: boolean;
  /** HeroUI-era controlled open flag. */
  isOpen?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
};

/**
 * Product tooltip API. Implementation is the shadcn/Radix renderer.
 * Pages keep using VTooltip — do not import Radix directly.
 */
export function VTooltip({
  delay = 320,
  closeDelay = 100,
  children,
  content,
  className,
  renderTrigger,
  showArrow = true,
  tone = "neutral",
  width = "default",
  open,
  isOpen,
  defaultOpen,
  onOpenChange,
}: VTooltipProps) {
  return (
    <ShadcnTooltip
      delay={delay}
      closeDelay={closeDelay}
      content={content}
      className={className}
      renderTrigger={renderTrigger}
      showArrow={showArrow}
      tone={tone}
      width={width}
      open={open}
      isOpen={isOpen}
      defaultOpen={defaultOpen}
      onOpenChange={onOpenChange}
    >
      {children}
    </ShadcnTooltip>
  );
}
