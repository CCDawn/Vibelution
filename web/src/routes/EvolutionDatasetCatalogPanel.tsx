import type { EvolutionWorkbench } from "../api/types";
import { VTabs, VTooltip } from "../components/vui";
import { datasetCatalogStatusLabel } from "./evolution/evolutionRouteModel";
import styles from "./EvolutionRoute.styles";

export type EvolutionDatasetCatalogFilter = "all" | "runnable" | "blocked" | "roadmap";

export type EvolutionDatasetCatalogItem = NonNullable<EvolutionWorkbench["datasets"]>[number];

export type EvolutionDatasetCatalogPanelCopy = {
  datasetCatalog: string;
  datasetCatalogAll: string;
  datasetCatalogRunnable: string;
  datasetCatalogBlocked: string;
  datasetCatalogRoadmap: string;
  datasetCatalogHiddenReason: string;
};

type EvolutionDatasetCatalogPanelProps = {
  lang: "zh" | "en";
  copy: EvolutionDatasetCatalogPanelCopy;
  items: EvolutionDatasetCatalogItem[];
  groups: Record<EvolutionDatasetCatalogFilter, EvolutionDatasetCatalogItem[]>;
  selectedFilter: EvolutionDatasetCatalogFilter;
  onFilterChange: (filter: EvolutionDatasetCatalogFilter) => void;
};

/**
 * Presentational dataset catalog strip for Evolution live launch console.
 * Keeps catalog chrome out of EvolutionRoute orchestrator.
 */
export function EvolutionDatasetCatalogPanel({
  lang,
  copy,
  items,
  groups,
  selectedFilter,
  onFilterChange,
}: EvolutionDatasetCatalogPanelProps) {
  if (!items.length) {
    return null;
  }

  const visible = groups[selectedFilter] ?? groups.all;
  const filters: Array<[EvolutionDatasetCatalogFilter, string, number]> = [
    ["all", copy.datasetCatalogAll, groups.all.length],
    ["runnable", copy.datasetCatalogRunnable, groups.runnable.length],
    ["blocked", copy.datasetCatalogBlocked, groups.blocked.length],
    ["roadmap", copy.datasetCatalogRoadmap, groups.roadmap.length],
  ];

  return (
    <details className={styles.datasetCatalogPanel} data-vui-region="evolution-dataset-catalog">
      <summary className={styles.datasetCatalogSummary}>
        <span>
          <strong>{copy.datasetCatalog}</strong>
          <span>
            {items.length} · {lang === "zh" ? "可运行" : "runnable"} {groups.runnable.length}
          </span>
        </span>
        <span>{lang === "zh" ? "展开管理" : "Manage"}</span>
      </summary>
      <div className={styles.datasetCatalogBody}>
        <VTabs
          aria-label={copy.datasetCatalog}
          value={selectedFilter}
          onValueChange={(value) => {
            if (
              value === "all"
              || value === "runnable"
              || value === "blocked"
              || value === "roadmap"
            ) {
              onFilterChange(value);
            }
          }}
          className="min-w-0"
          listClassName={styles.datasetCatalogFilterRow}
          triggerClassName={styles.datasetCatalogFilterButton}
          items={filters.map(([filter, label, count]) => ({
            id: filter,
            label: `${label} ${count}`,
          }))}
        />
        <div className={styles.datasetCatalogList}>
          {visible.length > 0 ? (
            visible.map((item) => {
              const statusText = datasetCatalogStatusLabel(item, lang);
              const reason = item.visibility === "primary"
                ? item.usabilityReason
                : (item.visibilityReason || item.usabilityReason);
              return (
                <article key={item.name} className={styles.datasetCatalogItem}>
                  <div className={styles.datasetCatalogItemMain}>
                    <VTooltip content={item.name} width="wide">
                      <strong tabIndex={0}>{item.name}</strong>
                    </VTooltip>
                    <span>{item.benchmarkFamily || item.taskType || item.bundleName || "--"}</span>
                  </div>
                  <span className={styles.datasetCatalogStatus}>{statusText}</span>
                  {reason ? (
                    <p>
                      <span>{item.visibility === "primary" ? statusText : copy.datasetCatalogHiddenReason}</span>
                      {reason}
                    </p>
                  ) : null}
                </article>
              );
            })
          ) : (
            <p className={styles.datasetCatalogEmpty}>{lang === "zh" ? "当前筛选无条目。" : "No entries for this filter."}</p>
          )}
        </div>
      </div>
    </details>
  );
}
