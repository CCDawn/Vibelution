import { Search } from "lucide-react";

import { VButton, VNativeInput, VSection, VSkeleton, VStateSurface, VSurface } from "../components/vui";
import { toReadableMemoryBlocks, type ReadableMemoryBlock } from "./memory/memoryReadableContent";
import styles from "./MemoryContentBrowsePanel.styles";

export type MemoryBrowseCard = {
  id: string;
  title: string;
  meta?: string;
  group?: string;
};

export type MemoryBrowseEntry = {
  id: string;
  title: string;
  body: string;
  group?: string;
};

export type MemoryContentBrowsePanelCopy = {
  loading: string;
  loadFailed: string;
  browseBack: string;
  browseSelectCard: string;
  browseEmptyCards: string;
  browseEmptyEntries: string;
  noContent: string;
  searchPlaceholder: string;
  ungrouped?: string;
};

type MemoryContentBrowsePanelProps = {
  copy: MemoryContentBrowsePanelCopy;
  searchText?: string;
  onSearchTextChange?: (value: string) => void;
  cards: MemoryBrowseCard[];
  selectedCardId: string;
  onSelectCard: (cardId: string) => void;
  onClearCard: () => void;
  entries: MemoryBrowseEntry[];
  selectedEntryId: string;
  onSelectEntry: (entryId: string) => void;
  loading?: boolean;
  errorText?: string;
  entriesLoading?: boolean;
};

function groupItems<T extends { id: string; group?: string }>(
  items: T[],
  ungrouped: string,
): Array<{ key: string; title: string; items: T[] }> {
  const groups: Array<{ key: string; title: string; items: T[] }> = [];
  const indexByKey = new Map<string, number>();
  for (const item of items) {
    const title = item.group?.trim() || ungrouped;
    const key = title;
    const existing = indexByKey.get(key);
    if (existing == null) {
      indexByKey.set(key, groups.length);
      groups.push({ key, title, items: [item] });
      continue;
    }
    groups[existing].items.push(item);
  }
  return groups;
}

function MemoryReadableBlocks({
  blocks,
  emptyText,
}: {
  blocks: ReadableMemoryBlock[];
  emptyText: string;
}) {
  if (!blocks.length) {
    return <p className={styles.body}>{emptyText}</p>;
  }
  return (
    <>
      {blocks.map((block, index) => {
        if (block.kind === "list") {
          return (
            <ul key={`list-${index}`} className={styles.list}>
              {block.items.map((item, itemIndex) => (
                <li key={`${itemIndex}`}>{item}</li>
              ))}
            </ul>
          );
        }
        if (block.kind === "fields") {
          return (
            <dl key={`fields-${index}`} className={styles.fieldList}>
              {block.entries.map((entry) => (
                <div key={entry.label}>
                  <dt className={styles.fieldLabel}>{entry.label}</dt>
                  <dd className={styles.fieldValue}>{entry.value}</dd>
                </div>
              ))}
            </dl>
          );
        }
        return (
          <p key={`text-${index}`} className={styles.body}>{block.text}</p>
        );
      })}
    </>
  );
}

function SkeletonCardGrid({ count }: { count: number }) {
  return (
    <div className={styles.cardGrid} aria-hidden="true">
      {Array.from({ length: count }).map((_, index) => (
        <VSurface key={index} tone="card" elevation="panel" padding="normal" className={styles.skeletonCard}>
          <VSkeleton shape="line" className="max-w-[70%]" />
          <VSkeleton shape="line" className="max-w-[40%]" />
        </VSurface>
      ))}
    </div>
  );
}

