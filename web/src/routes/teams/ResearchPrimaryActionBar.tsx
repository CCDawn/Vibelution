import { ArrowRight, Compass } from "lucide-react";

import { VButton, VSurface } from "../../components/vui";
import {
  researchPrimaryActionDetail,
  researchPrimaryActionLabel,
  type ResearchPrimaryAction,
  type ResearchStageHandoff,
} from "./researchPrimaryActionModel";

export type ResearchPrimaryMetric = {
  key: string;
  label: string;
  /** Settled string, or null while that metric is still loading in place. */
  value: string | null;
  loading?: boolean;
};

export type ResearchPrimaryActionBarProps = {
  lang: "zh" | "en";
  action: ResearchPrimaryAction;
  handoff: ResearchStageHandoff | null;
  /** Mutation in flight (button shows Working…). */
  pending?: boolean;
  /**
   * Cold-load / query pending: keep the same card geometry and fill
   * title/body/metrics/CTA with stable skeleton slots (no layout swap).
   */
  loading?: boolean;
  projectName?: string;
  metrics?: ResearchPrimaryMetric[];
  onPrimaryAction: (action: ResearchPrimaryAction) => void;
  /** @deprecated use metrics */
  facts?: Array<{ key: string; label: string; value: string }>;
};

const pulseClass =
  "block animate-pulse rounded-full bg-[color-mix(in_srgb,var(--vui-border-subtle)_70%,transparent)] motion-reduce:animate-none";

function MetricValue({
  value,
  loading,
  lang,
}: {
  value: string | null;
  loading?: boolean;
  lang: "zh" | "en";
}) {
  if (loading || value == null) {
    return (
      <span
        className={`${pulseClass} h-3 w-10`}
        role="status"
        aria-label={lang === "zh" ? "指标加载中" : "Metric loading"}
      />
    );
  }
  return <>{value}</>;
}

function ctaLabel(action: ResearchPrimaryAction, lang: "zh" | "en", pending: boolean): string {
  if (pending) {
    return lang === "zh" ? "处理中…" : "Working…";
  }
  switch (action.kind) {
    case "start_knowledge_collection":
      return lang === "zh" ? "开始搜集" : "Start collection";
    case "continue_knowledge_collection":
      return lang === "zh" ? "进入知识搜集" : "Open collection";
    case "start_experiment":
      return lang === "zh" ? "进入实验设计" : "Open experiment";
    case "continue_experiment":
      return lang === "zh" ? "继续实验设计" : "Continue experiment";
    case "start_iteration":
    case "continue_iteration":
      return lang === "zh" ? "进入执行迭代" : "Open iteration";
    default:
      return researchPrimaryActionLabel(action, lang);
  }
}

/**
 * Linear / GitHub style next-step card:
 * - Single solid CTA (no sibling "ghost text" that looks like a broken control)
 * - Metrics as quiet chips (value slots fill independently when ready)
 * - Helper copy stays in the body, never beside the CTA
 * - Optional stage-handoff banner when upstream is ready to advance
 * - `loading` keeps the same shell geometry; only inner text slots are skeleton
 */
