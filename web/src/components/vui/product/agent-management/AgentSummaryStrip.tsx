import { type VuiTone } from "../../renderers/heroui/heroVariants";

export type AgentSummaryMetric = {
  id: string;
  label: string;
  value: string | number;
  detail?: string;
  tone?: VuiTone;
};

export type AgentSummaryStripProps = {
  ariaLabel: string;
  metrics: AgentSummaryMetric[];
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
}: AgentSummaryStripProps) {
  return (
    <section
      data-vui-product="agent-summary-strip"
      aria-label={ariaLabel}
      className="grid min-w-0 grid-flow-col auto-cols-[minmax(72px,1fr)] overflow-hidden rounded-[var(--radius-control)] border border-vui-border-hairline bg-vui-surface-panel/80"
    >
      {metrics.map((metric, index) => (
        <div
          key={metric.id}
          title={metric.detail}
          className={[
            "grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-baseline gap-1 px-2 py-1",
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
