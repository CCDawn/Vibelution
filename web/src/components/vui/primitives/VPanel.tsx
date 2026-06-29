import { type ComponentPropsWithoutRef, type ReactNode } from "react";

export type VPanelProps = ComponentPropsWithoutRef<"section"> & {
  ariaLabel?: string;
  children: ReactNode;
};

export function VPanel({ ariaLabel, className, children, ...props }: VPanelProps) {
  return (
    <section
      {...props}
      data-vui="panel"
      aria-label={ariaLabel}
      className={[
        "min-w-0 rounded-[var(--radius-panel)] border border-vui-border-hairline bg-vui-surface-panel/82",
        "shadow-none backdrop-blur-[1px]",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {children}
    </section>
  );
}
