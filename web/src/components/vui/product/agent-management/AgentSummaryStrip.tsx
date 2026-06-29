import { type VuiTone } from "../../renderers/heroui/heroVariants";

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

function metricToneClass(tone: VuiTone | undefined): string {
  if (tone === "success") {
    return "text-emerald-700";
  }
  if (tone === "warning") {
    return "text-amber-700";
  }
  if (tone === "danger") {
    return "text-red-700";
  }
  if (tone === "accent") {
    return "text-vui-accent-cool";
  }
  return "text-vui-fg-primary";
}

export function AgentSummaryStrip({
  ariaLabel,
  metrics,
  status,
}: AgentSummaryStripProps) {
  return (
    <section
      data-vui-product="agent-summary-strip"
      aria-label={ariaLabel}
      className="grid min-w-0 grid-cols-[repeat(auto-fit,minmax(88px,1fr))] rounded-[var(--radius-control)] border border-vui-border-hairline bg-vui-surface-panel/80"
    >
      {status ? (
        <div className="grid min-w-[88px] items-center border-r border-vui-border-hairline px-2 py-1">
          <span
            title={status.title}
            aria-label={status.ariaLabel}
            className={[
              "inline-flex min-w-0 items-center justify-center truncate rounded-full border border-vui-border-hairline px-2 py-0.5 text-[0.68rem] font-semibold leading-none",
              metricToneClass(status.tone),
            ].join(" ")}
          >
            {status.label}
          </span>
        </div>
      ) : null}
      {metrics.map((metric, index) => (
        <div
          key={metric.id}
          title={metric.detail}
          className={[
            "grid min-w-[88px] grid-cols-[minmax(0,1fr)_auto] items-baseline gap-1 px-2 py-1",
            index === metrics.length - 1
              ? ""
              : "border-r border-vui-border-hairline",
          ]
            .filter(Boolean)
            .join(" ")}
        >
          <span className="truncate text-[0.63rem] font-semibold uppercase tracking-[0.04em] text-vui-fg-tertiary">
            {metric.label}
          </span>
          <strong
            className={[
              "truncate text-[0.8rem] leading-none",
              metricToneClass(metric.tone),
            ].join(" ")}
          >
            {metric.value}
          </strong>
        </div>
      ))}
    </section>
  );
}
