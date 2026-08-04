import * as PopoverPrimitive from "@radix-ui/react-popover";
import { type ReactNode } from "react";

import { cn } from "../../lib/cn";

export type ShadcnPopoverProps = {
  trigger: ReactNode;
  children: ReactNode;
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  side?: "top" | "right" | "bottom" | "left";
  align?: "start" | "center" | "end";
  sideOffset?: number;
  /** When true, focus is trapped like a dialog. Default false for workbench panels. */
  modal?: boolean;
  "aria-label"?: string;
  contentClassName?: string;
  className?: string;
  "data-vui"?: string;
};

const contentBaseClass = [
  "z-[95] min-w-[12rem] max-w-[min(100vw-1.5rem,28rem)]",
  "rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)]",
  "bg-[var(--vui-surface-panel)] text-[var(--fg-primary)]",
  "shadow-[var(--vui-elevation-overlay)] outline-none",
].join(" ");

/**
 * Radix/shadcn Popover renderer — non-modal floating panel with a trigger.
 * Pages must not import this; use VPopover.
 */
export function ShadcnPopover({
  trigger,
  children,
  open,
  defaultOpen,
  onOpenChange,
  side = "bottom",
  align = "start",
  sideOffset = 6,
  modal = false,
  "aria-label": ariaLabel,
  contentClassName,
  className,
  "data-vui": dataVui = "popover",
}: ShadcnPopoverProps) {
  return (
    <PopoverPrimitive.Root
      open={open}
      defaultOpen={defaultOpen}
      onOpenChange={onOpenChange}
      modal={modal}
    >
      <PopoverPrimitive.Trigger asChild>{trigger}</PopoverPrimitive.Trigger>
      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Content
          side={side}
          align={align}
          sideOffset={sideOffset}
          collisionPadding={12}
          aria-label={ariaLabel}
          data-vui={dataVui}
          data-renderer="radix"
          className={cn(contentBaseClass, contentClassName, className)}
        >
          {children}
        </PopoverPrimitive.Content>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  );
}
