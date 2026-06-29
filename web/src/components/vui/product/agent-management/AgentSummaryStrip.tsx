import { type VuiTone } from "../../renderers/heroui/heroVariants";
import { VMetricStrip } from "../../index";

export type AgentSummaryMetric = {
  id: string;
  label: string;
  value: string | number;
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
  status?: AgentSummaryStatus;
};

export function AgentSummaryStrip({
  ariaLabel,
  metrics,
  status,
}: AgentSummaryStripProps) {
  return (
    <VMetricStrip
      data-vui-product="agent-summary-strip"
      ariaLabel={ariaLabel}
      metrics={metrics}
      status={status}
    />
  );
}
