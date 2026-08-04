import { type ComponentPropsWithoutRef } from "react";

import { cn } from "../lib/cn";

export type VSkeletonProps = ComponentPropsWithoutRef<"span"> & {
  /**
   * Visual shape. `line` = text row; `block` = card/panel body; `circle` = avatar/count.
   */
  shape?: "line" | "block" | "circle";
};

const pulseClass =
  "animate-pulse bg-[color-mix(in_srgb,var(--vui-border-subtle)_72%,transparent)] motion-reduce:animate-none";

const shapeClass: Record<NonNullable<VSkeletonProps["shape"]>, string> = {
  line: "block h-2.5 w-full max-w-full rounded-full",
  block: "block min-h-16 w-full rounded-[var(--radius-control)]",
  circle: "inline-block size-8 shrink-0 rounded-full",
};

/**
 * Shadcn-style skeleton pulse for progressive loading.
 * Prefer geometry shells (region templates) that compose multiple VSkeleton slots
 * over swapping an entire workbench region for a fill loading title.
 */
export function VSkeleton({
  className,
  shape = "line",
  "aria-hidden": ariaHidden = true,
  ...props
}: VSkeletonProps) {
  return (
    <span
      {...props}
      aria-hidden={ariaHidden}
      data-vui="skeleton"
      data-shape={shape}
      className={cn(pulseClass, shapeClass[shape], className)}
    />
  );
}
