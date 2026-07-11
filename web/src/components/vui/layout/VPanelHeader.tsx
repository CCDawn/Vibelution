import { type ReactNode } from "react";

export type VPanelHeaderProps = {
  title: ReactNode;
  eyebrow?: ReactNode;
  actions?: ReactNode;
  className?: string;
  headingLevel?: 2 | 3 | 4 | null;
  "data-vui"?: string;
};

const titleClassName =
  "m-0 text-[1rem] font-bold leading-[1.2] text-[var(--fg-primary)] [overflow-wrap:anywhere] [font-family:var(--font-display)]";

export function VPanelHeader({
  title,
  eyebrow,
  actions,
  className,
  headingLevel = 2,
  "data-vui": dataVui,
}: VPanelHeaderProps) {
  return (
    <div
      data-vui={dataVui ?? "panel-header"}
      className={["flex items-start justify-between gap-2 min-w-0", className]
        .filter(Boolean)
        .join(" ")}
    >
      <div className="min-w-0">
        {eyebrow ? (
          <p className="m-0 mb-px text-[var(--fg-tertiary)] text-[0.61rem] tracking-[0.07em] uppercase">
            {eyebrow}
          </p>
        ) : null}
        {headingLevel === null ? (
          <div className={titleClassName}>{title}</div>
        ) : headingLevel === 3 ? (
          <h3 className={titleClassName}>{title}</h3>
        ) : headingLevel === 4 ? (
          <h4 className={titleClassName}>{title}</h4>
        ) : (
          <h2 className={titleClassName}>{title}</h2>
        )}
      </div>
      {actions ? (
        <div className="inline-flex items-center justify-end gap-2 min-w-0">{actions}</div>
      ) : null}
    </div>
  );
}
