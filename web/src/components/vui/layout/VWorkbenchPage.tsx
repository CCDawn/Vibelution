import { type ComponentPropsWithoutRef, type ReactNode } from "react";

export type VWorkbenchPageProps = ComponentPropsWithoutRef<"section"> & {
  ariaLabel?: string;
  children: ReactNode;
};

export function VWorkbenchPage({
  ariaLabel,
  children,
  className,
  ...props
}: VWorkbenchPageProps) {
  return (
    <section
      {...props}
      data-vui="workbench-page"
      aria-label={ariaLabel}
      className={[
        "grid min-h-0 min-w-0 content-start gap-2 text-vui-fg-primary",
        "bg-transparent [--vui-workspace-sidebar:280px] [--vui-workspace-aside:300px]",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {children}
    </section>
  );
}
