import { type ComponentPropsWithoutRef, type ReactNode } from "react";

export type VRouteHeaderProps = ComponentPropsWithoutRef<"header"> & {
  actions?: ReactNode;
  eyebrow?: ReactNode;
  meta?: ReactNode;
  title: ReactNode;
};

export function VRouteHeader({
  actions,
  className,
  eyebrow,
  meta,
  title,
  ...props
}: VRouteHeaderProps) {
  return (
    <header
      {...props}
      data-vui="route-header"
      className={[
        "grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-2",
        "border border-vui-border-subtle bg-vui-surface-glass px-2.5 py-2",
        "shadow-[var(--vui-shadow-hairline)] backdrop-blur-md",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <div className="grid min-w-0 gap-0.5">
        {eyebrow ? (
          <span className="truncate text-[0.64rem] font-semibold uppercase tracking-normal text-vui-fg-tertiary">
            {eyebrow}
          </span>
        ) : null}
        <div className="flex min-w-0 flex-wrap items-baseline gap-1.5">
          <h1 className="m-0 min-w-0 truncate text-[0.95rem] font-bold leading-tight text-vui-fg-primary">
            {title}
          </h1>
          {meta ? (
            <span className="min-w-0 truncate text-[0.72rem] font-semibold text-vui-fg-tertiary">
              {meta}
            </span>
          ) : null}
        </div>
      </div>
      {actions ? <div className="min-w-0 justify-self-end">{actions}</div> : null}
    </header>
  );
}
