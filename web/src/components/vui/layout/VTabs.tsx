import * as TabsPrimitive from "@radix-ui/react-tabs";
import { type ReactNode } from "react";

import { cn } from "../lib/cn";
import { type VuiDensity } from "../renderers/shared/buttonVariants";

export type VTabsItem = {
  id: string;
  label: ReactNode;
  disabled?: boolean;
  /** Optional panel body for this tab. */
  content?: ReactNode;
};

export type VTabsProps = {
  items: VTabsItem[];
  /** Controlled active tab id. */
  value?: string;
  /** Uncontrolled initial tab id. Defaults to first enabled item. */
  defaultValue?: string;
  onValueChange?: (value: string) => void;
  density?: VuiDensity;
  className?: string;
  listClassName?: string;
  /** Extra classes on each tab trigger (merged after density chrome). */
  triggerClassName?: string;
  contentClassName?: string;
  "aria-label"?: string;
  "data-vui"?: string;
};

/**
 * shadcn/Radix tabs — compact workbench section switcher.
 * Prefer over ad-hoc button-row "tabs" in routes.
 */
export function VTabs({
  items,
  value,
  defaultValue,
  onValueChange,
  density = "compact",
  className,
  listClassName,
  triggerClassName,
  contentClassName,
  "aria-label": ariaLabel,
  "data-vui": dataVui = "tabs",
}: VTabsProps) {
  const firstEnabled = items.find((item) => !item.disabled)?.id;
  const resolvedDefault = defaultValue ?? firstEnabled;
  const hasPanels = items.some((item) => item.content != null);
  const dense = density === "compact";

  return (
    <TabsPrimitive.Root
      value={value}
      defaultValue={value === undefined ? resolvedDefault : undefined}
      onValueChange={onValueChange}
      className={cn("grid min-w-0 gap-2", className)}
      data-vui={dataVui}
      data-density={density}
      data-renderer="radix"
    >
      <TabsPrimitive.List
        aria-label={ariaLabel}
        className={cn(
          "inline-flex min-w-0 max-w-full flex-wrap items-center gap-0.5 rounded-[var(--radius-control)]",
          "border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] p-0.5",
          listClassName,
        )}
        data-slot="tabs-list"
      >
        {items.map((item) => (
          <TabsPrimitive.Trigger
            key={item.id}
            value={item.id}
            disabled={item.disabled}
            className={cn(
              "inline-flex min-w-0 max-w-full items-center justify-center gap-1.5 rounded-[calc(var(--radius-control)-2px)]",
              "px-2.5 font-semibold text-[var(--fg-secondary)] outline-none transition-colors duration-150",
              "hover:text-[var(--fg-primary)]",
              "focus-visible:ring-2 focus-visible:ring-[color-mix(in_srgb,var(--accent-cool)_45%,transparent)]",
              "data-[state=active]:bg-[var(--vui-surface-panel)] data-[state=active]:text-[var(--fg-primary)]",
              "data-[state=active]:shadow-none data-[state=active]:border data-[state=active]:border-[var(--vui-border-subtle)]",
              "disabled:pointer-events-none disabled:opacity-45",
              dense
                ? "min-h-[calc(var(--vui-control-height-sm)-2px)] text-[var(--vui-font-xs)]"
                : "min-h-[calc(var(--vui-control-height-md)-2px)] text-[var(--vui-font-sm)]",
              triggerClassName,
            )}
            data-slot="tabs-trigger"
          >
            <span className="min-w-0 truncate">{item.label}</span>
          </TabsPrimitive.Trigger>
        ))}
      </TabsPrimitive.List>
      {hasPanels
        ? items.map((item) =>
            item.content != null ? (
              <TabsPrimitive.Content
                key={item.id}
                value={item.id}
                className={cn(
                  "min-w-0 outline-none focus-visible:ring-2 focus-visible:ring-[color-mix(in_srgb,var(--accent-cool)_35%,transparent)]",
                  contentClassName,
                )}
                data-slot="tabs-content"
              >
                {item.content}
              </TabsPrimitive.Content>
            ) : null,
          )
        : null}
    </TabsPrimitive.Root>
  );
}
