import { Eye } from "lucide-react";

import { VNativeButton, VSurface } from "../../components/vui";
import type { ResearchBoardColumn } from "./researchBoardModel";

export type ResearchBoardKanbanProps = {
  lang: "zh" | "en";
  columns: ResearchBoardColumn[];
  onOpenCard?: (columnId: string, cardId: string) => void;
  /** When embedded under ResearchOverviewSurface, the parent already owns the section label. */
  showSectionLabel?: boolean;
  className?: string;
};

/**
 * Preview-aligned three-column research board (read-only cards + 查看).
 */
export function ResearchBoardKanban({
  lang,
  columns,
  onOpenCard,
  showSectionLabel = false,
  className = "",
}: ResearchBoardKanbanProps) {
  return (
    <section
      className={["researchBoardKanban grid min-w-0 gap-3", className].filter(Boolean).join(" ")}
      data-testid="research-board-kanban"
      data-vui="research-board-kanban"
      aria-label={lang === "zh" ? "阶段看板" : "Stage board"}
    >
      {showSectionLabel ? (
        <div className="flex min-w-0 items-baseline justify-between gap-3 px-0.5">
          <h3 className="m-0 text-[13px] font-[740] text-[var(--fg-primary)]">
            {lang === "zh" ? "阶段看板" : "Stage board"}
          </h3>
          <span className="text-[12px] text-[var(--fg-tertiary)]">
            {lang === "zh" ? "卡片只读 · 操作请用上方主按钮" : "Read-only cards · use the primary CTA above"}
          </span>
        </div>
      ) : null}
      <div className="grid min-w-0 grid-cols-1 items-start gap-3 md:grid-cols-3">
        {columns.map((column) => (
          <VSurface
            key={column.id}
            tone="inset"
            elevation="flat"
            padding="compact"
            className="grid min-h-[320px] min-w-0 content-start gap-2.5"
            data-testid={`research-board-column-${column.id}`}
          >
            <div className="flex min-w-0 items-center justify-between gap-2">
              <h4 className="m-0 text-[13px] font-[760] text-[var(--fg-primary)]">
                {lang === "zh" ? column.titleZh : column.titleEn}
              </h4>
              <span className="inline-grid h-[22px] min-w-[22px] place-items-center rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-1.5 text-[11px] font-[740] text-[var(--fg-secondary)]">
                {column.cards.length}
              </span>
            </div>
            {column.cards.length ? column.cards.map((card) => (
              <VSurface
                key={card.id}
                tone="panel"
                elevation="flat"
                padding="compact"
                className={[
                  "grid min-w-0 gap-2 border border-[var(--vui-border-subtle)]",
                  card.active ? "border-[var(--fg-primary)] shadow-[inset_0_0_0_1px_var(--fg-primary)]" : "",
                ].filter(Boolean).join(" ")}
                data-active={card.active ? "true" : "false"}
              >
                <strong className="text-[13px] font-[740] text-[var(--fg-primary)]">{card.title}</strong>
                <p className="m-0 text-[12px] leading-snug text-[var(--fg-secondary)]">{card.body}</p>
                {card.meta.length ? (
                  <div className="flex min-w-0 flex-wrap gap-1.5">
                    {card.meta.map((item) => (
                      <span
                        key={item}
                        className="rounded-md bg-[var(--vui-control-muted)] px-1.5 py-0.5 text-[10.5px] text-[var(--fg-tertiary)]"
                      >
                        {item}
                      </span>
                    ))}
                  </div>
                ) : null}
                <div className="flex min-w-0 items-center justify-between gap-2 text-[11px] text-[var(--fg-tertiary)]">
                  <span>{card.foot}</span>
                  <VNativeButton
                    type="button"
                    className="!min-h-7 !gap-1 !border-transparent !bg-transparent !px-2 !text-[12px] !text-[var(--fg-secondary)]"
                    onClick={() => onOpenCard?.(column.id, card.id)}
                  >
                    <Eye size={13} />
                    {lang === "zh" ? "查看" : "View"}
                  </VNativeButton>
                </div>
              </VSurface>
            )) : (
              <p className="m-0 text-[12px] text-[var(--fg-tertiary)]">
                {lang === "zh" ? "本列暂无卡片" : "No cards in this column"}
              </p>
            )}
          </VSurface>
        ))}
      </div>
    </section>
  );
}
