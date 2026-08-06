import {
  type ComponentPropsWithoutRef,
  type CSSProperties,
  type ReactNode,
} from "react";

export type VErrorSummaryTone = "error" | "warning" | "info";

export type VErrorSummaryProps = Omit<ComponentPropsWithoutRef<"div">, "title"> & {
  /** One-line high-value message (always visible). */
  summary: ReactNode;
  /** Optional leading symbol; use this instead of passing an icon through label. */
  icon?: ReactNode;
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
  "grid min-w-0 w-full content-start gap-1 rounded-[10px] border border-l-[3px] px-3 py-2.5 " +
  "border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] " +
  "text-left shadow-[var(--vui-elevation-1)] [font-size:var(--vui-font-xs)] leading-[var(--vui-line-readable)]";

const TONE_ACCENT: Record<VErrorSummaryTone, string> = {
  error: "var(--state-error)",
  warning: "var(--state-warning)",
  info: "var(--fg-secondary)",
};

const LABEL =
  "min-w-0 truncate [font-size:var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-tertiary)]";
const HEADER_WITH_ICON =
  "grid min-w-0 grid-cols-[auto_minmax(0,1fr)] items-start gap-2.5";
const HEADER_WITHOUT_ICON = "grid min-w-0";
const ICON =
  "grid size-4 shrink-0 place-items-center text-[var(--summary-accent)] [&_svg]:size-4";
const COPY = "grid min-w-0 gap-0.5";
const SUMMARY =
  "min-w-0 [font-size:var(--vui-font-sm)] font-[650] leading-snug tracking-[-0.006em] text-[var(--fg-primary)] " +
  "[overflow-wrap:anywhere] [word-break:break-word]";
const DETAILS =
  "min-w-0 mt-1 border-t border-[var(--vui-border-subtle)] pt-2 " +
  "[font-size:var(--vui-font-xs)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] " +
  "[overflow-wrap:anywhere] [word-break:break-word] whitespace-pre-wrap";
const TOGGLE =
  "inline-flex min-h-6 w-fit items-center rounded-[6px] px-1.5 [font-size:var(--vui-font-xs)] font-[650] text-[var(--fg-tertiary)] " +
  "hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--fg-primary)] " +
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
  icon,
  label,
  openLabel = "Details",
  summary,
  style,
  tone = "error",
  ...props
}: VErrorSummaryProps) {
  const hasDetails = details !== undefined && details !== null && details !== "";
  const resolvedStyle = {
    "--summary-accent": TONE_ACCENT[tone],
    borderLeftColor: "var(--summary-accent)",
    ...style,
  } as CSSProperties;

  if (!hasDetails) {
    return (
      <div
        {...props}
        data-vui="error-summary"
        data-tone={tone}
        data-expanded="false"
        role={tone === "error" ? "alert" : "status"}
        className={[ROOT, className].filter(Boolean).join(" ")}
        style={resolvedStyle}
      >
        <div className={icon ? HEADER_WITH_ICON : HEADER_WITHOUT_ICON} data-slot="error-summary-header">
          {icon ? <span className={ICON} data-slot="error-summary-icon">{icon}</span> : null}
          <div className={COPY}>
            {label ? <span className={LABEL}>{label}</span> : null}
            <div className={SUMMARY}>{summary}</div>
          </div>
        </div>
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
      className={[ROOT, className].filter(Boolean).join(" ")}
      style={resolvedStyle}
    >
      <details className="group/error-summary min-w-0" open={defaultOpen || undefined}>
        <summary
          className={[
            "grid min-w-0 cursor-pointer list-none items-start gap-2.5 marker:content-none [&::-webkit-details-marker]:hidden",
            icon
              ? "grid-cols-[auto_minmax(0,1fr)_auto]"
              : "grid-cols-[minmax(0,1fr)_auto]",
          ].join(" ")}
        >
          {icon ? <span className={ICON} data-slot="error-summary-icon">{icon}</span> : null}
          <div className={COPY}>
            {label ? <span className={LABEL}>{label}</span> : null}
            <div className={SUMMARY}>{summary}</div>
          </div>
          <span className={TOGGLE} data-slot="error-summary-toggle">
            <span className="group-open/error-summary:hidden">{openLabel}</span>
            <span className="hidden group-open/error-summary:inline">{closeLabel}</span>
          </span>
        </summary>
        <div className={[DETAILS, icon ? "ml-[26px]" : undefined].filter(Boolean).join(" ")} data-slot="error-summary-details">
          {details}
        </div>
      </details>
      {actions ? <div className={ACTIONS}>{actions}</div> : null}
    </div>
  );
}
