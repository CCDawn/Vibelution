import { type ReactNode } from "react";
import { SearchX } from "lucide-react";

export type TeamSourceEmptyStateFact = {
  key: string;
  label: ReactNode;
  value: ReactNode;
};

export type TeamSourceEmptyStateProps = {
  actions?: ReactNode;
  description?: ReactNode;
  facts?: TeamSourceEmptyStateFact[];
  footer?: ReactNode;
  icon?: ReactNode;
  title: ReactNode;
};

const PANEL =
  "grid min-h-[132px] min-w-0 w-full content-center justify-items-center gap-3 rounded-[12px] border border-dashed " +
  "border-[var(--vui-border-subtle)] bg-transparent px-6 py-7 text-center";

const VISUAL =
  "grid size-10 place-items-center rounded-[10px] bg-[var(--vui-control-muted)] text-[var(--fg-secondary)] shadow-[inset_0_0_0_1px_var(--vui-border-subtle)]";
const COPY = "grid max-w-sm min-w-0 justify-items-center gap-1";
const TITLE = "min-w-0 text-[0.86rem] font-[680] leading-tight tracking-[-0.008em] text-[var(--fg-primary)]";
const DESCRIPTION = "min-w-0 [font-size:var(--vui-font-xs)] leading-[var(--vui-line-readable)] text-[var(--fg-tertiary)]";
const FACTS = "flex min-w-0 max-w-xl flex-wrap items-center justify-center gap-x-4 gap-y-1.5";
const FACT =
  "inline-flex min-w-0 items-baseline gap-1.5 [font-size:var(--vui-font-xs)]";
const FACT_LABEL = "truncate font-[550] text-[var(--fg-tertiary)]";
const FACT_VALUE = "truncate font-[680] text-[var(--fg-primary)]";
const ACTIONS = "flex min-w-0 flex-wrap items-center justify-center gap-1.5";
const FOOTER = "min-w-0 [font-size:var(--vui-font-xs)] font-[550] leading-tight text-[var(--fg-tertiary)]";

export function TeamSourceEmptyState({
  actions,
  description,
  facts = [],
  footer,
  icon,
  title,
}: TeamSourceEmptyStateProps) {
  const visual = icon ?? <SearchX size={19} strokeWidth={1.8} aria-hidden="true" />;

  return (
    <div data-vui-product="team-source-empty-state" className={PANEL}>
      <div data-slot="source-empty-visual" className={VISUAL}>{visual}</div>
      <div className={COPY}>
        <strong className={TITLE}>{title}</strong>
        {description ? (
          <span data-slot="source-empty-description" className={DESCRIPTION}>
            {description}
          </span>
        ) : null}
      </div>
      {facts.length ? (
        <dl data-slot="source-empty-facts" className={FACTS}>
          {facts.map((fact) => (
            <div key={fact.key} className={FACT}>
              <dt className={FACT_LABEL}>{fact.label}</dt>
              <dd className={FACT_VALUE}>{fact.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {actions ? <div className={ACTIONS}>{actions}</div> : null}
      {footer ? <div className={FOOTER}>{footer}</div> : null}
    </div>
  );
}
