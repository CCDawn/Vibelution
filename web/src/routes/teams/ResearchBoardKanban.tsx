import { Eye } from "lucide-react";

import { VNativeButton, VSurface } from "../../components/vui";
import type { ResearchBoardColumn } from "./researchBoardModel";

export type ResearchBoardKanbanProps = {
  lang: "zh" | "en";
  columns: ResearchBoardColumn[];
  onOpenCard?: (columnId: string, cardId: string) => void;
  /** When embedded under ResearchOverviewSurface, the parent already owns the section label. */
  showSectionLabel?: boolean;
  /**
   * Progressive cold-load: keep the fixed three-column geometry and fill card
   * slots with skeleton blocks until data settles. Column titles stay stable.
   */
  loading?: boolean;
  className?: string;
};

const pulseClass =
  "block animate-pulse rounded-md bg-[color-mix(in_srgb,var(--vui-border-subtle)_70%,transparent)] motion-reduce:animate-none";

const SKELETON_COLUMNS: Array<{ id: ResearchBoardColumn["id"]; titleZh: string; titleEn: string }> = [
  { id: "knowledge_collection", titleZh: "知识搜集", titleEn: "Knowledge" },
  { id: "experiment", titleZh: "实验设计", titleEn: "Experiment" },
  { id: "iteration", titleZh: "执行与迭代", titleEn: "Iteration" },
];

function SkeletonCard() {
  return (
    <div
      className="grid min-w-0 gap-2 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-2.5"
      aria-hidden="true"
    >
      <span className={`${pulseClass} h-3.5 w-[72%]`} />
      <span className={`${pulseClass} h-2.5 w-full`} />
      <span className={`${pulseClass} h-2.5 w-[88%] opacity-80`} />
      <div className="flex items-center justify-between gap-2 pt-1">
        <span className={`${pulseClass} h-2.5 w-14`} />
        <span className={`${pulseClass} h-2.5 w-10`} />
      </div>
    </div>
  );
}

/**
 * End-user three-column research board (read-only cards + 查看).
 * Column count/geometry is fixed; only card interiors progressive-fill.
 * Long machine titles/bodies are clamped so overview stays scannable.
 */
export function ResearchBoardKanban({
  lang,
  columns,
  onOpenCard,
  showSectionLabel = false,
  loading = false,
  className = "",
}: ResearchBoardKanbanProps) {
  const renderedColumns = loading
    ? SKELETON_COLUMNS.map((column) => ({
        id: column.id,
        titleZh: column.titleZh,
        titleEn: column.titleEn,
        cards: [] as ResearchBoardColumn["cards"],
      }))
    : columns;

  return (
    <section
      className={["researchBoardKanban grid min-w-0 gap-2", className].filter(Boolean).join(" ")}
      data-testid="research-board-kanban"
      data-vui="research-board-kanban"
      data-loading={loading ? "true" : "false"}
      aria-busy={loading || undefined}
      aria-label={lang === "zh" ? "阶段看板" : "Stage board"}
    >
      {showSectionLabel ? (
        <div className="flex min-w-0 items-baseline justify-between gap-3 px-0.5">
          <h3 className="m-0 [font-size:var(--vui-font-xs)] font-[740] text-[var(--fg-primary)]">
            {lang === "zh" ? "阶段看板" : "Stage board"}
          </h3>
        </div>
      ) : null}
      {/* Prefer project-stable 3-col recipe; scroll horizontally on narrow widths. */}
      <div
        className="!grid min-w-0 !grid-cols-[repeat(3,minmax(0,1fr))] items-start gap-2.5 overflow-x-auto pb-1 [scrollbar-gutter:stable] max-[900px]:min-w-[720px]"
        data-testid="research-board-columns"
      >
        {renderedColumns.map((column) => (
          <VSurface
            key={column.id}
            tone="inset"
            elevation="flat"
            padding="compact"
            className="grid min-h-[280px] min-w-0 content-start gap-2"
            data-testid={`research-board-column-${column.id}`}
          >
            <div className="flex min-w-0 items-center justify-between gap-2">
              <h4 className="m-0 truncate [font-size:var(--vui-font-xs)] font-[760] text-[var(--fg-primary)]">
                {lang === "zh" ? column.titleZh : column.titleEn}
              </h4>
              {loading ? (
                <span className={`${pulseClass} size-[22px] shrink-0 rounded-full`} aria-hidden="true" />
              ) : (
                <span className="inline-grid h-[22px] min-w-[22px] place-items-center rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-1.5 [font-size:var(--vui-font-2xs)] font-[740] text-[var(--fg-secondary)]">
                  {column.cards.length}
                </span>
              )}
            </div>
            {loading ? (
              <div className="grid gap-2" data-testid={`research-board-column-skeleton-${column.id}`}>
                <SkeletonCard />
                <SkeletonCard />
              </div>
            ) : column.cards.length ? column.cards.map((card) => (
              <VSurface
                key={card.id}
                tone="panel"
                elevation="flat"
                padding="compact"
                className={[
                  "grid min-w-0 gap-1.5 border border-[var(--vui-border-subtle)]",
                  card.active ? "border-[var(--fg-primary)] shadow-[inset_0_0_0_1px_var(--fg-primary)]" : "",
                ].filter(Boolean).join(" ")}
                data-active={card.active ? "true" : "false"}
              >
                <strong
                  className="min-w-0 truncate [font-size:var(--vui-font-xs)] font-[740] leading-snug text-[var(--fg-primary)]"
                  title={card.title}
                >
                  {card.title}
                </strong>
                <p
                  className="m-0 line-clamp-2 min-w-0 [font-size:var(--vui-font-2xs)] leading-snug text-[var(--fg-secondary)]"
                  title={card.body}
                >
                  {card.body}
                </p>
                {card.meta.length ? (
                  <div className="flex min-w-0 flex-wrap gap-1">
                    {card.meta.slice(0, 3).map((item) => (
                      <span
                        key={item}
                        className="max-w-full truncate rounded-md bg-[var(--vui-control-muted)] px-1.5 py-0.5 text-[10.5px] text-[var(--fg-tertiary)]"
                        title={item}
                      >
                        {item}
                      </span>
                    ))}
                  </div>
                ) : null}
                <div className="flex min-w-0 items-center justify-between gap-2 [font-size:var(--vui-font-2xs)] text-[var(--fg-tertiary)]">
                  <span className="min-w-0 truncate" title={card.foot}>{card.foot}</span>
                  <VNativeButton
                    type="button"
                    className="!min-h-7 shrink-0 !gap-1 !border-transparent !bg-transparent !px-2 ![font-size:var(--vui-font-2xs)] !text-[var(--fg-secondary)]"
                    onClick={() => onOpenCard?.(column.id, card.id)}
                  >
                    <Eye size={13} />
                    {lang === "zh" ? "查看" : "View"}
                  </VNativeButton>
                </div>
              </VSurface>
            )) : (
              <p className="m-0 [font-size:var(--vui-font-2xs)] text-[var(--fg-tertiary)]">
                {lang === "zh" ? "本列暂无卡片" : "No cards in this column"}
              </p>
            )}
          </VSurface>
        ))}
      </div>
    </section>
  );
}
