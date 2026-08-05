/**
 * Production research overview strip — end-user IA (flow only):
 * Stage rail + continue/advance primary. Main body is the organization canvas
 * (shell canvas mode), not a second kanban wall.
 *
 * Loading contract (progressive-fill): fixed CTA geometry; metrics skeleton
 * in place — never swap the whole strip for a fill surface mid-load.
 */
import type { ReactNode } from "react";

import {
  ResearchPrimaryActionBar,
  type ResearchPrimaryActionBarProps,
} from "./ResearchPrimaryActionBar";

export type ResearchOverviewSurfaceProps = {
  lang: "zh" | "en";
  primary: Omit<ResearchPrimaryActionBarProps, "lang">;
  /** Persistent stage switcher */
  stageNav?: ReactNode;
  /** Live-region notice after cross-stage advance */
  notice?: string;
  /** Productized workflow error / cascade reset */
  errorSlot?: ReactNode;
  /**
   * @deprecated Stage board is no longer part of end-user overview.
   * Main content lives on the organization canvas.
   */
  stages?: ReactNode;
  /**
   * @deprecated Advanced details stay out of end-user overview.
   */
  advanced?: ReactNode;
  /** Compact strip over canvas (no extra section chrome). */
  density?: "flow" | "page";
  /** Canvas tools merged into the flow strip (auto-layout, etc.). */
  trailingActions?: ReactNode;
  /**
   * Placed inside the next-step card on the right (4 stage cards).
   * Not a second row under the hero.
   */
  sideSlot?: ReactNode;
  className?: string;
};

export function ResearchOverviewSurface({
  lang,
  primary,
  stageNav,
  notice,
  errorSlot,
  density = "flow",
  trailingActions = null,
  sideSlot = null,
  className = "",
}: ResearchOverviewSurfaceProps) {
  const headerSlot =
    stageNav || trailingActions ? (
      <div className="flex min-w-0 w-full flex-wrap items-center justify-between gap-2">
        {stageNav ? (
          <div data-testid="research-overview-stage-nav" className="min-w-0">
            {stageNav}
          </div>
        ) : (
          <span />
        )}
        {trailingActions ? (
          <div
            className="flex min-w-0 shrink-0 flex-wrap items-center justify-end gap-1.5"
            data-testid="research-overview-trailing-actions"
          >
            {trailingActions}
          </div>
        ) : null}
      </div>
    ) : null;

  return (
    <div
      className={[
        "grid min-w-0 content-start",
        density === "flow" ? "gap-2" : "gap-3",
        className,
      ].filter(Boolean).join(" ")}
      data-testid="research-overview-surface"
      data-vui="research-overview-surface"
      data-overview-density="flow-only"
    >
      <section
        className="grid min-w-0 gap-2"
        data-testid="research-overview-flow"
        aria-label={lang === "zh" ? "流程控制" : "Flow control"}
      >
        <div data-testid="research-overview-hero" className="grid min-w-0 gap-2">
          <ResearchPrimaryActionBar
            lang={lang}
            {...primary}
            headerSlot={headerSlot}
            sideSlot={sideSlot}
          />
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
      </section>
    </div>
  );
}
