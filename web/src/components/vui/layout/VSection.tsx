import { type ComponentPropsWithoutRef, type ReactNode } from "react";

import { VContextualHint } from "../primitives/VContextualHint";

export type VSectionProps = ComponentPropsWithoutRef<"section"> & {
  actions?: ReactNode;
  children?: ReactNode;
  eyebrow?: ReactNode;
  headerClassName?: string;
  meta?: ReactNode;
  title: ReactNode;
  tooltip?: ReactNode;
  tooltipLabel?: string;
};

export function VSection({
  actions,
  children,
  className,
  eyebrow,
  headerClassName,
  meta,
  title,
  tooltip,
  tooltipLabel,
  ...props
}: VSectionProps) {
  return (
    <section
      {...props}
      data-vui="section"
      className={["grid min-w-0 gap-2", className].filter(Boolean).join(" ")}
    >
      <header
        className={[
          "grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-start gap-2",
          headerClassName,
        ]
          .filter(Boolean)
          .join(" ")}
      >
        <div className="grid min-w-0 gap-0.5">
          {eyebrow ? (
            <span className="truncate [font-size:var(--vui-font-xs)] font-semibold uppercase tracking-[0.06em] text-vui-fg-tertiary">
              {eyebrow}
            </span>
          ) : null}
          <div className="flex min-w-0 flex-wrap items-baseline gap-1.5">
            <h2 className="m-0 min-w-0 truncate [font-size:var(--vui-font-md)] font-bold leading-tight text-vui-fg-primary">
              {title}
            </h2>
            {tooltip ? (
              <VContextualHint
                label={tooltipLabel ?? "Section details"}
                content={tooltip}
                width="wide"
              />
            ) : null}
            {meta ? (
              <span className="min-w-0 truncate [font-size:var(--vui-font-xs)] font-semibold text-vui-fg-tertiary">
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
