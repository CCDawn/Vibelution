import { useEffect, useRef, useState } from "react";

import { cn } from "../../lib/cn";
import { VInput } from "../../forms/VInput";
import { VDialog } from "../../primitives/VDialog";
import { VNativeButton } from "../../primitives/VNativeButton";
import { VStateSurface } from "../../layout/VStateSurface";

export type VSessionSearchDialogItem = {
  id: string;
  /** Primary line: session title (server q matches this). */
  title: string;
  /** Secondary line: task summary / last-message preview returned with the hit. */
  detail?: string;
  /** Meta line: agent display name, status and recency. */
  meta?: string;
  /** The active query; occurrences in title/detail render highlighted. */
  highlight?: string;
  active?: boolean;
  onOpen: () => void;
};

export type VSessionSearchDialogLabels = {
  searchPlaceholder: string;
  emptyTitle: string;
  emptyHint?: string;
  loadMore: string;
  loadingMore: string;
  resultSummary?: (loaded: number, total: number) => string;
  hint: string;
};

export type VSessionSearchDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Controlled query: the mounting surface debounces and owns the request. */
  query: string;
  onQueryChange: (query: string) => void;
  /** Optional filter controls (agent / team scopes) rendered under the input. */
  filters?: React.ReactNode;
  items: VSessionSearchDialogItem[];
  loading?: boolean;
  hasMore?: boolean;
  loadingMore?: boolean;
  onLoadMore?: () => void;
  /** Total server-side estimate; enables a "loaded N of M" summary line. */
  totalEstimate?: number;
  labels: VSessionSearchDialogLabels;
  className?: string;
  "data-vui"?: string;
};

/**
 * Highlights needle occurrences inside one text run without mangling case.
 * Returns the text unchanged when the needle is empty.
 */
function HighlightedText({ text, needle }: { text: string; needle: string }) {
  const normalized = needle.trim().toLowerCase();
  if (!normalized || !text) {
    return <>{text}</>;
  }
  const parts: React.ReactNode[] = [];
  let cursor = 0;
  let key = 0;
  let index = text.toLowerCase().indexOf(normalized);
  while (index >= 0) {
    if (index > cursor) {
      parts.push(text.slice(cursor, index));
    }
    parts.push(
      <mark
        key={key += 1}
        className="rounded-[2px] bg-[var(--vui-surface-inset)] px-[1px] text-inherit"
      >
        {text.slice(index, index + normalized.length)}
      </mark>,
    );
    cursor = index + normalized.length;
    index = text.toLowerCase().indexOf(normalized, cursor);
  }
  if (cursor < text.length) {
    parts.push(text.slice(cursor));
  }
  return <>{parts}</>;
}

/**
 * Server-paginated session search surface ("all sessions" directory). Unlike
 * VCommandPalette — which filters a fully client-provided item list in memory —
 * this surface renders paged results the mounting surface fetched from the
 * session query API, so paging, loading and totals are explicit props. The
 * component stays data-driven: it never fetches, filters remotely, or owns the
 * consequence of opening a session.
 */
export function VSessionSearchDialog({
  open,
  onOpenChange,
  query,
  onQueryChange,
  filters,
  items,
  loading = false,
  hasMore = false,
  loadingMore = false,
  onLoadMore,
  totalEstimate,
  labels,
  className,
  "data-vui": dataVui = "session-search-dialog",
}: VSessionSearchDialogProps) {
  const [activeIndex, setActiveIndex] = useState(0);
  const listRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setActiveIndex(0);
  }, [query, open, items.length]);

  useEffect(() => {
    listRef.current
      ?.querySelector<HTMLElement>(`[data-index="${activeIndex}"]`)
      ?.scrollIntoView({ block: "nearest" });
  }, [activeIndex]);

  const openItem = (item: VSessionSearchDialogItem) => {
    onOpenChange(false);
    item.onOpen();
  };

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveIndex((current) => Math.min(current + 1, items.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((current) => Math.max(current - 1, 0));
    } else if (event.key === "Enter") {
      event.preventDefault();
      const item = items[activeIndex];
      if (item) openItem(item);
    }
  };

  const summary = labels.resultSummary && typeof totalEstimate === "number"
    ? labels.resultSummary(items.length, totalEstimate)
    : "";

  return (
    <VDialog
      open={open}
      onOpenChange={onOpenChange}
      title={<span className="sr-only">{labels.searchPlaceholder}</span>}
      description={null}
      size="md"
      className={cn("w-[min(640px,92vw)]", className)}
      data-vui={dataVui}
    >
      <div className="flex min-h-0 flex-col" onKeyDown={onKeyDown} data-testid="vui-session-search-dialog">
        <VInput
          type="search"
          value={query}
          onChange={(event) => onQueryChange(event.currentTarget.value)}
          placeholder={labels.searchPlaceholder}
          aria-label={labels.searchPlaceholder}
          autoFocus
        />
        {filters ? <div className="mt-2 flex flex-wrap items-center gap-2">{filters}</div> : null}
        <div ref={listRef} className="mt-2 max-h-[52vh] overflow-y-auto">
          {items.length === 0 ? (
            loading ? (
              <VStateSurface tone="loading" title={labels.loadingMore} />
            ) : (
              <VStateSurface tone="empty" title={labels.emptyTitle}>
                {labels.emptyHint}
              </VStateSurface>
            )
          ) : (
            items.map((item, index) => {
              const active = index === activeIndex;
              return (
                <VNativeButton
                  key={item.id}
                  type="button"
                  data-index={index}
                  data-active={active ? "true" : "false"}
                  aria-pressed={item.active ? "true" : "false"}
                  className={
                    "mt-[2px] grid w-full gap-[2px] rounded-[var(--vui-radius-control)] border border-transparent px-2 py-[6px] text-left " +
                    "data-[active=true]:border-[var(--vui-border)] data-[active=true]:bg-[var(--vui-surface-inset)]"
                  }
                  onMouseEnter={() => setActiveIndex(index)}
                  onClick={() => openItem(item)}
                >
                  <span className="[font-size:var(--vui-font-xs)]">
                    <HighlightedText text={item.title} needle={item.highlight ?? ""} />
                  </span>
                  {item.detail ? (
                    <span className="truncate [font-size:var(--vui-font-2xs)] text-[var(--fg-secondary)]">
                      <HighlightedText text={item.detail} needle={item.highlight ?? ""} />
                    </span>
                  ) : null}
                  {item.meta ? (
                    <span className="truncate [font-size:var(--vui-font-2xs)] text-[var(--fg-secondary)]">
                      {item.meta}
                    </span>
                  ) : null}
                </VNativeButton>
              );
            })
          )}
        </div>
        <div className="mt-2 flex items-center justify-between gap-2 border-t border-[var(--vui-border-subtle)] pt-2">
          <span className="[font-size:var(--vui-font-2xs)] text-[var(--fg-secondary)]">
            {summary || labels.hint}
          </span>
          {hasMore ? (
            <VNativeButton
              type="button"
              className="rounded-[var(--vui-radius-control)] px-2 py-1 [font-size:var(--vui-font-2xs)] hover:bg-[var(--vui-surface-inset)]"
              disabled={loadingMore}
              onClick={() => onLoadMore?.()}
            >
              {loadingMore ? labels.loadingMore : labels.loadMore}
            </VNativeButton>
          ) : (
            <span className="[font-size:var(--vui-font-2xs)] text-[var(--fg-secondary)]">{labels.hint}</span>
          )}
        </div>
      </div>
    </VDialog>
  );
}
