/**
 * Progressive region loading — keep stable geometry; fill slots in place.
 *
 * Product contract (same as research overview):
 * - Mount the real layout chrome first (headers, columns, panel frames).
 * - While a query is pending, only the *data slots* show skeleton pulse.
 * - Do not swap an entire workbench main region for a fill VStateSurface mid-load.
 * - Empty / error still use VStateSurface after the query has settled.
 */

import { VSkeleton } from "../../components/vui";

export type ProgressiveRegionSkeletonProps = {
  label: string;
  className?: string;
  /** list = stacked rows; detail = header + body cards; panel = section blocks; canvas = node grid */
  variant?: "list" | "detail" | "panel" | "canvas" | "conversation";
};

export function ProgressiveRegionSkeleton({
  label,
  className = "",
  variant = "panel",
}: ProgressiveRegionSkeletonProps) {
  return (
    <div
      className={["grid min-h-0 min-w-0 content-start gap-2.5", className].filter(Boolean).join(" ")}
      role="status"
      aria-busy="true"
      aria-live="polite"
      aria-label={label}
      data-testid="progressive-region-skeleton"
      data-variant={variant}
    >
      <span className="sr-only">{label}</span>
      {variant === "list" ? <ListSkeleton /> : null}
      {variant === "detail" ? <DetailSkeleton /> : null}
      {variant === "panel" ? <PanelSkeleton /> : null}
      {variant === "canvas" ? <CanvasSkeleton /> : null}
      {variant === "conversation" ? <ConversationSkeleton /> : null}
    </div>
  );
}

function ListSkeleton() {
  return (
    <div className="grid min-w-0 content-start gap-2" aria-hidden="true">
      {Array.from({ length: 6 }, (_, index) => (
        <div
          key={index}
          className="grid min-h-[52px] grid-cols-[minmax(0,1fr)_auto] items-center gap-2 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] px-2.5 py-2"
        >
          <span className="grid min-w-0 gap-1.5">
            <VSkeleton className="h-3 w-[58%]" />
            <VSkeleton className="h-2.5 w-[82%] opacity-80" />
          </span>
          <VSkeleton className="h-5 w-12 rounded-full" />
        </div>
      ))}
    </div>
  );
}

function DetailSkeleton() {
  return (
    <div className="grid min-w-0 content-start gap-3" aria-hidden="true">
      <div className="grid min-w-0 gap-2">
        <VSkeleton className="h-2.5 w-16" />
        <VSkeleton className="h-5 w-[min(100%,18rem)]" />
      </div>
      <div className="flex min-w-0 flex-wrap gap-2">
        {Array.from({ length: 3 }, (_, index) => (
          <VSkeleton key={index} className="h-8 w-28 rounded-[var(--radius-control)]" />
        ))}
      </div>
      {Array.from({ length: 3 }, (_, index) => (
        <div
          key={index}
          className="grid min-w-0 gap-2 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-3"
        >
          <VSkeleton className="h-3 w-[40%]" />
          <VSkeleton className="h-2.5 w-full" />
          <VSkeleton className="h-2.5 w-[88%] opacity-80" />
        </div>
      ))}
    </div>
  );
}

function PanelSkeleton() {
  return (
    <div className="grid min-w-0 content-start gap-3" aria-hidden="true">
      {Array.from({ length: 2 }, (_, index) => (
        <div
          key={index}
          className="grid min-w-0 gap-2.5 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-3"
        >
          <VSkeleton className="h-3.5 w-[36%]" />
          <VSkeleton className="h-2.5 w-full" />
          <VSkeleton className="h-2.5 w-[92%] opacity-80" />
          <VSkeleton className="h-2.5 w-[70%] opacity-70" />
          <div className="flex gap-2 pt-1">
            <VSkeleton className="h-7 w-20 rounded-[var(--radius-control)]" />
            <VSkeleton className="h-7 w-16 rounded-[var(--radius-control)]" />
          </div>
        </div>
      ))}
    </div>
  );
}

function CanvasSkeleton() {
  return (
    <div
      className="relative grid min-h-[min(420px,50vh)] min-w-0 flex-1 place-content-center gap-4 overflow-hidden rounded-[var(--radius-panel)] border border-dashed border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-4"
      aria-hidden="true"
    >
      <div className="grid grid-cols-3 gap-6 opacity-90">
        {Array.from({ length: 6 }, (_, index) => (
          <VSkeleton
            key={index}
            shape="block"
            className="h-16 w-28 min-h-16 border border-[var(--vui-border-subtle)]"
          />
        ))}
      </div>
    </div>
  );
}

function ConversationSkeleton() {
  return (
    <div className="grid min-h-0 min-w-0 flex-1 grid-rows-[minmax(0,1fr)_auto] gap-2" aria-hidden="true">
      <div className="grid min-h-0 content-start gap-3 overflow-hidden p-1">
        <div className="grid max-w-[85%] grid-cols-[28px_minmax(0,1fr)] gap-2">
          <VSkeleton shape="circle" className="size-7" />
          <span className="grid gap-1.5">
            <VSkeleton className="h-3 w-24" />
            <VSkeleton className="h-2.5 w-full" />
            <VSkeleton className="h-2.5 w-[88%] opacity-80" />
          </span>
        </div>
        <div className="ml-auto grid w-[70%] gap-1.5">
          <VSkeleton className="h-10 w-full rounded-[var(--radius-control)]" />
        </div>
        <div className="grid max-w-[85%] grid-cols-[28px_minmax(0,1fr)] gap-2">
          <VSkeleton shape="circle" className="size-7" />
          <span className="grid gap-1.5">
            <VSkeleton className="h-3 w-20" />
            <VSkeleton className="h-2.5 w-full" />
            <VSkeleton className="h-2.5 w-[76%] opacity-80" />
          </span>
        </div>
      </div>
      <VSkeleton className="h-11 w-full rounded-[var(--radius-control)]" />
    </div>
  );
}
