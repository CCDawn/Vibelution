import { type ComponentPropsWithoutRef, type ReactNode } from "react";

import { type VuiTone } from "../renderers/shared/buttonVariants";
import { VTooltip } from "../primitives/VTooltip";

export type VMetricStripMetric = {
  detail?: string;
  id?: string;
  label: string;
  tone?: VuiTone;
  value: ReactNode;
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
    return "text-vui-fg-primary";
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
        "flex min-w-0 flex-wrap items-stretch rounded-[var(--radius-control)] border border-vui-border-hairline bg-vui-surface-toolbar",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {status ? (
        <div className="inline-flex min-w-0 items-center border-r border-vui-border-hairline px-2 py-1">
          {status.title ? (
            <VTooltip content={status.title}>
              <span
                tabIndex={0}
                role="status"
                aria-label={status.ariaLabel}
                className={[
                  "vui-tone-" + (status.tone ?? "neutral"),
                  "inline-flex min-w-0 items-center justify-center truncate rounded-full border border-vui-border-hairline px-2 py-0.5 [font-size:var(--vui-font-xs)] font-semibold leading-none focus-visible:outline-none focus-visible:shadow-[var(--vui-shadow-focus)]",
                ].join(" ")}
              >
                {status.label}
              </span>
            </VTooltip>
          ) : (
            <span
              aria-label={status.ariaLabel}
              className={[
                "vui-tone-" + (status.tone ?? "neutral"),
                "inline-flex min-w-0 items-center justify-center truncate rounded-full border border-vui-border-hairline px-2 py-0.5 [font-size:var(--vui-font-xs)] font-semibold leading-none",
              ].join(" ")}
            >
              {status.label}
            </span>
          )}
        </div>
      ) : null}
      {metrics.map((metric, index) => {
        const key = metric.id ?? `${metric.label}:${index}`;
        const metricCard = (
          <div
            tabIndex={metric.detail ? 0 : undefined}
            role={metric.detail ? "group" : undefined}
            aria-label={metric.detail ? `${metric.label}：${metric.detail}` : undefined}
            className={[
              "inline-flex min-w-0 items-baseline gap-1.5 px-2 py-1 focus-visible:outline-none focus-visible:shadow-[var(--vui-shadow-focus)]",
              index === metrics.length - 1
                ? ""
                : "border-r border-vui-border-hairline",
            ]
              .filter(Boolean)
              .join(" ")}
          >
            <span className="truncate [font-size:var(--vui-font-xs)] font-semibold text-vui-fg-secondary">
              {metric.label}
            </span>
            <strong className={["shrink-0 [font-size:var(--vui-font-md)] leading-none", toneTextClass(metric.tone)].join(" ")}>
              {metric.value}
            </strong>
          </div>
        );
        return metric.detail ? (
          <VTooltip key={key} content={metric.detail}>{metricCard}</VTooltip>
        ) : (
          <div key={key} className="contents">{metricCard}</div>
        );
      })}
    </section>
  );
}
