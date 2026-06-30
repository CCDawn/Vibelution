import { type ComponentPropsWithoutRef, type ReactNode } from "react";

export type VEmptyStateProps = ComponentPropsWithoutRef<"div"> & {
  actions?: ReactNode;
  icon?: ReactNode;
  title: ReactNode;
};

export function VEmptyState({
  actions,
  children,
  className,
  icon,
  title,
  ...props
}: VEmptyStateProps) {
  return (
    <div
      {...props}
      data-vui="empty-state"
      className={[
        "grid min-h-24 min-w-0 place-items-center gap-1 rounded-md",
        "border border-dashed border-vui-border-subtle bg-vui-surface-glass px-3 py-4 text-center",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {icon ? <div className="text-vui-fg-tertiary">{icon}</div> : null}
      <strong className="text-sm text-vui-fg-secondary">{title}</strong>
      {children ? <span className="text-xs text-vui-fg-tertiary">{children}</span> : null}
      {actions ? <div className="mt-1 flex min-w-0 items-center justify-center gap-1.5">{actions}</div> : null}
    </div>
  );
}
