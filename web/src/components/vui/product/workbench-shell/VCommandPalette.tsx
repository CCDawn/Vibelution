import { useEffect, useMemo, useRef, useState } from "react";

import { cn } from "../../lib/cn";
import { VDialog } from "../../primitives/VDialog";
import { VInput } from "../../forms/VInput";

export type VCommandPaletteItem = {
  id: string;
  label: string;
  /** Optional secondary line (e.g. question title under an id). */
  detail?: string;
  /** Group heading; items render grouped in insertion order. */
  group: string;
  /** Simple substring/fuzzy score; higher wins. Empty query keeps order. */
  keywords?: string;
  onRun: () => void;
};

export type VCommandPaletteLabels = {
  searchPlaceholder: string;
  emptyTitle: string;
  hint: string;
};

export type VCommandPaletteProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  items: VCommandPaletteItem[];
  labels: VCommandPaletteLabels;
  /** Max rendered rows per group before the list scrolls. */
  maxVisible?: number;
  className?: string;
  "data-vui"?: string;
};

function scoreItem(item: VCommandPaletteItem, query: string): number {
  if (!query) return 1;
  const haystack = `${item.label} ${item.detail ?? ""} ${item.keywords ?? ""}`.toLowerCase();
  const needle = query.toLowerCase();
  const direct = haystack.indexOf(needle);
  if (direct >= 0) return 1000 - direct;
  // Subsequence fallback: characters in order, not necessarily adjacent.
  let cursor = 0;
  let hits = 0;
  for (const char of needle) {
    const found = haystack.indexOf(char, cursor);
    if (found < 0) return 0;
    cursor = found + 1;
    hits += 1;
  }
  return hits;
}

/**
 * Keyboard-first command palette (Linear/VS Code pattern): one searchable
 * surface for navigation and actions. The component is data-driven; surfaces
 * compose the item list and own the consequences of running an item.
 */
export function VCommandPalette({
  open,
  onOpenChange,
  items,
  labels,
  maxVisible = 9,
  className,
  "data-vui": dataVui = "command-palette",
}: VCommandPaletteProps) {
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const listRef = useRef<HTMLDivElement | null>(null);

  const flat = useMemo(() => {
    if (!query) return items;
    return items
      .map((item) => ({ item, score: scoreItem(item, query) }))
      .filter((entry) => entry.score > 0)
      .sort((left, right) => right.score - left.score)
      .map((entry) => entry.item);
  }, [items, query]);

  useEffect(() => {
    setActiveIndex(0);
  }, [query, open]);

  useEffect(() => {
    if (!open) setQuery("");
  }, [open]);

  useEffect(() => {
    listRef.current
      ?.querySelector<HTMLElement>(`[data-index="${activeIndex}"]`)
      ?.scrollIntoView({ block: "nearest" });
  }, [activeIndex]);

  const runItem = (item: VCommandPaletteItem) => {
    onOpenChange(false);
    item.onRun();
  };

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveIndex((current) => Math.min(current + 1, flat.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((current) => Math.max(current - 1, 0));
    } else if (event.key === "Enter") {
      event.preventDefault();
      const item = flat[activeIndex];
      if (item) runItem(item);
    }
  };

  let renderedInGroup = 0;
  const rows = flat.slice(0, maxVisible * 4);

  return (
    <VDialog
      open={open}
      onOpenChange={onOpenChange}
      title={<span className="sr-only">{labels.searchPlaceholder}</span>}
      description={null}
      size="sm"
      className={cn("w-[min(560px,92vw)]", className)}
      data-vui={dataVui}
    >
      <div className="flex min-h-0 flex-col" onKeyDown={onKeyDown} data-testid="vui-command-palette">
        <VInput
          value={query}
          onChange={(event) => setQuery(event.currentTarget.value)}
          placeholder={labels.searchPlaceholder}
          aria-label={labels.searchPlaceholder}
          autoFocus
        />
        <div ref={listRef} className="mt-2 max-h-[46vh] overflow-y-auto">
          {rows.length === 0 ? (
            <p className="m-0 px-1 py-3 text-center [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)]">
              {labels.emptyTitle}
            </p>
          ) : (
            rows.map((item, index) => {
              const firstOfGroup = index === 0 || rows[index - 1].group !== item.group;
              if (firstOfGroup) renderedInGroup = 0;
              renderedInGroup += 1;
              const active = index === activeIndex;
              return (
                <div key={item.id}>
                  {firstOfGroup ? (
                    <p className="m-0 mt-2 px-1 [font-size:var(--vui-font-2xs)] font-[650] tracking-[0.02em] text-[var(--fg-secondary)]">
                      {item.group}
                    </p>
                  ) : null}
                  <button
                    type="button"
                    data-index={index}
                    data-active={active ? "true" : "false"}
                    className={
                      "mt-[2px] grid w-full gap-[2px] rounded-[var(--vui-radius-control)] border border-transparent px-2 py-[6px] text-left " +
                      "data-[active=true]:border-[var(--vui-border)] data-[active=true]:bg-[var(--vui-surface-inset)]"
                    }
                    onMouseEnter={() => setActiveIndex(index)}
                    onClick={() => runItem(item)}
                  >
                    <span className="[font-size:var(--vui-font-xs)]">{item.label}</span>
                    {item.detail ? (
                      <span className="truncate [font-size:var(--vui-font-2xs)] text-[var(--fg-secondary)]">
                        {item.detail}
                      </span>
                    ) : null}
                  </button>
                </div>
              );
            })
          )}
        </div>
        <p className="m-0 mt-2 border-t border-[var(--vui-border-subtle)] pt-2 [font-size:var(--vui-font-2xs)] text-[var(--fg-secondary)]">
          {labels.hint}
        </p>
      </div>
    </VDialog>
  );
}
