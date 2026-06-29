import { type ComponentPropsWithoutRef } from "react";

import { type VuiTone } from "../renderers/heroui/heroVariants";

export type VMetricStripMetric = {
  detail?: string;
  id?: string;
  label: string;
  tone?: VuiTone;
  value: string | number;
};

export type VMetricStripStatus = {
  ariaLabel?: string;
  label: string;
  title?: string;
  tone?: VuiTone;
};

export type VMetricStripProps = Omit<ComponentPropsWithoutRef<"section">, "children"> & {
  ariaLabel: string;
  metrics: VMetricStripMetric[];
  status?: VMetricStripStatus;
};

function toneTextClass(tone: VuiTone | undefined): string {
  if (tone === "accent" || tone === "info") {
    return "text-vui-accent-cool";
  }
  if (tone === "success") {
    return "text-[var(--state-success)]";
  }
  if (tone === "warning") {
    return "text-[var(--state-warning)]";
  }
  if (tone === "danger") {
    return "text-[var(--state-error)]";
  }
  return "text-vui-fg-primary";
}

export function VMetricStrip({
  ariaLabel,
  className,
  metrics,
  status,
  ...props
}: VMetricStripProps) {
  return (
    <section
      {...props}
      data-vui="metric-strip"
      aria-label={ariaLabel}
      className={[
        "grid min-w-0 grid-cols-[repeat(auto-fit,minmax(88px,1fr))] rounded-[var(--radius-control)] border border-vui-border-hairline bg-vui-surface-toolbar",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {status ? (
        <div className="grid min-w-[88px] items-center border-r border-vui-border-hairline px-2 py-1">
          <span
            title={status.title}
            aria-label={status.ariaLabel}
            className={[
              "vui-tone-" + (status.tone ?? "neutral"),
              "inline-flex min-w-0 items-center justify-center truncate rounded-full border border-vui-border-hairline px-2 py-0.5 text-[0.68rem] font-semibold leading-none",
            ].join(" ")}
          >
            {status.label}
          </span>
        </div>
      ) : null}
      {metrics.map((metric, index) => (
        <div
          key={metric.id ?? `${metric.label}:${index}`}
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
          <strong className={["truncate text-[0.8rem] leading-none", toneTextClass(metric.tone)].join(" ")}>
            {metric.value}
          </strong>
        </div>
      ))}
    </section>
  );
}
