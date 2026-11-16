import { Check, ChevronDown, ChevronRight } from "lucide-react";
import {
  type KeyboardEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { VButton, VNativeInput, VStateSurface } from "../vui";
import styles from "./ConversationModelCandidateList.styles";

/** One model row, already mapped from the host's own choice DTO. */
export type ConversationModelCandidateRow = {
  /** Stable identity inside the menu (modelRef or modelId). */
  key: string;
  label: string;
  /** Full identity kept as the row tooltip. */
  title?: string;
  /** Localized reason; non-empty marks the row disabled and prints the why. */
  reason?: string;
  /** Machine-readable reason code for host contracts (optional). */
  reasonCode?: string;
  /** Right-aligned action copy such as "添加"; empty for selectable rows. */
  action?: string;
  pending?: boolean;
};

export type ConversationModelCandidateGroup = {
  groupKey: string;
  groupLabel: string;
  items: ConversationModelCandidateRow[];
};

/** Optional standalone row above the groups (Agent "Default" binding). */
export type ConversationModelCandidateLeadingOption = {
  label: string;
  selected: boolean;
  onSelect: () => void;
};

/**
 * Which provider groups are open for a given query. Plain search expands every
 * group except the ones the operator collapsed; a non-empty query inverts the
 * ownership so folding a group during search never outlives the query.
 */
export function expandedModelCandidateGroupKeys(
  groups: readonly ConversationModelCandidateGroup[],
  query: string,
  manuallyExpandedGroupKeys: ReadonlySet<string>,
  searchCollapsedGroupKeys: ReadonlySet<string>,
): Set<string> {
  const searching = Boolean(query.trim());
  return new Set(
    groups
      .filter((group) => (searching
        ? !searchCollapsedGroupKeys.has(group.groupKey)
        : manuallyExpandedGroupKeys.has(group.groupKey)))
      .map((group) => group.groupKey),
  );
}

export type ConversationModelCandidateListProps = {
  lang: "zh" | "en";
  /** Groups already filtered by the host's own search semantics. */
  groups: readonly ConversationModelCandidateGroup[];
  selectedKey: string;
  disabled?: boolean;
  /** Search text is host-owned: the host re-filters and re-groups per keystroke. */
  query: string;
  onQueryChange: (query: string) => void;
  /** Groups expanded on mount (normally the selected row's provider). */
  defaultExpandedGroupKeys?: readonly string[];
  leadingOption?: ConversationModelCandidateLeadingOption;
  onSelect: (key: string) => void;
  /** Accessible name of the whole list. */
  listLabel: string;
  searchLabel?: string;
  emptyLabel?: string;
  "data-testid"?: string;
};

function providerModelCount(lang: "zh" | "en", count: number) {
  return lang === "zh" ? `${count} 个模型` : `${count} models`;
}

/**
 * Shared provider-grouped model menu: search, disclosure groups, disabled
 * reasons, selected check and keyboard traversal. Hosts own the trigger, the
 * popover shell and the actual model action (pin/switch).
 */
export function ConversationModelCandidateList({
  lang,
  groups,
  selectedKey,
  disabled = false,
  query,
  onQueryChange,
  defaultExpandedGroupKeys,
  leadingOption,
  onSelect,
  listLabel,
  searchLabel,
  emptyLabel,
  "data-testid": dataTestId,
}: ConversationModelCandidateListProps) {
  const searchRef = useRef<HTMLInputElement | null>(null);
  const optionRefs = useRef(new Map<string, HTMLButtonElement>());
  const [activeKey, setActiveKey] = useState("");
  const [manuallyExpandedGroupKeys, setManuallyExpandedGroupKeys] = useState<Set<string>>(
    () => new Set(defaultExpandedGroupKeys ?? []),
  );
  const [searchCollapsedGroupKeys, setSearchCollapsedGroupKeys] = useState<Set<string>>(
    () => new Set(),
  );

  const expandedGroupKeys = useMemo(
    () => expandedModelCandidateGroupKeys(
      groups,
      query,
      manuallyExpandedGroupKeys,
      searchCollapsedGroupKeys,
    ),
    [groups, manuallyExpandedGroupKeys, query, searchCollapsedGroupKeys],
  );

  const enabledKeys = useMemo(
    () => groups
      .filter((group) => expandedGroupKeys.has(group.groupKey))
      .flatMap((group) => group.items)
      .filter((row) => !row.reason && !disabled)
      .map((row) => row.key),
    [disabled, expandedGroupKeys, groups],
  );

  useEffect(() => {
    setActiveKey((current) => (enabledKeys.includes(current) ? current : enabledKeys[0] ?? ""));
  }, [enabledKeys]);

  useEffect(() => {
    requestAnimationFrame(() => searchRef.current?.focus());
  }, []);

  function moveActive(delta: number) {
    if (!enabledKeys.length) return;
    const currentIndex = enabledKeys.indexOf(activeKey);
    const nextIndex = currentIndex < 0
      ? 0
      : (currentIndex + delta + enabledKeys.length) % enabledKeys.length;
    const nextKey = enabledKeys[nextIndex]!;
    setActiveKey(nextKey);
    requestAnimationFrame(() => optionRefs.current.get(nextKey)?.focus());
  }

  function focusEdge(edge: "first" | "last") {
    const nextKey = edge === "first" ? enabledKeys[0] : enabledKeys.at(-1);
    if (!nextKey) return;
    setActiveKey(nextKey);
    requestAnimationFrame(() => optionRefs.current.get(nextKey)?.focus());
  }

  function toggleGroup(groupKey: string) {
    const update = (current: Set<string>) => {
      const next = new Set(current);
      if (next.has(groupKey)) next.delete(groupKey);
      else next.add(groupKey);
      return next;
    };
    if (query.trim()) {
      setSearchCollapsedGroupKeys(update);
      return;
    }
    setManuallyExpandedGroupKeys(update);
  }

  function handlePanelKeyDown(event: KeyboardEvent) {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      moveActive(event.key === "ArrowDown" ? 1 : -1);
      return;
    }
    if (event.key === "Home" || event.key === "End") {
      event.preventDefault();
      focusEdge(event.key === "Home" ? "first" : "last");
    }
  }

  return (
    <div className={styles.root} data-testid={dataTestId} data-vui="conversation-model-candidate-list">
      <VNativeInput
        ref={searchRef}
        className={styles.search}
        value={query}
        aria-label={searchLabel ?? (lang === "zh" ? "搜索模型" : "Search models")}
        placeholder={searchLabel ?? (lang === "zh" ? "搜索模型" : "Search models")}
        onChange={(event) => onQueryChange(event.target.value)}
      />
      <div className={styles.list} aria-label={listLabel} onKeyDown={handlePanelKeyDown}>
        {leadingOption ? (
          <VButton
            type="button"
            contentLayout="plain"
            className={`${styles.option} ${leadingOption.selected ? styles.optionSelected : ""}`}
            isDisabled={disabled}
            aria-selected={leadingOption.selected}
            role="option"
            onPress={leadingOption.onSelect}
          >
            <span className={styles.optionCopy}>
              <span className={styles.optionTitle}>
                <span>{leadingOption.label}</span>
                {leadingOption.selected
                  ? <Check className={styles.check} size={14} aria-hidden="true" />
                  : null}
              </span>
            </span>
          </VButton>
        ) : null}
        {groups.map((group, groupIndex) => {
          const groupExpanded = expandedGroupKeys.has(group.groupKey);
          const groupPanelId = `conversation-model-group-${groupIndex}-${group.groupKey.replace(/[^a-zA-Z0-9_-]/g, "-")}`;
          return (
            <section key={group.groupKey} className={styles.group} aria-label={group.groupLabel}>
              <VButton
                type="button"
                contentLayout="plain"
                className={styles.groupHeader}
                aria-expanded={groupExpanded}
                aria-controls={groupPanelId}
                onPress={() => toggleGroup(group.groupKey)}
              >
                <span className={styles.groupTitle}>
                  {groupExpanded
                    ? <ChevronDown className={styles.groupChevron} size={14} aria-hidden="true" />
                    : <ChevronRight className={styles.groupChevron} size={14} aria-hidden="true" />}
                  <span>{group.groupLabel}</span>
                </span>
                <span className={styles.groupCount}>{providerModelCount(lang, group.items.length)}</span>
              </VButton>
              <div
                id={groupPanelId}
                className={styles.groupItems}
                role="listbox"
                aria-label={`${group.groupLabel} ${listLabel}`}
                hidden={!groupExpanded}
              >
                {group.items.map((row) => {
                  const selectedRow = row.key === selectedKey;
                  const rowDisabled = disabled || Boolean(row.reason);
                  return (
                    <VButton
                      key={row.key}
                      ref={(node) => {
                        if (node) optionRefs.current.set(row.key, node);
                        else optionRefs.current.delete(row.key);
                      }}
                      type="button"
                      contentLayout="plain"
                      role="option"
                      className={`${styles.option} ${selectedRow ? styles.optionSelected : ""} ${row.reason ? styles.optionDisabled : ""}`}
                      isDisabled={rowDisabled}
                      aria-selected={selectedRow}
                      data-reason-code={row.reasonCode || undefined}
                      title={row.title ?? row.label}
                      onFocus={() => setActiveKey(row.key)}
                      onPress={() => {
                        if (rowDisabled) return;
                        onSelect(row.key);
                      }}
                    >
                      <span className={styles.optionCopy}>
                        <span className={styles.optionTitle}>
                          <span>{row.label}</span>
                          {selectedRow ? <Check className={styles.check} size={14} aria-hidden="true" /> : null}
                        </span>
                      </span>
                      <span className={styles.action}>
                        {row.pending
                          ? (lang === "zh" ? "处理中…" : "Pending…")
                          : row.action ?? ""}
                      </span>
                      {row.reason ? <span className={styles.reason}>{row.reason}</span> : null}
                    </VButton>
                  );
                })}
              </div>
            </section>
          );
        })}
        {!groups.length
          ? <VStateSurface tone="empty" title={emptyLabel ?? (lang === "zh" ? "没有匹配的模型" : "No matching models")} />
          : null}
      </div>
    </div>
  );
}