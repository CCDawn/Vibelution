import { ArrowRight, Compass } from "lucide-react";

import { VButton, VSurface } from "../../components/vui";
import {
  researchPrimaryActionDetail,
  researchPrimaryActionLabel,
  type ResearchPrimaryAction,
  type ResearchStageHandoff,
} from "./researchPrimaryActionModel";

export type ResearchPrimaryActionBarProps = {
  lang: "zh" | "en";
  action: ResearchPrimaryAction;
  handoff: ResearchStageHandoff | null;
  pending?: boolean;
  projectName?: string;
  metrics?: Array<{ key: string; label: string; value: string }>;
  onPrimaryAction: (action: ResearchPrimaryAction) => void;
  /** @deprecated use metrics */
  facts?: Array<{ key: string; label: string; value: string }>;
};

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
 * - One solid primary button only (no sibling "ghost text" that looks like a broken control)
 * - Metrics as quiet chips
 * - Helper copy stays in the body, never beside the CTA
 * - Optional stage-handoff banner when upstream is ready to advance
 */
export function ResearchPrimaryActionBar({
  lang,
  action,
  handoff,
  pending = false,
  projectName = "",
  metrics,
  facts = [],
  onPrimaryAction,
}: ResearchPrimaryActionBarProps) {
  const chips = metrics?.length ? metrics : facts;
  const effectiveAction = handoff?.action ?? action;
  const projectLine = projectName
    ? projectName
    : (lang === "zh" ? "当前科研项目" : "Active project");
  const buttonLabel = ctaLabel(effectiveAction, lang, pending);
  const disabled = effectiveAction.blocked || pending;
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
      data-handoff={handoff ? "true" : "false"}
      data-blocked={effectiveAction.blocked ? "true" : "false"}
      aria-label={lang === "zh" ? "建议下一步" : "Suggested next step"}
    >
      <VSurface
        tone="panel"
        elevation="panel"
        padding="none"
        className={[
          "min-w-0 overflow-hidden",
          "border border-[color-mix(in_srgb,var(--accent-cool)_28%,var(--vui-border-subtle))]",
          "bg-[linear-gradient(165deg,color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-surface-panel))_0%,var(--vui-surface-panel)_48%)]",
          "shadow-[inset_3px_0_0_0_var(--accent-cool)]",
          effectiveAction.blocked
            ? "border-[color-mix(in_srgb,var(--state-warning)_30%,var(--vui-border-subtle))] shadow-[inset_3px_0_0_0_var(--state-warning)]"
            : "",
        ].filter(Boolean).join(" ")}
      >
        <div className="grid min-w-0 gap-3 p-4">
          <div className="flex min-w-0 items-center gap-2 text-[var(--vui-font-xs)] text-[var(--fg-tertiary)]">
            <Compass size={14} className="shrink-0 text-[var(--accent-cool)]" aria-hidden="true" />
            <span className="font-semibold text-[var(--accent-cool)]">
              {lang === "zh" ? "下一步" : "Next"}
            </span>
            <span className="text-[var(--fg-tertiary)]" aria-hidden="true">·</span>
            <span className="min-w-0 truncate">{projectLine}</span>
          </div>

          <div className="grid min-w-0 gap-1.5">
            <h3 className="m-0 text-[1.125rem] font-[820] leading-snug tracking-tight text-[var(--fg-primary)]">
              {title}
            </h3>
            <p className="m-0 max-w-[40rem] text-[var(--vui-font-sm)] leading-relaxed text-[var(--fg-secondary)]">
              {body}
            </p>
          </div>

          {handoff ? (
            <div
              className="flex min-w-0 flex-wrap items-center gap-2 rounded-lg border border-[color-mix(in_srgb,var(--accent-cool)_22%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--accent-cool)_10%,transparent)] px-3 py-2 text-[12.5px] text-[var(--fg-primary)]"
              role="status"
              data-testid="research-stage-handoff-banner"
            >
              <strong className="font-[740] text-[var(--accent-cool)]">
                {lang === "zh" ? "阶段交接" : "Stage handoff"}
              </strong>
              <span className="text-[var(--fg-tertiary)]" aria-hidden="true">·</span>
              <span>
                {lang === "zh" ? handoff.titleZh : handoff.titleEn}
              </span>
            </div>
          ) : null}

          {chips.length ? (
            <dl className="m-0 flex min-w-0 flex-wrap gap-2">
              {chips.map((chip) => (
                <div
                  key={chip.key}
                  className="inline-flex items-center gap-1.5 rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] px-2.5 py-1"
                >
                  <dt className="m-0 text-[11px] font-semibold text-[var(--fg-tertiary)]">{chip.label}</dt>
                  <dd className="m-0 text-[12px] font-semibold text-[var(--fg-primary)]">{chip.value}</dd>
                </div>
              ))}
            </dl>
          ) : null}

          <div className="pt-1">
            {/* Single solid CTA — no sibling ghost "open stage" control */}
            <VButton
              type="button"
              data-vui="research-primary-cta"
              data-testid="research-primary-cta"
              variant={effectiveAction.blocked ? "secondary" : "primary"}
              isDisabled={disabled}
              aria-label={buttonLabel}
              title={buttonLabel}
              onPress={() => {
                if (disabled) return;
                onPrimaryAction(effectiveAction);
              }}
            >
              <span>{buttonLabel}</span>
              {!pending && !effectiveAction.blocked ? (
                <ArrowRight size={14} aria-hidden="true" strokeWidth={2.25} />
              ) : null}
            </VButton>
          </div>
        </div>
      </VSurface>
    </section>
  );
}
