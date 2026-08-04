import { type ComponentPropsWithoutRef, type ReactNode } from "react";

import { cn } from "../lib/cn";

export type VStateSurfaceTone = "info" | "loading" | "empty" | "unavailable" | "error";
export type VStateSurfaceDensity = "default" | "compact";

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
  /**
   * Occupy the parent workbench region (flex-1 + min height) so loading/empty
   * is not a one-line label above a large empty floor.
   */
  fill?: boolean;
  /**
   * Compact density for inline alerts (failed banners, notices): tighter padding
   * and content-sized fact chips instead of full-width 1fr cards.
   */
  density?: VStateSurfaceDensity;
};

const BASE =
  "grid min-w-0 w-full content-start gap-2 rounded-[var(--radius-control)] border p-3 text-left " +
  "[font-size:var(--vui-font-xs)] leading-[var(--vui-line-readable)]";

const BASE_COMPACT =
  "grid min-w-0 w-full content-start gap-1.5 rounded-[var(--radius-control)] border px-2.5 py-2 text-left " +
  "[font-size:var(--vui-font-xs)] leading-[var(--vui-line-readable)]";

/** Full-region occupancy for board/canvas/list-detail main slots. */
const FILL =
  "h-full min-h-[min(100%,22rem)] flex-1 content-center place-content-center self-stretch p-4 " +
  "sm:min-h-[min(100%,28rem)]";

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
const HEADER_COMPACT = "grid min-w-0 grid-cols-[auto_minmax(0,1fr)] items-start gap-1.5";
const ICON =
  "mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-[var(--radius-control)] " +
  "border border-[color-mix(in_srgb,currentColor_22%,transparent)] text-[var(--accent-cool)]";
const ICON_COMPACT =
  "mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-[var(--radius-control)] " +
  "border border-[color-mix(in_srgb,currentColor_22%,transparent)] text-[var(--accent-cool)]";
const COPY = "grid min-w-0 gap-0.5";
const TITLE = "min-w-0 [font-size:var(--vui-font-sm)] font-[820] leading-tight text-[var(--fg-primary)]";
const TITLE_COMPACT = "min-w-0 [font-size:var(--vui-font-xs)] font-[820] leading-tight text-[var(--fg-primary)]";
const DESCRIPTION =
  "min-w-0 max-w-[72ch] [font-size:var(--vui-font-xs)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]";
const DESCRIPTION_COMPACT =
  "min-w-0 max-w-[88ch] [font-size:var(--vui-font-xs)] leading-snug text-[var(--fg-secondary)] " +
  "[display:-webkit-box] [-webkit-box-orient:vertical] [-webkit-line-clamp:2]";
/** Stretching cards — good for sparse overview; bad for 2 short facts on wide screens. */
const FACTS = "grid min-w-0 grid-cols-[repeat(auto-fit,minmax(8rem,1fr))] gap-1.5";
/** Content-sized chips that wrap; no full-row empty floors. */
const FACTS_COMPACT = "flex min-w-0 flex-wrap items-stretch gap-1.5";
const FACT =
  "grid min-w-0 gap-0.5 rounded-[7px] border border-[var(--vui-border-subtle)] " +
  "bg-[color-mix(in_srgb,var(--vui-surface-panel)_72%,transparent)] px-2 py-1.5";
const FACT_COMPACT =
  "grid min-w-0 max-w-[min(100%,18rem)] gap-0 rounded-[7px] border border-[var(--vui-border-subtle)] " +
  "bg-[color-mix(in_srgb,var(--vui-surface-panel)_72%,transparent)] px-2 py-1 " +
  "grid-cols-[auto_minmax(0,1fr)] items-baseline gap-x-1.5 gap-y-0";
const FACT_LABEL = "truncate text-[0.6rem] font-[760] uppercase text-[var(--fg-tertiary)]";
const FACT_LABEL_COMPACT = "shrink-0 text-[0.6rem] font-[760] uppercase text-[var(--fg-tertiary)]";
const FACT_VALUE = "truncate text-[0.72rem] font-[820] text-[var(--fg-primary)]";
const FACT_VALUE_COMPACT = "min-w-0 truncate font-mono text-[0.72rem] font-[820] text-[var(--fg-primary)]";
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
  density = "default",
  facts = [],
  fill = false,
  icon,
  skeletonLines,
  title,
  tone = "info",
  ...props
}: VStateSurfaceProps) {
  const compact = density === "compact";
  const resolvedSkeleton =
    skeletonLines === undefined && (fill || tone === "loading")
      ? fill
        ? 3
        : tone === "loading"
          ? 2
          : false
      : skeletonLines;
  const lineCount = skeletonLineCount(resolvedSkeleton);
  const isBusy = busy ?? tone === "loading";

  return (
    <section
      {...props}
      aria-busy={isBusy || undefined}
      data-tone={tone}
      data-fill={fill ? "true" : "false"}
      data-density={density}
      data-vui="state-surface"
      className={cn(
        compact ? BASE_COMPACT : BASE,
        TONE[tone],
        fill ? FILL : undefined,
        className,
      )}
    >
      <div className={icon ? (compact ? HEADER_COMPACT : HEADER) : COPY}>
        {icon ? <span className={compact ? ICON_COMPACT : ICON}>{icon}</span> : null}
        <div className={COPY}>
          <strong className={compact ? TITLE_COMPACT : TITLE}>{title}</strong>
          {children ? (
            <span className={compact ? DESCRIPTION_COMPACT : DESCRIPTION}>{children}</span>
          ) : null}
        </div>
      </div>
      {facts.length ? (
        <div className={compact ? FACTS_COMPACT : FACTS} data-vui="state-surface-facts">
          {facts.map((fact) => (
            <span key={fact.key} className={compact ? FACT_COMPACT : FACT}>
              <small className={compact ? FACT_LABEL_COMPACT : FACT_LABEL}>{fact.label}</small>
              <strong className={compact ? FACT_VALUE_COMPACT : FACT_VALUE}>{fact.value}</strong>
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
