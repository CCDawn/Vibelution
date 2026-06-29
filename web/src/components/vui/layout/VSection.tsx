import { type ComponentPropsWithoutRef, type ReactNode } from "react";

export type VSectionProps = ComponentPropsWithoutRef<"section"> & {
  actions?: ReactNode;
  children: ReactNode;
  eyebrow?: ReactNode;
  meta?: ReactNode;
  title: ReactNode;
};

export function VSection({
  actions,
  children,
  className,
  eyebrow,
  meta,
  title,
  ...props
}: VSectionProps) {
  return (
    <section
      {...props}
      data-vui="section"
      className={["grid min-w-0 gap-2", className].filter(Boolean).join(" ")}
    >
      <header className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-start gap-2">
        <div className="grid min-w-0 gap-0.5">
          {eyebrow ? (
            <span className="truncate text-[0.62rem] font-semibold uppercase tracking-[0.06em] text-vui-fg-tertiary">
              {eyebrow}
            </span>
          ) : null}
          <div className="flex min-w-0 flex-wrap items-baseline gap-1.5">
            <h2 className="m-0 min-w-0 truncate text-[0.9rem] font-bold leading-tight text-vui-fg-primary">
              {title}
            </h2>
            {meta ? (
              <span className="min-w-0 truncate text-[0.72rem] font-semibold text-vui-fg-tertiary">
                {meta}
              </span>
            ) : null}
          </div>
        </div>
        {actions ? <div className="min-w-0 justify-self-end">{actions}</div> : null}
      </header>
      {children}
    </section>
  );
}
