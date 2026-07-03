import type { ReactNode } from "react";

import { Brain, Pencil, Search, Square, SquareCheckBig, Trash2, Undo2 } from "lucide-react";

import { VButton, VNativeInput } from "../components/vui";
import styles from "./MemoryRoute.styles";

export type MemoryManageFilterView = {
  id: string;
  label: string;
  count: number;
};

export type MemoryManageSourceFilterView = {
  id: string;
  title: string;
  count: number;
  active: boolean;
};

export type MemoryManagePanelCopy = {
  management: string;
  manageListHint: string;
  manageAllMemory: string;
  searchPlaceholder: string;
  manageFilters: string;
  sourceFilters: string;
  allSections: string;
  selectedCount: string;
  clearSelection: string;
  selectAllVisible: string;
  loading: string;
  bulkDisable: string;
  bulkRestore: string;
  manageConfigPanel: string;
  addMemory: string;
  editMemory: string;
  selectedMemory: string;
  noMatches: string;
};

type MemoryManagePanelProps = {
  copy: MemoryManagePanelCopy;
  warningStrip: ReactNode;
  manageableCount: number;
  visibleItemCount: number;
  searchText: string;
  onSearchTextChange: (value: string) => void;
  manageFilterOptions: MemoryManageFilterView[];
  activeManageFilterId: string;
  onManageFilterChange: (filterId: string) => void;
  sourceFilters: MemoryManageSourceFilterView[];
  allSectionsActive: boolean;
  onSelectAllSections: () => void;
  onSelectSourceFilter: (sectionId: string) => void;
  mutationBusy: boolean;
  allVisibleSelected: boolean;
  onToggleVisibleSelection: () => void;
  selectedMemoryCount: number;
  onBulkDisable: () => void;
  onBulkRestore: () => void;
  disableBulkDisabled: boolean;
  restoreBulkDisabled: boolean;
  disableBulkPending: boolean;
  restoreBulkPending: boolean;
  memoryList: ReactNode;
  editMode: "create" | "edit" | null;
  onStartCreate: () => void;
  managementEditor: ReactNode;
  selectedConfig: ReactNode;
  showEmptySelection: boolean;
  detailPanel: ReactNode;
};

export function MemoryManagePanel({
  copy,
  warningStrip,
  manageableCount,
  visibleItemCount,
  searchText,
  onSearchTextChange,
  manageFilterOptions,
  activeManageFilterId,
  onManageFilterChange,
  sourceFilters,
  allSectionsActive,
  onSelectAllSections,
  onSelectSourceFilter,
  mutationBusy,
  allVisibleSelected,
  onToggleVisibleSelection,
  selectedMemoryCount,
  onBulkDisable,
  onBulkRestore,
  disableBulkDisabled,
  restoreBulkDisabled,
  disableBulkPending,
  restoreBulkPending,
  memoryList,
  editMode,
  onStartCreate,
  managementEditor,
  selectedConfig,
  showEmptySelection,
  detailPanel,
}: MemoryManagePanelProps) {
  return (
    <>
      {warningStrip}
      <div className={`${styles.workspace} ${styles.manageWorkspace}`}>
        <main className={styles.manageListPanel}>
          <div className={styles.panelHeader}>
            <div>
              <p className={styles.panelEyebrow}>{copy.management}</p>
              <h2 title={copy.manageListHint}>{copy.manageAllMemory}</h2>
            </div>
            <span className={styles.countPill}>{manageableCount}</span>
          </div>
          <label className={styles.searchBox}>
            <Search size={15} />
            <VNativeInput value={searchText} placeholder={copy.searchPlaceholder} onChange={(event) => onSearchTextChange(event.target.value)} />
          </label>
          <section className={styles.manageFilterPanel} aria-label={copy.manageFilters}>
            <div className={styles.manageFilterHeader}>
              <span>{copy.manageFilters}</span>
              <strong>{visibleItemCount}</strong>
            </div>
            <div className={styles.filterGroup}>
              {manageFilterOptions.map((option) => (
                <VButton
                  key={option.id}
                  type="button"
                  className={option.id === activeManageFilterId ? `${styles.filterButton} ${styles.filterButtonActive}` : styles.filterButton}
                  onClick={() => onManageFilterChange(option.id)}
                  aria-pressed={option.id === activeManageFilterId}
                >
                  <span>{option.label}</span>
                  <strong>{option.count}</strong>
                </VButton>
              ))}
            </div>
          </section>
          <section className={styles.manageSourceFilters} aria-label={copy.sourceFilters}>
            <VButton
              type="button"
              className={allSectionsActive ? `${styles.sourceChip} ${styles.sourceChipActive}` : styles.sourceChip}
              onClick={onSelectAllSections}
              aria-pressed={allSectionsActive}
            >
              <span>{copy.allSections}</span>
              <strong>{manageableCount}</strong>
            </VButton>
            {sourceFilters.map((section) => (
              <VButton
                key={section.id}
                type="button"
                className={section.active ? `${styles.sourceChip} ${styles.sourceChipActive}` : styles.sourceChip}
                onClick={() => onSelectSourceFilter(section.id)}
                aria-pressed={section.active}
                title={section.title}
              >
                <span>{section.title}</span>
                <strong>{section.count}</strong>
              </VButton>
            ))}
          </section>
          <section className={styles.bulkActionBar}>
            <VButton type="button" className={styles.detailActionButton} onClick={onToggleVisibleSelection} isDisabled={mutationBusy}>
              {allVisibleSelected ? <SquareCheckBig size={14} /> : <Square size={14} />}
              <span>{allVisibleSelected ? copy.clearSelection : copy.selectAllVisible}</span>
            </VButton>
            <span className={styles.countPill}>
              {copy.selectedCount}: {selectedMemoryCount}
            </span>
            <VButton type="button" className={styles.detailActionButton} onClick={onBulkDisable} isDisabled={disableBulkDisabled}>
              <Trash2 size={14} />
              <span>{disableBulkPending ? copy.loading : copy.bulkDisable}</span>
            </VButton>
            <VButton type="button" className={styles.detailActionButton} onClick={onBulkRestore} isDisabled={restoreBulkDisabled}>
              <Undo2 size={14} />
              <span>{restoreBulkPending ? copy.loading : copy.bulkRestore}</span>
            </VButton>
          </section>
          {memoryList}
        </main>

        <section className={styles.manageFormPanel}>
          <div className={styles.managementHeader}>
            <div>
              <p className={styles.panelEyebrow}>{copy.management}</p>
              <h2>{editMode ? (editMode === "create" ? copy.addMemory : copy.editMemory) : copy.manageConfigPanel}</h2>
            </div>
            <VButton type="button" className={styles.primaryActionButton} onClick={onStartCreate} isDisabled={mutationBusy}>
              <Pencil size={15} />
              <span>{copy.addMemory}</span>
            </VButton>
          </div>
          {managementEditor}
          {selectedConfig}
          {showEmptySelection ? (
            <section className={styles.emptyDetail}>
              <Brain size={24} />
              <strong>{copy.selectedMemory}</strong>
              <p>{copy.noMatches}</p>
            </section>
          ) : null}
        </section>

        {detailPanel}
      </div>
    </>
  );
}