export function MemoryContentBrowsePanel({
  copy,
  searchText,
  onSearchTextChange,
  cards,
  selectedCardId,
  onSelectCard,
  onClearCard,
  entries,
  selectedEntryId,
  onSelectEntry,
  loading = false,
  errorText = "",
  entriesLoading = false,
}: MemoryContentBrowsePanelProps) {
  const ungrouped = copy.ungrouped || copy.browseSelectCard;
  const selectedCard = cards.find((card) => card.id === selectedCardId) ?? null;
  const cardGroups = groupItems(cards, ungrouped);
  const entryGroups = groupItems(entries, selectedCard?.title || ungrouped);

  return (
    <div className={styles.root} data-vui-region="memory-content-browse">
      {onSearchTextChange && !selectedCard ? (
        <label className={styles.searchBox}>
          <Search size={15} />
          <VNativeInput
            value={searchText ?? ""}
            placeholder={copy.searchPlaceholder}
            onChange={(event) => onSearchTextChange(event.target.value)}
            aria-label={copy.searchPlaceholder}
          />
        </label>
      ) : null}
      {selectedCard ? (
        <div className={styles.backRow}>
          <VButton type="button" variant="secondary" density="compact" onClick={onClearCard}>
            {copy.browseBack}
          </VButton>
        </div>
      ) : null}
      <div className={styles.scroll}>
        {errorText ? (
          <VStateSurface tone="error" title={copy.loadFailed}>{errorText}</VStateSurface>
        ) : null}
        {!selectedCard ? (
          <>
            {loading && !cards.length ? (
              <VSection title={copy.loading}>
                <SkeletonCardGrid count={6} />
              </VSection>
            ) : null}
            {!loading && !cards.length && !errorText ? (
              <VStateSurface tone="empty" title={copy.browseEmptyCards} />
            ) : null}
            {cardGroups.map((group) => (
              <VSection
                key={group.key}
                className={styles.group}
                title={group.title}
                meta={`${group.items.length}`}
              >
                <div className={styles.cardGrid}>
                  {group.items.map((card) => (
                    <VSurface
                      key={card.id}
                      as="article"
                      tone="card"
                      elevation="panel"
                      padding="normal"
                      className={styles.card}
                      tabIndex={0}
                      role="button"
                      aria-label={card.title}
                      onClick={() => onSelectCard(card.id)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          onSelectCard(card.id);
                        }
                      }}
                    >
                      <strong className={styles.cardTitle}>{card.title}</strong>
                      {card.meta ? <span className={styles.cardMeta}>{card.meta}</span> : null}
                    </VSurface>
                  ))}
                </div>
              </VSection>
            ))}
          </>
        ) : (
          <div className={styles.entryList}>
            {entriesLoading && !entries.length ? (
              <VSection title={copy.loading}>
                <SkeletonCardGrid count={3} />
              </VSection>
            ) : null}
            {!entriesLoading && !entries.length && !errorText ? (
              <VStateSurface tone="empty" title={copy.browseEmptyEntries} />
            ) : null}
            {entryGroups.map((group) => (
              <VSection
                key={group.key}
                className={styles.group}
                title={group.title}
                meta={`${group.items.length}`}
              >
                <div className={styles.entryList}>
                  {group.items.map((entry) => {
                    const active = selectedEntryId === entry.id;
                    return (
                      <VSurface
                        key={entry.id}
                        as="article"
                        tone="card"
                        elevation="panel"
                        padding="normal"
                        className={styles.entryCard}
                        data-active={active ? "true" : "false"}
                        tabIndex={0}
                        role="button"
                        aria-label={entry.title}
                        onClick={() => onSelectEntry(entry.id)}
                        onKeyDown={(event) => {
                          if (event.key === "Enter" || event.key === " ") {
                            event.preventDefault();
                            onSelectEntry(entry.id);
                          }
                        }}
                      >
                        <h3 className={styles.entryTitle}>{entry.title}</h3>
                        <MemoryReadableBlocks
                          blocks={toReadableMemoryBlocks(entry.body)}
                          emptyText={copy.noContent}
                        />
                      </VSurface>
                    );
                  })}
                </div>
              </VSection>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
