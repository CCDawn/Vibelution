import type { ReactNode } from "react";

import {
  ShadcnHoverCard,
  type ShadcnHoverCardAlign,
  type ShadcnHoverCardSide,
  type ShadcnHoverCardWidth,
} from "../renderers/shadcn/ShadcnHoverCard";

export type VHoverCardSide = ShadcnHoverCardSide;
export type VHoverCardAlign = ShadcnHoverCardAlign;
export type VHoverCardWidth = ShadcnHoverCardWidth;

export type VHoverCardProps = {
  /** Single trigger element (e.g. `VButton`); wraps plain children in a focusable host. */
  children: ReactNode;
  /** Card body — rich preview content, not just a short tip. */
  content: ReactNode;
  className?: string;
  side?: VHoverCardSide;
  align?: VHoverCardAlign;
  sideOffset?: number;
  /** Pointer open wait in ms before the overlay mounts/opens. */
  openDelay?: number;
  /** Close wait in ms after the pointer leaves trigger or card. */
  closeDelay?: number;
  width?: VHoverCardWidth;
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
};

/**
 * Product hover card API. Implementation is the shadcn/Radix renderer.
 * Pages keep using VHoverCard — do not import Radix directly.
 */
export function VHoverCard({
  side = "bottom",
  align = "center",
  sideOffset = 8,
  openDelay = 120,
  closeDelay = 80,
  width = "default",
  children,
  content,
  className,
  open,
  defaultOpen,
  onOpenChange,
}: VHoverCardProps) {
  return (
    <ShadcnHoverCard
      side={side}
      align={align}
      sideOffset={sideOffset}
      openDelay={openDelay}
      closeDelay={closeDelay}
      width={width}
      content={content}
      className={className}
      open={open}
      defaultOpen={defaultOpen}
      onOpenChange={onOpenChange}
    >
      {children}
    </ShadcnHoverCard>
  );
}
