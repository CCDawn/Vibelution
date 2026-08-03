/**
 * Production research overview surface — information architecture matches
 * web/research-overview-preview.html design acceptance contract:
 * 1) Single solid primary CTA first
 * 2) Read-only three-stage progress
 * 3) Advanced details collapsed
 * 4) Productized errors (optional slot)
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
      <div className="flex min-w-0 items-baseline justify-between gap-3 px-0.5">
        <h3 className="m-0 text-[13px] font-[740] text-[var(--fg-primary)]">
          {lang === "zh" ? "项目推进" : "Project progress"}
        </h3>
        <span className="text-[12px] text-[var(--fg-tertiary)]">
          {lang === "zh" ? "看板模式 · 单一主 CTA + 三列阶段" : "Board · single primary CTA + three stages"}
        </span>
      </div>

      <div data-testid="research-overview-hero" className="grid min-w-0 gap-3">
        <ResearchPrimaryActionBar lang={lang} {...primary} />
        {errorSlot ? <div data-testid="research-overview-error">{errorSlot}</div> : null}
      </div>

      <div className="flex min-w-0 items-baseline justify-between gap-3 px-0.5">
        <h3 className="m-0 text-[13px] font-[740] text-[var(--fg-primary)]">
          {lang === "zh" ? "阶段看板" : "Stage board"}
        </h3>
        <span className="text-[12px] text-[var(--fg-tertiary)]">
          {lang === "zh" ? "卡片只读 · 操作请用上方主按钮" : "Read-only cards · use the primary CTA above"}
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