export function ResearchPrimaryActionBar({
  lang,
  action,
  handoff,
  pending = false,
  loading = false,
  projectName = "",
  metrics,
  facts = [],
  onPrimaryAction,
}: ResearchPrimaryActionBarProps) {
  const chips: ResearchPrimaryMetric[] = metrics?.length
    ? metrics
    : facts.map((item) => ({ ...item, loading: false }));
  const effectiveAction = handoff?.action ?? action;
  const projectLine = projectName
    ? projectName
    : (lang === "zh" ? "当前科研项目" : "Active project");
  const buttonLabel = ctaLabel(effectiveAction, lang, pending);
  const disabled = loading || effectiveAction.blocked || pending;
  const title = handoff
    ? (lang === "zh" ? handoff.titleZh : handoff.titleEn)
    : researchPrimaryActionLabel(effectiveAction, lang);
  const body = handoff
    ? (lang === "zh" ? handoff.bodyZh : handoff.bodyEn)
    : researchPrimaryActionDetail(effectiveAction, lang);

  return (
    <section
      className="min-w-0"
      data-testid="research-primary-action-bar"
      data-vui="research-primary-action"
      data-loading={loading ? "true" : "false"}
      data-handoff={!loading && handoff ? "true" : "false"}
      data-blocked={!loading && effectiveAction.blocked ? "true" : "false"}
      aria-busy={loading || undefined}
      aria-label={lang === "zh" ? "建议下一步" : "Suggested next step"}
    >
      <VSurface
        tone="panel"
        elevation="panel"
        padding="none"
        className={[
          "min-w-0 overflow-hidden",
          // Preview contract: monochrome ink accent (not teal).
          "border border-[var(--vui-border-strong,var(--vui-border-subtle))]",
          "bg-[var(--vui-surface-panel)]",
          "shadow-[inset_3px_0_0_0_var(--fg-primary)]",
          !loading && effectiveAction.blocked
            ? "border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] shadow-[inset_3px_0_0_0_var(--fg-tertiary)]"
            : "",
        ].filter(Boolean).join(" ")}
      >
        <div className="grid min-w-0 gap-3 p-4">
          <div className="flex min-w-0 items-center gap-2 text-[var(--vui-font-xs)] text-[var(--fg-tertiary)]">
            <span className="inline-flex items-center gap-1.5 rounded-full bg-[var(--fg-primary)] px-2 py-0.5 font-semibold text-[var(--vui-surface-base)]">
              <Compass size={12} className="shrink-0" aria-hidden="true" />
              {lang === "zh" ? "下一步" : "Next"}
            </span>
            <span className="text-[var(--fg-tertiary)]" aria-hidden="true">·</span>
            {loading && !projectName ? (
              <span className={`${pulseClass} h-3 w-28`} aria-hidden="true" />
            ) : (
              <span className="min-w-0 truncate">{projectLine}</span>
            )}
          </div>

          <div className="grid min-w-0 gap-1.5">
            {loading ? (
              <>
                <span className={`${pulseClass} h-5 w-[min(100%,22rem)]`} aria-hidden="true" />
                <span className={`${pulseClass} h-3.5 w-[min(100%,36rem)]`} aria-hidden="true" />
                <span className={`${pulseClass} h-3.5 w-[min(100%,28rem)] opacity-80`} aria-hidden="true" />
              </>
            ) : (
              <>
                <h3 className="m-0 text-[1.125rem] font-[820] leading-snug tracking-tight text-[var(--fg-primary)]">
                  {title}
                </h3>
                <p className="m-0 max-w-[40rem] text-[var(--vui-font-sm)] leading-relaxed text-[var(--fg-secondary)]">
                  {body}
                </p>
              </>
            )}
          </div>

          {!loading && handoff ? (
            <div
              className="flex min-w-0 flex-wrap items-center gap-2 rounded-lg border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] px-3 py-2 text-[12.5px] text-[var(--fg-primary)]"
              role="status"
              data-testid="research-stage-handoff-banner"
            >
              <strong className="font-[740] text-[var(--fg-primary)]">
                {lang === "zh" ? "阶段交接" : "Stage handoff"}
              </strong>
              <span className="text-[var(--fg-tertiary)]" aria-hidden="true">·</span>
              <span>
                {lang === "zh" ? handoff.titleZh : handoff.titleEn}
              </span>
            </div>
          ) : null}

          {loading ? (
            <dl className="m-0 flex min-w-0 flex-wrap gap-2" aria-hidden="true">
              {["stage", "sources", "candidates"].map((key) => (
                <div
                  key={key}
                  className="inline-flex items-center gap-1.5 rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] px-2.5 py-1"
                >
                  <span className={`${pulseClass} h-2.5 w-8`} />
                  <span className={`${pulseClass} h-3 w-10`} />
                </div>
              ))}
            </dl>
          ) : chips.length ? (
            <dl className="m-0 flex min-w-0 flex-wrap gap-2">
              {chips.map((chip) => (
                <div
                  key={chip.key}
                  className="inline-flex items-center gap-1.5 rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] px-2.5 py-1"
                >
                  <dt className="m-0 text-[11px] font-semibold text-[var(--fg-tertiary)]">{chip.label}</dt>
                  <dd className="m-0 text-[12px] font-semibold text-[var(--fg-primary)]">
                    <MetricValue value={chip.value} loading={chip.loading} lang={lang} />
                  </dd>
                </div>
              ))}
            </dl>
          ) : null}

          <div className="pt-1">
            {loading ? (
              <span
                className={`${pulseClass} inline-block h-9 w-28 rounded-[var(--radius-control)]`}
                role="status"
                aria-label={lang === "zh" ? "主操作加载中" : "Primary action loading"}
                data-testid="research-primary-cta-skeleton"
              />
            ) : (
              <VButton
                type="button"
                data-vui="research-primary-cta"
                data-testid="research-primary-cta"
                variant={effectiveAction.blocked ? "secondary" : "primary"}
                isDisabled={disabled}
                aria-label={buttonLabel}
                // Prefer trailingIcon + plain label text: default contentLayout="label"
                // wraps all children in a truncated label slot, which breaks multi-child
                // (text + ArrowRight) and can look like a split/cut-off control.
                // Avoid title= here — it forces VTooltip wrap when aria-label already exists.
                trailingIcon={
                  !pending && !effectiveAction.blocked
                    ? <ArrowRight size={14} aria-hidden="true" strokeWidth={2.25} />
                    : undefined
                }
                onPress={() => {
                  if (disabled) return;
                  onPrimaryAction(effectiveAction);
                }}
              >
                {buttonLabel}
              </VButton>
            )}
          </div>
        </div>
      </VSurface>
    </section>
  );
}
