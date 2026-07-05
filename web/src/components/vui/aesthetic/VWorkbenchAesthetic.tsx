import { type ComponentPropsWithoutRef, type ReactNode } from "react";

import { VSurface } from "../primitives/VSurface";

export type VStatusTone = "neutral" | "accent" | "success" | "warning" | "danger";

type DivProps = ComponentPropsWithoutRef<"div">;

type VEmbeddedPanelProps = ComponentPropsWithoutRef<"section"> & {
  ariaLabel?: string;
  children: ReactNode;
};

type VDenseToolbarProps = DivProps & {
  ariaLabel: string;
};

type VDenseRowProps = DivProps & {
  children: ReactNode;
};

type VStateRowProps = VDenseRowProps & {
  tone?: VStatusTone;
};

type VMetricChipProps = DivProps & {
  label: ReactNode;
  value: ReactNode;
};

type VStatusChipProps = DivProps & {
  children: ReactNode;
  tone?: VStatusTone;
};

const stateToneClass: Record<VStatusTone, string> = {
  accent:
    "border-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-surface-row))] text-[var(--accent-cool)]",
  danger:
    "border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_9%,transparent)] text-[var(--state-error)]",
  neutral: "border-vui-border-subtle bg-vui-surface-row/70 text-vui-fg-secondary",
  success:
    "border-[color-mix(in_srgb,var(--state-success)_32%,transparent)] bg-[color-mix(in_srgb,var(--state-success)_9%,transparent)] text-[var(--state-success)]",
  warning:
    "border-[color-mix(in_srgb,var(--state-warning)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-warning)_10%,transparent)] text-[var(--state-warning)]",
};

export function VEmbeddedPanel({ ariaLabel, className, children, ...props }: VEmbeddedPanelProps) {
  return (
    <VSurface
      {...props}
      as="section"
      data-vui="embedded-panel"
      ariaLabel={ariaLabel}
      padding="compact"
      tone="row"
      className={[
        "bg-vui-surface-row/70 shadow-none backdrop-blur-0",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {children}
    </VSurface>
  );
}

export function VDenseToolbar({ ariaLabel, className, ...props }: VDenseToolbarProps) {
  return (
    <div
      {...props}
      data-vui="dense-toolbar"
      role="toolbar"
      aria-label={ariaLabel}
      className={[
        "flex min-w-0 flex-wrap items-center gap-1.5 rounded-[var(--radius-control)] border border-vui-border-subtle bg-vui-surface-toolbar px-2 py-1.5",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    />
  );
}

export function VDenseRow({ className, children, ...props }: VDenseRowProps) {
  return (
    <div
      {...props}
      data-vui="dense-row"
      className={[
        "min-w-0 rounded-[var(--radius-control)] border border-vui-border-subtle bg-vui-surface-row px-2 py-1.5 text-[var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-vui-fg-secondary",
        "focus-within:ring-2 focus-within:ring-[color-mix(in_srgb,var(--accent-cool)_38%,transparent)]",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {children}
    </div>
  );
}

export function VStateRow({ className, children, tone = "neutral", ...props }: VStateRowProps) {
  return (
    <VDenseRow
      {...props}
      data-tone={tone}
      className={[stateToneClass[tone], className].filter(Boolean).join(" ")}
    >
      {children}
    </VDenseRow>
  );
}

export function VMetricChip({ className, label, value, ...props }: VMetricChipProps) {
  return (
    <span
      {...props}
      data-vui="metric-chip"
      className={[
        "inline-flex min-h-6 w-fit max-w-full items-center gap-1.5 rounded-full border border-vui-border-subtle bg-vui-control-muted px-2 text-[var(--vui-font-xs)] font-semibold leading-none text-vui-fg-secondary",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <span className="text-vui-fg-tertiary">{label}</span>
      <strong className="font-semibold text-vui-fg-primary">{value}</strong>
    </span>
  );
}

export function VStatusChip({ className, children, tone = "neutral", ...props }: VStatusChipProps) {
  return (
    <span
      {...props}
      data-vui="status-chip"
      data-tone={tone}
      className={[
        "inline-flex min-h-6 w-fit max-w-full items-center rounded-full border px-2 text-[var(--vui-font-xs)] font-semibold leading-none",
        stateToneClass[tone],
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {children}
    </span>
  );
}
