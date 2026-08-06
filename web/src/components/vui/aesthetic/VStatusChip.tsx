import { type ComponentPropsWithoutRef, type ReactNode } from "react";

export type VStatusTone = "neutral" | "accent" | "success" | "warning" | "danger";

export type VStatusChipProps = Omit<ComponentPropsWithoutRef<"span">, "children"> & {
  children: ReactNode;
  tone?: VStatusTone;
};

const TONE_CLASS: Record<VStatusTone, string> = {
  neutral: "text-vui-fg-tertiary [--status-dot:var(--fg-tertiary)]",
  accent: "text-vui-fg-primary [--status-dot:var(--fg-primary)]",
  success: "text-vui-fg-secondary [--status-dot:var(--fg-tertiary)]",
  warning: "text-[var(--state-warning)] [--status-dot:var(--state-warning)]",
  danger: "text-[var(--state-error)] [--status-dot:var(--state-error)]",
};

/** Quiet non-interactive status: semantic dot + text, never button chrome. */
export function VStatusChip({
  className,
  children,
  tone = "neutral",
  ...props
}: VStatusChipProps) {
  return (
    <span
      {...props}
      data-vui="status-chip"
      data-tone={tone}
      className={[
        "inline-flex min-h-5 w-fit max-w-full items-center gap-1.5",
        "[font-size:var(--vui-font-xs)] font-[650] leading-none",
        TONE_CLASS[tone],
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <span
        aria-hidden="true"
        data-slot="status-chip-dot"
        className="size-1.5 shrink-0 rounded-full bg-[var(--status-dot)] opacity-75"
      />
      <span className="min-w-0 truncate">{children}</span>
    </span>
  );
}
