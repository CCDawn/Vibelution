/**
 * SC inject: filter bar options + selection wiring.
 */
import {
  TeamSourceCollectionFilterBar,
  type TeamSourceCollectionFilterOption,
} from "../TeamSourceCollectionResultControls";
import { buildSourceCollectionFilterBarOptions } from "./source-collection/injectModel";
import {
  SOURCE_COLLECTION_SOURCE_FILTERS,
  sourceCollectionSourceFilterLabel,
  type SourceCollectionSourceFilter,
} from "./source-collection/evidenceModel";

export type TeamSourceCollectionFilterBarInjectProps = {
  lang: "zh" | "en";
  counts: Record<SourceCollectionSourceFilter, number>;
  label: string;
  selected: SourceCollectionSourceFilter;
  loading?: boolean;
  loadingAllText: string;
  onSelect: (filter: SourceCollectionSourceFilter) => void;
};

export function TeamSourceCollectionFilterBarInject({
  lang,
  counts,
  label,
  selected,
  loading = false,
  loadingAllText,
  onSelect,
}: TeamSourceCollectionFilterBarInjectProps) {
  const options = buildSourceCollectionFilterBarOptions({
    filters: SOURCE_COLLECTION_SOURCE_FILTERS,
    counts,
    selected,
    loading,
    loadingAllText,
    labelFor: (filter) => sourceCollectionSourceFilterLabel(filter, lang),
  }) as Array<TeamSourceCollectionFilterOption<SourceCollectionSourceFilter>>;

  return (
    <TeamSourceCollectionFilterBar
      ariaLabel={label}
      options={options}
      onSelect={onSelect}
    />
  );
}
