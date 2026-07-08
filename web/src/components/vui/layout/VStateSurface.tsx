import { type ComponentPropsWithoutRef, type ReactNode } from "react";

export type VStateSurfaceTone = "info" | "loading" | "empty" | "unavailable" | "error";

export type VStateSurfaceFact = {
  key: string;
  label: ReactNode;
  value: ReactNode;
};

export type VStateSurfaceProps = Omit<ComponentPropsWithoutRef<"section">, "title"> & {
  actions?: ReactNode;
  busy?: boolean;
  facts?: VStateSurfaceFact[];
  icon?: ReactNode;
  skeletonLines?: boolean | number;
  title: ReactNode;
  tone?: VStateSurfaceTone;
};

const BASE =
  "grid min-w-0 w-full content-start gap-2 rounded-[var(--radius-control)] border p-3 text-left " +
  "text-[var(--vui-font-xs)] leading-[var(--vui-line-readable)]";

const TONE: Record<VStateSurfaceTone, string> = {
  info:
    "border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] text-[var(--fg-secondary)]",
  loading:
    "border-[color-mix(in_srgb,var(--accent-cool)_28%,var(--vui-border-subtle))] " +
    "bg-[color-mix(in_srgb,var(--accent-cool)_7%,var(--vui-surface-row))] text-[var(--fg-secondary)]",
  empty:
    "border-dashed border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] text-[var(--fg-secondary)]",
  unavailable:
    "border-[color-mix(in_srgb,var(--state-warning)_34%,var(--vui-border-subtle))] " +
    "bg-[color-mix(in_srgb,var(--state-warning)_8%,var(--vui-surface-row))] text-[var(--fg-secondary)]",
  error:
    "border-[color-mix(in_srgb,var(--state-error)_36%,var(--vui-border-subtle))] " +
    "bg-[color-mix(in_srgb,var(--state-error)_8%,var(--vui-surface-row))] text-[var(--fg-secondary)]",
};

const HEADER = "grid min-w-0 grid-cols-[auto_minmax(0,1fr)] items-start gap-2";
const ICON =
  "mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-[var(--radius-control)] " +
  "border border-[color-mix(in_srgb,currentColor_22%,transparent)] text-[var(--accent-cool)]";
const COPY = "grid min-w-0 gap-0.5";
const TITLE = "min-w-0 text-[var(--vui-font-sm)] font-[820] leading-tight text-[var(--fg-primary)]";
const DESCRIPTION = "min-w-0 max-w-[72ch] text-[var(--vui-font-xs)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]";
const FACTS = "grid min-w-0 grid-cols-[repeat(auto-fit,minmax(8rem,1fr))] gap-1.5";
const FACT =
  "grid min-w-0 gap-0.5 rounded-[7px] border border-[var(--vui-border-subtle)] " +
  "bg-[color-mix(in_srgb,var(--vui-surface-panel)_72%,transparent)] px-2 py-1.5";
const FACT_LABEL = "truncate text-[0.6rem] font-[760] uppercase text-[var(--fg-tertiary)]";
const FACT_VALUE = "truncate text-[0.72rem] font-[820] text-[var(--fg-primary)]";
const ACTIONS = "flex min-w-0 flex-wrap items-center gap-1.5";
const SKELETON_STACK = "grid min-w-0 gap-1.5";
const SKELETON_LINE =
  "block h-2 animate-pulse rounded-full bg-[color-mix(in_srgb,var(--accent-cool)_22%,var(--vui-border-subtle))]";
const SKELETON_WIDTHS = ["w-[min(100%,520px)]", "w-[min(72%,380px)]", "w-[min(46%,260px)]"];

function skeletonLineCount(value: boolean | number | undefined): number {
  if (value === true) {
    return 2;
  }
  if (typeof value === "number") {
    return Math.max(0, Math.min(3, Math.floor(value)));
  }
  return 0;
}

export function VStateSurface({
  actions,
  busy,
  children,
  className,
  facts = [],
  icon,
  skeletonLines,
  title,
  tone = "info",
  ...props
}: VStateSurfaceProps) {
  const lineCount = skeletonLineCount(skeletonLines);
  const isBusy = busy ?? tone === "loading";

  return (
    <section
      {...props}
      aria-busy={isBusy || undefined}
      data-tone={tone}
      data-vui="state-surface"
      className={[BASE, TONE[tone], className].filter(Boolean).join(" ")}
    >
      <div className={icon ? HEADER : COPY}>
        {icon ? <span className={ICON}>{icon}</span> : null}
        <div className={COPY}>
          <strong className={TITLE}>{title}</strong>
          {children ? <span className={DESCRIPTION}>{children}</span> : null}
        </div>
      </div>
      {facts.length ? (
        <div className={FACTS}>
          {facts.map((fact) => (
            <span key={fact.key} className={FACT}>
              <small className={FACT_LABEL}>{fact.label}</small>
              <strong className={FACT_VALUE}>{fact.value}</strong>
            </span>
          ))}
        </div>
      ) : null}
      {lineCount ? (
        <div className={SKELETON_STACK} aria-hidden="true">
          {Array.from({ length: lineCount }).map((_, index) => (
            <span key={index} className={`${SKELETON_LINE} ${SKELETON_WIDTHS[index]}`} />
          ))}
        </div>
      ) : null}
      {actions ? <div className={ACTIONS}>{actions}</div> : null}
    </section>
  );
}
