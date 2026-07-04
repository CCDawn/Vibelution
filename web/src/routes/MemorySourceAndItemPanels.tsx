import type { ReactNode } from "react";

import { Brain, Database, Search, TriangleAlert } from "lucide-react";

import { VButton, VNativeInput } from "../components/vui";
import styles from "./MemorySourceAndItemPanels.styles";

export type MemorySourceFilterView = {
  id: string;
  label: string;
  count: number;
};

export type MemorySourceSectionView = {
  id: string;
  title: string;
  sourcePath?: string;
  sourceApi?: string;
  sourceKind: string;
  itemCount: number;
  promptCount: number;
  active: boolean;
};

export type MemorySourceAndItemPanelsCopy = {
  sections: string;
  allSections: string;
  searchPlaceholder: string;
  filters: string;
  items: string;
  refreshFailed: string;
};

type MemorySourceAndItemPanelsProps = {
  copy: MemorySourceAndItemPanelsCopy;
  sourceTitle: string;
  itemTitle: string;
  selectedSectionVisibleCount: number;
  searchText: string;
  onSearchTextChange: (value: string) => void;
  filterOptions: MemorySourceFilterView[];
  activeFilterId: string;
  onFilterChange: (filterId: string) => void;
  allSectionsActive: boolean;
  flatVisibleItemCount: number;
  selectedSectionPromptCount: number;
  onSelectAllSections: () => void;
  sections: MemorySourceSectionView[];
  onSelectSection: (sectionId: string) => void;
  showRefreshNotice: boolean;
  refreshErrorText: string;
  memoryList: ReactNode;
};

export function MemorySourceAndItemPanels({
  copy,
  sourceTitle,
  itemTitle,
  selectedSectionVisibleCount,
  searchText,
  onSearchTextChange,
  filterOptions,
  activeFilterId,
  onFilterChange,
  allSectionsActive,
  flatVisibleItemCount,
  selectedSectionPromptCount,
  onSelectAllSections,
  sections,
  onSelectSection,
  showRefreshNotice,
  refreshErrorText,
  memoryList,
}: MemorySourceAndItemPanelsProps) {
  return (
    <>
      <aside className={styles.sourcePanel}>
        <div className={styles.panelHeader}>
          <div>
            <p className={styles.panelEyebrow}>{copy.sections}</p>
            <h2>{sourceTitle}</h2>
          </div>
          <span className={styles.countPill}>{selectedSectionVisibleCount}</span>
        </div>

        <label className={styles.searchBox}>
          <Search size={15} />
          <VNativeInput value={searchText} placeholder={copy.searchPlaceholder} onChange={(event) => onSearchTextChange(event.target.value)} />
        </label>

        <div className={styles.filterGroup} aria-label={copy.filters}>
          {filterOptions.map((option) => (
            <VButton
              key={option.id}
              type="button"
              className={option.id === activeFilterId ? `${styles.filterButton} ${styles.filterButtonActive}` : styles.filterButton}
              onClick={() => onFilterChange(option.id)}
              aria-pressed={option.id === activeFilterId}
            >
              <span>{option.label}</span>
              <strong>{option.count}</strong>
            </VButton>
          ))}
        </div>

        <VButton
          type="button"
          className={allSectionsActive ? `${styles.sourceButton} ${styles.sourceButtonActive}` : styles.sourceButton}
          onClick={onSelectAllSections}
        >
          <span className={styles.sourceIcon}>
            <Database size={15} />
          </span>
          <span className={styles.sourceCopy}>
            <strong>{copy.allSections}</strong>
            <span>
              {copy.items}: {flatVisibleItemCount}
              {selectedSectionPromptCount ? ` / ${selectedSectionPromptCount}` : ""}
            </span>
          </span>
        </VButton>

        <nav className={styles.sourceList} aria-label={copy.sections}>
          {sections.map((section) => (
            <VButton
              key={section.id}
              type="button"
              className={section.active ? `${styles.sourceButton} ${styles.sourceButtonActive}` : styles.sourceButton}
              onClick={() => onSelectSection(section.id)}
              aria-pressed={section.active}
            >
              <span className={styles.sourceIcon}>
                <Brain size={15} />
              </span>
              <span className={styles.sourceCopy}>
                <strong>{section.title}</strong>
                <span>{[section.sourcePath, section.sourceApi].filter(Boolean).join(" · ") || section.sourceKind}</span>
              </span>
              <span className={styles.sourceStats}>
                {section.itemCount}
                {section.promptCount ? ` / ${section.promptCount}` : ""}
              </span>
            </VButton>
          ))}
        </nav>
      </aside>

      <main className={styles.itemPanel}>
        <div className={styles.panelHeader}>
          <div>
            <p className={styles.panelEyebrow}>{copy.items}</p>
            <h2>{itemTitle}</h2>
          </div>
          <span className={styles.countPill}>{flatVisibleItemCount}</span>
        </div>

        {showRefreshNotice ? (
          <section className={styles.panelNotice} aria-label={copy.refreshFailed}>
            <TriangleAlert size={16} />
            <strong>{copy.refreshFailed}</strong>
            <span>{refreshErrorText}</span>
          </section>
        ) : null}

        {memoryList}
      </main>
    </>
  );
}
