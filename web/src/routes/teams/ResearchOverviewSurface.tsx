/**
 * Production research overview surface — easy-ops IA:
 * 1) Stage rail (one-click switch)
 * 2) Continue primary + optional advance secondary
 * 3) Read-only three-stage board
 * 4) Advanced details collapsed
 *
 * Loading contract (progressive-fill): this shell mounts immediately on
 * overview. Primary CTA and stage kanban keep fixed geometry; inner slots
 * fill via `loading` on child bars/boards — never swap the whole surface
 * for a fill VStateSurface mid-load.
 */
import type { ReactNode } from "react";

import {
  ResearchPrimaryActionBar,
  type ResearchPrimaryActionBarProps,
} from "./ResearchPrimaryActionBar";
import { ResearchOverviewSecondary } from "./ResearchOverviewSecondary";

export type ResearchOverviewSurfaceProps = {
  lang: "zh" | "en";
  primary: Omit<ResearchPrimaryActionBarProps, "lang">;
  /** Persistent stage switcher */
  stageNav?: ReactNode;
  /** Live-region notice after cross-stage advance */
  notice?: string;
  /** Productized workflow error / cascade reset, rendered above stages when present */
  errorSlot?: ReactNode;
  /** Stage launcher (presentationMode=overview) */
  stages: ReactNode;
  /** Advanced disclosure body */
  advanced?: ReactNode;
  className?: string;
};

export function ResearchOverviewSurface({
  lang,
  primary,
  stageNav,
  notice,
  errorSlot,
  stages,
  advanced,
  className = "",
}: ResearchOverviewSurfaceProps) {
  return (
    <div
      className={["grid min-w-0 gap-4", className].filter(Boolean).join(" ")}
      data-testid="research-overview-surface"
      data-vui="research-overview-surface"
    >
      <div className="flex min-w-0 flex-wrap items-center justify-between gap-3 px-0.5">
        <h3 className="m-0 text-[13px] font-[740] text-[var(--fg-primary)]">
          {lang === "zh" ? "项目推进" : "Project progress"}
        </h3>
        <span className="text-[12px] text-[var(--fg-tertiary)]">
          {lang === "zh" ? "主按钮继续当前 · 次按钮进入下一阶段" : "Primary continues · secondary advances"}
        </span>
      </div>

      {stageNav ? (
        <div data-testid="research-overview-stage-nav" className="min-w-0">
          {stageNav}
        </div>
      ) : null}

      <div data-testid="research-overview-hero" className="grid min-w-0 gap-3">
        <ResearchPrimaryActionBar lang={lang} {...primary} />
        {notice ? (
          <div
            className="rounded-lg border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] px-3 py-2 text-[12.5px] text-[var(--fg-primary)]"
            role="status"
            aria-live="polite"
            data-testid="research-advance-notice"
          >
            {notice}
          </div>
        ) : null}
        {errorSlot ? <div data-testid="research-overview-error">{errorSlot}</div> : null}
      </div>

      <div className="flex min-w-0 items-baseline justify-between gap-3 px-0.5">
        <h3 className="m-0 text-[13px] font-[740] text-[var(--fg-primary)]">
          {lang === "zh" ? "阶段看板" : "Stage board"}
        </h3>
        <span className="text-[12px] text-[var(--fg-tertiary)]">
          {lang === "zh" ? "卡片可打开阶段 · 推进请用上方按钮" : "Cards open stages · advance via CTAs above"}
        </span>
      </div>

      <div data-testid="research-overview-stages" className="min-w-0">
        {stages}
      </div>

      {advanced ? (
        <ResearchOverviewSecondary lang={lang}>{advanced}</ResearchOverviewSecondary>
      ) : null}
    </div>
  );
}
