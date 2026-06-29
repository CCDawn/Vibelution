import { type ComponentPropsWithoutRef, type ReactNode } from "react";

import { VSurface } from "./VSurface";

export type VPanelProps = ComponentPropsWithoutRef<"section"> & {
  ariaLabel?: string;
  children: ReactNode;
};

export function VPanel({ ariaLabel, className, children, ...props }: VPanelProps) {
  return (
    <VSurface
      {...props}
      as="section"
      data-vui="panel"
      ariaLabel={ariaLabel}
      className={[
        "backdrop-blur-[1px]",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {children}
    </VSurface>
  );
}
