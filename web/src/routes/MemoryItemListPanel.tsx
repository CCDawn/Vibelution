import { VButton, VNativeInput } from "../components/vui";
import type { MemoryItem, MemorySection } from "../api/types";
import styles from "./MemoryRoute.styles";

export type MemoryItemListPair = {
  section: MemorySection;
  item: MemoryItem;
};

export type MemoryItemListChannelPill = {
  label: string;
  hint: string;
};

export type MemoryItemListCopy = {
  loading: string;
  sourceOrigin: string;
  inPrompt: string;
  canUse: string;
  manualOnly: string;
  userManaged: string;
  overridden: string;
  disabledByUser: string;
  missing: string;
  truncated: string;
  selectMemory: string;
};

type MemoryItemListPanelProps = {
  pairs: MemoryItemListPair[];
  emptyText: string;
  loading: boolean;
  errorText: string;
  compact?: boolean;
  selectable?: boolean;
  activePairKey: string;
  selectedMemoryKeys: ReadonlySet<string>;
  copy: MemoryItemListCopy;
  formatTimestamp: (value: string) => string;
  formatSourceOrigin: (section: MemorySection, item: MemoryItem) => string;
  statusClassName: (active: boolean, injected: boolean) => string;
  channelPills: (item: MemoryItem) => MemoryItemListChannelPill[];
  onSelectPair: (sectionId: string, itemId: string) => void;
  onToggleSelection: (sectionId: string, itemId: string) => void;
};

function memoryItemListKey(sectionId: string, itemId: string) {
  return `${sectionId}:${itemId}`;
}

export function MemoryItemListPanel({
  pairs,
  emptyText,
  loading,
  errorText,
  compact = false,
  selectable = false,
  activePairKey,
  selectedMemoryKeys,
  copy,
  formatTimestamp,
  formatSourceOrigin,
  statusClassName,
  channelPills,
  onSelectPair,
  onToggleSelection,
}: MemoryItemListPanelProps) {
  if (loading) {
    return <div className={styles.emptyState}>{copy.loading}</div>;
  }
  if (errorText) {
    return <div className={styles.emptyState}>{errorText}</div>;
  }
  if (!pairs.length) {
    return <div className={styles.emptyState}>{emptyText}</div>;
  }

  return (
    <div className={compact ? styles.compactMemoryList : styles.itemList}>
      {pairs.map(({ section, item }) => {
        const itemKey = memoryItemListKey(section.id, item.id);
        const active = itemKey === activePairKey;
        const originLabel = formatSourceOrigin(section, item);
        const updatedAtText = formatTimestamp(item.updatedAt);
        const sourcePath = item.path || item.source;
        const statusLabel = item.inPrompt ? copy.inPrompt : item.agentVisible ? copy.canUse : copy.manualOnly;
        const managedStateBadges = (
          <>
            {item.managedState?.userManaged ? <span className={styles.statusPill}>{copy.userManaged}</span> : null}
            {item.managedState?.overridden ? <span className={styles.statusPill}>{copy.overridden}</span> : null}
            {item.managedState?.disabled ? <span className={styles.statusPill}>{copy.disabledByUser}</span> : null}
            {!item.exists ? <span className={styles.statusPill}>{copy.missing}</span> : null}
            {item.contentTruncated ? <span className={styles.statusPill}>{copy.truncated}</span> : null}
          </>
        );
        const compactItemBody = (
          <>
            <span className={styles.compactItemPrimary}>
              <strong>{item.title}</strong>
              <span>{updatedAtText}</span>
            </span>
            <span className={styles.compactItemMeta}>
              <span>{originLabel}</span>
              <span title={sourcePath}>{sourcePath}</span>
            </span>
            <span className={styles.compactItemSummary}>{item.summary}</span>
          </>
        );
        const denseItemBody = (
          <>
            <span className={styles.manageItemPrimary}>
              <strong>{item.title}</strong>
              <span>{updatedAtText}</span>
            </span>
            <span className={styles.manageItemMeta}>
              <span>{originLabel}</span>
              <span title={sourcePath}>{sourcePath}</span>
            </span>
            <span className={styles.manageItemFooter}>
              <span className={styles.manageItemSummary}>{item.summary}</span>
              <span className={styles.manageItemBadges}>
                <span className={statusClassName(item.agentVisible, item.inPrompt)}>{statusLabel}</span>
                {managedStateBadges}
              </span>
            </span>
          </>
        );
        const itemBody = (
          <>
            <span className={styles.itemHeader}>
              <strong>{item.title}</strong>
              <span>{updatedAtText}</span>
            </span>
            <span className={styles.itemOrigin}>
              {copy.sourceOrigin}: {originLabel}
            </span>
            <span className={styles.itemPath}>{sourcePath}</span>
            <span className={styles.itemSummary}>{item.summary}</span>
            <span className={styles.itemBadges}>
              <span className={statusClassName(item.agentVisible, item.inPrompt)}>{statusLabel}</span>
              {managedStateBadges}
              {channelPills(item).map((pill) => (
                <span key={`${item.id}:${pill.label}`} className={styles.channelPill} title={pill.hint}>
                  {pill.label}
                </span>
              ))}
            </span>
          </>
        );

        if (selectable) {
          return (
            <article
              key={itemKey}
              className={
                active
                  ? `${styles.itemButton} ${styles.itemButtonDense} ${styles.itemButtonActive}`
                  : `${styles.itemButton} ${styles.itemButtonDense}`
              }
            >
              <label className={`${styles.itemSelectionRow} ${styles.itemSelectionRowDense}`}>
                <VNativeInput
                  type="checkbox"
                  checked={selectedMemoryKeys.has(itemKey)}
                  aria-label={`${copy.selectMemory}: ${item.title}`}
                  onChange={() => onToggleSelection(section.id, item.id)}
                />
              </label>
              <VButton
                type="button"
                className={`${styles.itemContentButton} ${styles.itemContentButtonDense}`}
                onClick={() => onSelectPair(section.id, item.id)}
                aria-pressed={active}
              >
                {denseItemBody}
              </VButton>
            </article>
          );
        }

        if (compact) {
          return (
            <VButton
              key={itemKey}
              type="button"
              className={
                active
                  ? `${styles.itemButton} ${styles.itemButtonCompact} ${styles.itemButtonActive}`
                  : `${styles.itemButton} ${styles.itemButtonCompact}`
              }
              onClick={() => onSelectPair(section.id, item.id)}
              aria-pressed={active}
            >
              {compactItemBody}
            </VButton>
          );
        }

        return (
          <VButton
            key={itemKey}
            type="button"
            className={active ? `${styles.itemButton} ${styles.itemButtonActive}` : styles.itemButton}
            onClick={() => onSelectPair(section.id, item.id)}
            aria-pressed={active}
          >
            {itemBody}
          </VButton>
        );
      })}
    </div>
  );
}
