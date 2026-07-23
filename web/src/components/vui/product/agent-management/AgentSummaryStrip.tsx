import { ChevronDown } from "lucide-react";
import { type ReactNode } from "react";

import { type VuiTone } from "../../renderers/shared/buttonVariants";
import { VMetricStrip } from "../../index";

export type AgentSummaryMetric = {
  id: string;
  label: string;
  value: ReactNode;
  detail?: string;
  tone?: VuiTone;
};

export type AgentSummaryStatus = {
  label: string;
  title?: string;
  ariaLabel?: string;
  tone?: VuiTone;
};

export type AgentSummaryStripProps = {
  ariaLabel: string;
  metrics: AgentSummaryMetric[];
  secondaryMetrics?: AgentSummaryMetric[];
  moreLabel?: ReactNode;
  status?: AgentSummaryStatus;
};

export function AgentSummaryStrip({
  ariaLabel,
  metrics,
  secondaryMetrics,
  moreLabel = "更多",
  status,
}: AgentSummaryStripProps) {
  const hasSecondary = Boolean(secondaryMetrics && secondaryMetrics.length > 0);

  return (
    <div
      data-vui-product="agent-summary-strip"
      className="grid min-w-0 gap-1"
    >
      <VMetricStrip
        ariaLabel={ariaLabel}
        metrics={metrics}
        status={status}
      />
      {hasSecondary ? (
        <details className="group min-w-0">
          <summary className="inline-flex cursor-pointer list-none items-center gap-1 rounded-[var(--radius-control)] px-1.5 py-0.5 [font-size:var(--vui-font-xs)] font-bold text-[var(--fg-tertiary)] hover:bg-[var(--vui-surface-row-hover)] hover:text-[var(--fg-secondary)] [&::-webkit-details-marker]:hidden">
            <span>{moreLabel}</span>
            <ChevronDown
              size={13}
              className="transition-transform duration-150 group-[[open]]:rotate-180"
            />
          </summary>
          <div className="mt-1 min-w-0">
            <VMetricStrip
              ariaLabel={`${ariaLabel} · ${typeof moreLabel === "string" ? moreLabel : "more"}`}
              metrics={secondaryMetrics ?? []}
            />
          </div>
        </details>
      ) : null}
    </div>
  );
}
