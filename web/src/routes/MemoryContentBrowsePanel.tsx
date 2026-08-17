import { Search } from "lucide-react";

import { WORKBENCH_LAYOUT_IDS } from "../components/layout/workbenchLayoutIds";
import { VButton, VNativeInput, VSplitWorkspace, VStateSurface, VSurface } from "../components/vui";
import styles from "./MemoryContentBrowsePanel.styles";

export type MemoryBrowseCard = {
  id: string;
  title: string;
  meta?: string;
};

export type MemoryBrowseEntry = {
  id: string;
  title: string;
  body: string;
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
  const selectedCard = cards.find((card) => card.id === selectedCardId) ?? null;
  const activeEntry = entries.find((entry) => entry.id === selectedEntryId) ?? entries[0] ?? null;

  if (loading) {
    return (
      <div className={styles.root}>
        <VStateSurface fill tone="loading" title={copy.loading} skeletonLines={3} />
      </div>
    );
  }
  if (errorText) {
    return (
      <div className={styles.root}>
        <VStateSurface fill tone="error" title={copy.loadFailed}>
          {errorText}
        </VStateSurface>
      </div>
    );
  }
  if (!selectedCard) {
    return (
      <div className={styles.root}>
        {onSearchTextChange ? (
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
        {!cards.length ? <VStateSurface fill tone="empty" title={copy.browseEmptyCards} /> : null}
        {cards.length ? (
          <div className={styles.cardGrid}>
            {cards.map((card) => (
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
        ) : null}
      </div>
    );
  }

  return (
    <VSplitWorkspace
      className={styles.root}
      data-vui-region="memory-content-browse"
      data-vui-layout-id={WORKBENCH_LAYOUT_IDS.memory}
      resize={{
        layoutId: WORKBENCH_LAYOUT_IDS.memory,
        sidebar: { id: "memory-browse-list", defaultWidth: 260, minWidth: 200, maxWidth: 360 },
      }}
      sidebar={(
        <div className={styles.list}>
          <div className={styles.backRow}>
            <VButton type="button" variant="secondary" density="compact" onClick={onClearCard}>
              {copy.browseBack}
            </VButton>
          </div>
          <div className={styles.listItems}>
            {entriesLoading ? <VStateSurface tone="loading" title={copy.loading} skeletonLines={2} /> : null}
            {!entriesLoading && !entries.length ? <VStateSurface tone="empty" title={copy.browseEmptyEntries} /> : null}
            {entries.map((entry) => {
              const active = (activeEntry?.id ?? "") === entry.id;
              return (
                <VButton
                  key={entry.id}
                  type="button"
                  contentLayout="plain"
                  className={active ? `${styles.entryButton} ${styles.entryButtonActive}` : styles.entryButton}
                  onClick={() => onSelectEntry(entry.id)}
                >
                  {entry.title}
                </VButton>
              );
            })}
          </div>
        </div>
      )}
      main={(
        <div className={styles.detail}>
          {activeEntry ? (
            <>
              <h2 className={styles.detailTitle}>{activeEntry.title}</h2>
              <div className={styles.body}>{activeEntry.body.trim() ? activeEntry.body : copy.noContent}</div>
            </>
          ) : (
            <VStateSurface fill tone="empty" title={copy.browseSelectCard} />
          )}
        </div>
      )}
    />
  );
}
