import * as DropdownMenuPrimitive from "@radix-ui/react-dropdown-menu";
import { type ReactNode } from "react";

import { cn } from "../../lib/cn";

export type ShadcnDropdownMenuItem = {
  id: string;
  label: ReactNode;
  icon?: ReactNode;
  disabled?: boolean;
  danger?: boolean;
  title?: string;
  onSelect?: () => void;
};

export type ShadcnDropdownMenuPosition = {
  x: number;
  y: number;
};

export type ShadcnDropdownMenuProps = {
  items: ShadcnDropdownMenuItem[];
  /** Controlled open. Defaults to true when `position` is set (mount-as-open surface). */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  /**
   * Fixed screen coordinates for context-menu style surfaces.
   * When set, a 1px virtual anchor is placed at (x, y) and the panel portals beside it.
   */
  position?: ShadcnDropdownMenuPosition;
  /** Button/trigger for classic dropdown menus. Ignored when `position` is set. */
  trigger?: ReactNode;
  side?: "top" | "right" | "bottom" | "left";
  align?: "start" | "center" | "end";
  sideOffset?: number;
  "aria-label"?: string;
  className?: string;
  contentClassName?: string;
  itemClassName?: string;
  dangerItemClassName?: string;
  "data-vui"?: string;
  /** Optional data attribute passthrough for domain identity (e.g. agent id). */
  contentProps?: Record<string, string | undefined>;
};

const contentBaseClass = [
  "z-[100] min-w-[11.5rem] max-w-[min(100vw-1.5rem,16rem)]",
  "grid content-start gap-1 p-1",
  "rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)]",
  "bg-[var(--vui-surface-panel)] text-[var(--fg-primary)] shadow-[var(--vui-elevation-overlay)]",
  "outline-none",
].join(" ");

const itemBaseClass = [
  "relative flex w-full min-w-0 cursor-default select-none items-center gap-2",
  "rounded-[calc(var(--radius-control)-2px)] px-2 py-1.5 text-left [font-size:var(--vui-type-control-size)] font-semibold",
  "text-[var(--fg-secondary)] outline-none",
  "data-[highlighted]:bg-[color-mix(in_srgb,var(--accent-cool)_10%,transparent)]",
  "data-[highlighted]:text-[var(--fg-primary)]",
  "data-[disabled]:pointer-events-none data-[disabled]:opacity-45",
].join(" ");

const itemDangerClass = [
  "text-[var(--vui-status-danger-fg)]",
  "data-[highlighted]:bg-[color-mix(in_srgb,var(--state-error)_12%,transparent)]",
  "data-[highlighted]:text-[var(--vui-status-danger-fg)]",
].join(" ");

/**
 * Radix/shadcn DropdownMenu renderer.
 * Supports classic trigger menus and fixed-position context surfaces.
 */
export function ShadcnDropdownMenu({
  items,
  open,
  onOpenChange,
  position,
  trigger,
  side,
  align,
  sideOffset,
  "aria-label": ariaLabel,
  className,
  contentClassName,
  itemClassName,
  dangerItemClassName,
  "data-vui": dataVui = "dropdown-menu",
  contentProps,
}: ShadcnDropdownMenuProps) {
  const anchored = Boolean(position);
  const controlledOpen = open ?? (anchored ? true : undefined);
  const resolvedSide = side ?? "bottom";
  const resolvedAlign = align ?? (anchored ? "start" : "start");
  const resolvedSideOffset = sideOffset ?? (anchored ? 2 : 4);

  return (
    <DropdownMenuPrimitive.Root open={controlledOpen} onOpenChange={onOpenChange} modal={!anchored}>
      {anchored && position ? (
        // Older Radix dropdown builds lack Anchor; a zero-size Trigger is the position reference.
        <DropdownMenuPrimitive.Trigger asChild>
          <span
            aria-hidden="true"
            tabIndex={-1}
            className="pointer-events-none fixed size-px overflow-hidden opacity-0"
            style={{ left: position.x, top: position.y }}
          />
        </DropdownMenuPrimitive.Trigger>
      ) : trigger ? (
        <DropdownMenuPrimitive.Trigger asChild>{trigger}</DropdownMenuPrimitive.Trigger>
      ) : null}
      <DropdownMenuPrimitive.Portal>
        <DropdownMenuPrimitive.Content
          aria-label={ariaLabel}
          side={resolvedSide}
          align={resolvedAlign}
          sideOffset={resolvedSideOffset}
          collisionPadding={12}
          data-vui={dataVui}
          data-renderer="radix"
          data-anchored={anchored ? "true" : undefined}
          className={cn(contentBaseClass, contentClassName, className)}
          onCloseAutoFocus={(event) => {
            // Context menus are dismissed externally; avoid stealing focus back to a virtual anchor.
            if (anchored) {
              event.preventDefault();
            }
          }}
          {...contentProps}
        >
          {items.map((item) => (
            <DropdownMenuPrimitive.Item
              key={item.id}
              disabled={item.disabled}
              title={item.title}
              textValue={typeof item.label === "string" ? item.label : item.id}
              className={cn(
                itemBaseClass,
                item.danger ? itemDangerClass : null,
                item.danger ? dangerItemClassName : null,
                itemClassName,
              )}
              onSelect={(event) => {
                if (item.disabled) {
                  event.preventDefault();
                  return;
                }
                item.onSelect?.();
              }}
            >
              {item.icon ? (
                <span className="inline-grid shrink-0 place-items-center" data-slot="menu-item-icon" aria-hidden="true">
                  {item.icon}
                </span>
              ) : null}
              <span className="min-w-0 flex-1 truncate" data-slot="menu-item-label">
                {item.label}
              </span>
            </DropdownMenuPrimitive.Item>
          ))}
        </DropdownMenuPrimitive.Content>
      </DropdownMenuPrimitive.Portal>
    </DropdownMenuPrimitive.Root>
  );
}
