import { PersistedHeightListShell } from "../components/layout/PersistedHeightListShell";
import { VButton, VNativeInput, VStateSurface, VStatusChip, type VStatusTone } from "../components/vui";
import type { MemoryItem, MemorySection } from "../api/types";
import styles from "./MemoryItemListPanel.styles";
import {
  MEMORY_COMPACT_LIST_HEIGHT_PANE,
  MEMORY_LIST_HEIGHT_LAYOUT_ID,
} from "./memoryListHeights";

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
  fillParent?: boolean;
  selectable?: boolean;
  activePairKey: string;
  selectedMemoryKeys: ReadonlySet<string>;
  copy: MemoryItemListCopy;
  formatTimestamp: (value: string) => string;
  formatSourceOrigin: (section: MemorySection, item: MemoryItem) => string;
  statusTone: (active: boolean, injected: boolean) => VStatusTone;
  channelPills: (item: MemoryItem) => MemoryItemListChannelPill[];
  onSelectPair: (sectionId: string, itemId: string) => void;
  onToggleSelection: (sectionId: string, itemId: string) => void;
};

function memoryItemListKey(sectionId: string, itemId: string) {
  return `${sectionId}:${itemId}`;
}

function compactPathLabel(path: string) {
  const normalized = String(path || "").replace(/\\/g, "/");
  const name = normalized.split("/").filter(Boolean).pop();
  return name || path;
}

export function MemoryItemListPanel({
  pairs,
  emptyText,
  loading,
  errorText,
  compact = false,
  fillParent = false,
  selectable = false,
  activePairKey,
  selectedMemoryKeys,
  copy,
  formatTimestamp,
  formatSourceOrigin,
  statusTone,
  channelPills,
  onSelectPair,
  onToggleSelection,
}: MemoryItemListPanelProps) {
  if (loading) {
    return <VStateSurface tone="loading" title={copy.loading} skeletonLines={2} />;
  }
  if (errorText) {
    return <VStateSurface tone="error" title={errorText} />;
  }
  if (!pairs.length) {
    return <VStateSurface tone="empty" title={emptyText} />;
  }

  const listItems = pairs.map(({ section, item }) => {
        const itemKey = memoryItemListKey(section.id, item.id);
        const active = itemKey === activePairKey;
        const originLabel = formatSourceOrigin(section, item);
        const updatedAtText = formatTimestamp(item.updatedAt);
        const sourcePath = item.path || item.source;
        const sourceFileLabel = compactPathLabel(sourcePath);
        const statusLabel = item.inPrompt ? copy.inPrompt : item.agentVisible ? copy.canUse : copy.manualOnly;
        const managedStateBadges = (
          <>
            {item.managedState?.userManaged ? <VStatusChip tone="neutral">{copy.userManaged}</VStatusChip> : null}
            {item.managedState?.overridden ? <VStatusChip tone="warning">{copy.overridden}</VStatusChip> : null}
            {item.managedState?.disabled ? <VStatusChip tone="danger">{copy.disabledByUser}</VStatusChip> : null}
            {!item.exists ? <VStatusChip tone="danger">{copy.missing}</VStatusChip> : null}
            {item.contentTruncated ? <VStatusChip tone="warning">{copy.truncated}</VStatusChip> : null}
          </>
        );
        const compactItemBody = (
          <>
            <span className={styles.compactItemPrimary}>
              <strong>{item.title}</strong>
              <span>{updatedAtText}</span>
            </span>
            <span className={styles.compactItemMeta} title={sourcePath}>
              <span>{originLabel}</span>
              <span>{sourceFileLabel}</span>
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
                <VStatusChip tone={statusTone(item.agentVisible, item.inPrompt)}>{statusLabel}</VStatusChip>
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
              <VStatusChip tone={statusTone(item.agentVisible, item.inPrompt)}>{statusLabel}</VStatusChip>
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
                contentLayout="plain"
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
                contentLayout="plain"
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
            contentLayout="plain"
            className={active ? `${styles.itemButton} ${styles.itemButtonActive}` : styles.itemButton}
            onClick={() => onSelectPair(section.id, item.id)}
            aria-pressed={active}
          >
            {itemBody}
          </VButton>
        );
      });

  if (compact) {
    if (fillParent) {
      return (
        <div className={`${styles.compactMemoryList} ${styles.compactMemoryListFill}`} role="region" aria-label={copy.selectMemory}>
          {listItems}
        </div>
      );
    }
    return (
      <PersistedHeightListShell
        layoutId={MEMORY_LIST_HEIGHT_LAYOUT_ID}
        pane={MEMORY_COMPACT_LIST_HEIGHT_PANE}
        label={copy.selectMemory}
        className={styles.compactMemoryList}
        resizeHandleClassName={styles.compactMemoryListResizeHandle}
        role="region"
        aria-label={copy.selectMemory}
      >
        {listItems}
      </PersistedHeightListShell>
    );
  }

  return <div className={styles.itemList}>{listItems}</div>;
}
