import { type ReactNode } from "react";

export type TeamSourceEmptyStateFact = {
  key: string;
  label: ReactNode;
  value: ReactNode;
};

export type TeamSourceEmptyStateProps = {
  actions?: ReactNode;
  description: ReactNode;
  facts?: TeamSourceEmptyStateFact[];
  footer?: ReactNode;
  title: ReactNode;
};

const PANEL =
  "grid min-w-0 self-start items-start gap-2 rounded-[var(--radius-control)] border border-dashed " +
  "border-[color:color-mix(in_srgb,var(--accent-cool)_26%,var(--border-soft))] " +
  "bg-[color:color-mix(in_srgb,var(--accent-cool)_5%,var(--source-workbench-card))] px-3 py-2.5 text-left max-[560px]:gap-1.5 max-[560px]:px-2 max-[560px]:py-2";

const COPY = "grid min-w-0 gap-0.5";
const TITLE = "min-w-0 text-[0.78rem] font-[840] leading-tight text-[var(--fg-primary)]";
const DESCRIPTION = "min-w-0 text-[var(--vui-font-xs)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]";
const FACTS = "grid min-w-0 grid-cols-[repeat(auto-fit,minmax(9rem,1fr))] gap-1.5 max-[560px]:grid-cols-[repeat(2,minmax(0,1fr))]";
const FACT =
  "grid min-w-0 gap-0.5 rounded-[7px] border border-[color:var(--border-soft)] " +
  "bg-[color:var(--source-workbench-card)] px-2 py-1.5";
const FACT_LABEL = "truncate text-[0.6rem] font-[760] uppercase text-[var(--fg-tertiary)]";
const FACT_VALUE = "truncate text-[0.72rem] font-[820] text-[var(--fg-primary)]";
const ACTIONS = "flex min-w-0 flex-wrap items-center gap-1.5";
const FOOTER = "min-w-0 text-[0.62rem] font-[720] leading-tight text-[var(--fg-tertiary)]";

export function TeamSourceEmptyState({
  actions,
  description,
  facts = [],
  footer,
  title,
}: TeamSourceEmptyStateProps) {
  return (
    <div data-vui-product="team-source-empty-state" className={PANEL}>
      <div className={COPY}>
        <strong className={TITLE}>{title}</strong>
        <span className={DESCRIPTION}>{description}</span>
      </div>
      {facts.length ? (
        <div data-slot="source-empty-facts" className={FACTS}>
          {facts.map((fact) => (
            <span key={fact.key} className={FACT}>
              <small className={FACT_LABEL}>{fact.label}</small>
              <strong className={FACT_VALUE}>{fact.value}</strong>
            </span>
          ))}
        </div>
      ) : null}
      {actions ? <div className={ACTIONS}>{actions}</div> : null}
      {footer ? <div className={FOOTER}>{footer}</div> : null}
    </div>
  );
}
