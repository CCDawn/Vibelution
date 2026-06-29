import { type ComponentPropsWithoutRef } from "react";

export type VActionGroupProps = ComponentPropsWithoutRef<"div"> & {
  ariaLabel: string;
};

export function VActionGroup({ ariaLabel, className, ...props }: VActionGroupProps) {
  return (
    <div
      {...props}
      data-vui="action-group"
      role="group"
      aria-label={ariaLabel}
      className={[
        "flex min-w-0 flex-wrap items-center gap-1.5 rounded-[var(--radius-control)]",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    />
  );
}
