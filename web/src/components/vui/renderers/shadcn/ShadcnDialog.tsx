import * as DialogPrimitive from "@radix-ui/react-dialog";
import { type ReactNode } from "react";

import { cn } from "../../lib/cn";

export type ShadcnDialogSize = "sm" | "md" | "lg" | "xl";

export type ShadcnDialogProps = {
  open?: boolean;
  /** HeroUI-era alias for controlled open. */
  isOpen?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  title: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  size?: ShadcnDialogSize;
  className?: string;
  contentClassName?: string;
  /** When true, hide the built-in close control in the header. */
  hideClose?: boolean;
  /** Accessible label when title is not plain text. */
  "aria-label"?: string;
};

const sizeClassName: Record<ShadcnDialogSize, string> = {
  sm: "w-[min(100%,22rem)]",
  md: "w-[min(100%,28rem)]",
  lg: "w-[min(100%,36rem)]",
  xl: "w-[min(100%,48rem)]",
};

/**
 * Radix/shadcn-style dialog renderer.
 * Pages must not import this — only VUI primitives consume it.
 */
export function ShadcnDialog({
  open,
  isOpen,
  defaultOpen,
  onOpenChange,
  title,
  description,
  children,
  footer,
  size = "md",
  className,
  contentClassName,
  hideClose = false,
  "aria-label": ariaLabel,
}: ShadcnDialogProps) {
  const controlledOpen = open ?? isOpen;

  return (
    <DialogPrimitive.Root
      open={controlledOpen}
      defaultOpen={defaultOpen}
      onOpenChange={onOpenChange}
    >
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay
          data-vui="dialog-overlay"
          data-renderer="radix"
          className={cn(
            "fixed inset-0 z-[90]",
            "bg-[color-mix(in_srgb,var(--bg-canvas)_52%,transparent)]",
            "backdrop-blur-[5px]",
          )}
        />
        <DialogPrimitive.Content
          data-vui="dialog-content"
          data-renderer="radix"
          aria-label={ariaLabel}
          className={cn(
            "fixed left-1/2 top-1/2 z-[91] max-h-[min(88dvh,52rem)] -translate-x-1/2 -translate-y-1/2",
            "grid min-w-0 grid-rows-[auto_minmax(0,1fr)_auto] gap-0 overflow-hidden",
            "rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)]",
            "bg-[color-mix(in_srgb,var(--vui-surface-panel)_98%,transparent)]",
            "shadow-[var(--vui-elevation-overlay)] outline-none",
            sizeClassName[size],
            contentClassName,
            className,
          )}
        >
          <header
            data-slot="dialog-header"
            className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-start gap-2 border-b border-[var(--vui-border-subtle)] px-3 py-2.5"
          >
            <div className="grid min-w-0 gap-0.5">
              <DialogPrimitive.Title
                data-slot="dialog-title"
                className="m-0 min-w-0 truncate [font-size:var(--vui-font-title)] font-semibold leading-tight text-[var(--fg-primary)]"
              >
                {title}
              </DialogPrimitive.Title>
              {description ? (
                <DialogPrimitive.Description
                  data-slot="dialog-description"
                  className="m-0 min-w-0 [font-size:var(--vui-font-xs)] leading-[1.45] text-[var(--fg-secondary)]"
                >
                  {description}
                </DialogPrimitive.Description>
              ) : (
                // Radix warns if Description is missing; keep an empty but present node for a11y tooling.
                <DialogPrimitive.Description className="sr-only">
                  {typeof title === "string" ? title : "Dialog"}
                </DialogPrimitive.Description>
              )}
            </div>
            {hideClose ? null : (
              <DialogPrimitive.Close
                data-vui="dialog-close"
                data-slot="dialog-close"
                className={cn(
                  "inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-[var(--radius-control)]",
                  "border border-transparent text-[var(--fg-tertiary)]",
                  "hover:border-[var(--vui-border-subtle)] hover:bg-[var(--vui-control-muted)] hover:text-[var(--fg-primary)]",
                  "focus-visible:outline-none focus-visible:shadow-[var(--vui-shadow-focus)]",
                )}
                aria-label="Close"
              >
                <span aria-hidden="true" className="text-sm leading-none">
                  ×
                </span>
              </DialogPrimitive.Close>
            )}
          </header>
          <div
            data-slot="dialog-body"
            className="min-h-0 overflow-auto px-3 py-2.5 [font-size:var(--vui-font-sm)] text-[var(--fg-secondary)]"
          >
            {children}
          </div>
          {footer ? (
            <footer
              data-slot="dialog-footer"
              className="flex min-w-0 flex-wrap items-center justify-end gap-1.5 border-t border-[var(--vui-border-subtle)] px-3 py-2"
            >
              {footer}
            </footer>
          ) : null}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
