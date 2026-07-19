import { type ComponentPropsWithoutRef, type ReactNode } from "react";

export type VErrorSummaryTone = "error" | "warning" | "info";

export type VErrorSummaryProps = Omit<ComponentPropsWithoutRef<"div">, "title"> & {
  /** One-line high-value message (always visible). */
  summary: ReactNode;
  /** Optional expanded diagnostics; only rendered when present. */
  details?: ReactNode;
  /** Short status label such as "请求错误" / "Runtime". */
  label?: ReactNode;
  tone?: VErrorSummaryTone;
  defaultOpen?: boolean;
  actions?: ReactNode;
  openLabel?: string;
  closeLabel?: string;
};

const ROOT =
  "grid min-w-0 w-full content-start gap-1 rounded-[var(--radius-control)] border px-2 py-1.5 " +
  "text-left [font-size:var(--vui-font-xs)] leading-[var(--vui-line-readable)]";

const TONE: Record<VErrorSummaryTone, string> = {
  error:
    "border-[color-mix(in_srgb,var(--state-error)_36%,var(--vui-border-subtle))] " +
    "bg-[color-mix(in_srgb,var(--state-error)_8%,var(--vui-surface-row))] text-[var(--state-error)]",
  warning:
    "border-[color-mix(in_srgb,var(--state-warning)_36%,var(--vui-border-subtle))] " +
    "bg-[color-mix(in_srgb,var(--state-warning)_9%,var(--vui-surface-row))] text-[var(--state-warning)]",
  info:
    "border-[color-mix(in_srgb,var(--accent-cool)_28%,var(--vui-border-subtle))] " +
    "bg-[color-mix(in_srgb,var(--accent-cool)_8%,var(--vui-surface-row))] text-[var(--accent-cool)]",
};

const LABEL =
  "min-w-0 truncate [font-size:var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-tertiary)]";
const SUMMARY =
  "min-w-0 [font-size:var(--vui-font-sm)] font-semibold leading-snug text-[var(--fg-primary)] " +
  "[overflow-wrap:anywhere] [word-break:break-word]";
const DETAILS =
  "min-w-0 mt-1 border-t border-[color-mix(in_srgb,currentColor_18%,var(--vui-border-subtle))] " +
  "pt-1.5 [font-size:var(--vui-font-xs)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] " +
  "[overflow-wrap:anywhere] [word-break:break-word] whitespace-pre-wrap";
const TOGGLE =
  "inline-flex min-h-[var(--vui-control-height-sm)] w-fit items-center rounded-[var(--radius-control)] " +
  "border border-transparent px-1.5 [font-size:var(--vui-font-xs)] font-semibold text-[var(--fg-tertiary)] " +
  "hover:border-[var(--vui-border-subtle)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--fg-primary)] " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color-mix(in_srgb,var(--accent-cool)_40%,transparent)]";
const ACTIONS = "flex min-w-0 flex-wrap items-center gap-1.5 pt-0.5";

/**
 * Collapse long error text into a one-line summary plus optional full body.
 * Pure helper so routes can precompute without mounting the component.
 */
export function summarizeErrorText(
  text: string,
  maxLength = 96,
): { summary: string; details: string | null } {
  const normalized = String(text ?? "").replace(/\s+/g, " ").trim();
  if (!normalized) {
    return { summary: "", details: null };
  }
  if (normalized.length <= maxLength) {
    return { summary: normalized, details: null };
  }
  const cut = normalized.slice(0, Math.max(24, maxLength - 1)).trimEnd();
  return {
    summary: `${cut}…`,
    details: normalized,
  };
}

export function VErrorSummary({
  actions,
  className,
  closeLabel = "Hide details",
  defaultOpen = false,
  details,
  label,
  openLabel = "Details",
  summary,
  tone = "error",
  ...props
}: VErrorSummaryProps) {
  const hasDetails = details !== undefined && details !== null && details !== "";

  if (!hasDetails) {
    return (
      <div
        {...props}
        data-vui="error-summary"
        data-tone={tone}
        data-expanded="false"
        role={tone === "error" ? "alert" : "status"}
        className={[ROOT, TONE[tone], className].filter(Boolean).join(" ")}
      >
        {label ? <span className={LABEL}>{label}</span> : null}
        <div className={SUMMARY}>{summary}</div>
        {actions ? <div className={ACTIONS}>{actions}</div> : null}
      </div>
    );
  }

  return (
    <div
      {...props}
      data-vui="error-summary"
      data-tone={tone}
      role={tone === "error" ? "alert" : "status"}
      className={[ROOT, TONE[tone], className].filter(Boolean).join(" ")}
    >
      <details className="group/error-summary min-w-0" open={defaultOpen || undefined}>
        <summary className="grid min-w-0 cursor-pointer list-none gap-1 marker:content-none [&::-webkit-details-marker]:hidden">
          {label ? <span className={LABEL}>{label}</span> : null}
          <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-start gap-2">
            <div className={SUMMARY}>{summary}</div>
            <span className={TOGGLE} data-slot="error-summary-toggle">
              <span className="group-open/error-summary:hidden">{openLabel}</span>
              <span className="hidden group-open/error-summary:inline">{closeLabel}</span>
            </span>
          </div>
        </summary>
        <div className={DETAILS} data-slot="error-summary-details">
          {details}
        </div>
      </details>
      {actions ? <div className={ACTIONS}>{actions}</div> : null}
    </div>
  );
}
