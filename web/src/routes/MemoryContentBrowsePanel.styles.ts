import {
  vuiOpaqueRowClass,
  vuiStateSelectedRowClass,
  vuiWorkspaceFillClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  backRow:
    "backRow flex min-w-0 items-center gap-2 px-1 py-1",
  body:
    "body min-h-0 min-w-0 flex-1 overflow-auto whitespace-pre-wrap break-words [font-size:var(--vui-font-sm)] leading-relaxed text-[var(--fg-primary)]",
  card:
    "card min-w-0 cursor-pointer text-left grid gap-1",
  cardGrid:
    "cardGrid grid min-h-0 min-w-0 flex-1 content-start gap-2 overflow-auto p-1 [grid-template-columns:repeat(auto-fill,minmax(220px,1fr))]",
  cardMeta:
    "cardMeta [font-size:var(--vui-font-xs)] text-[var(--fg-tertiary)]",
  cardTitle:
    "cardTitle min-w-0 truncate [font-size:var(--vui-font-md)] font-semibold text-[var(--fg-primary)]",
  detail:
    "detail grid min-h-0 min-w-0 grid-rows-[auto_minmax(0,1fr)] gap-2 overflow-hidden p-3",
  detailTitle:
    "detailTitle min-w-0 truncate [font-size:var(--vui-font-md)] font-semibold text-[var(--fg-primary)]",
  entryButton: `entryButton min-w-0 w-full max-w-full !h-auto text-left ${vuiOpaqueRowClass} px-2 py-1.5 [font-size:var(--vui-font-sm)] font-semibold text-[var(--fg-secondary)] [&_[data-slot=vui-button-content]]:w-full [&_[data-slot=vui-button-label]]:block [&_[data-slot=vui-button-label]]:truncate`,
  entryButtonActive: `entryButtonActive ${vuiStateSelectedRowClass}`,
  list:
    "list grid min-h-0 min-w-0 grid-rows-[auto_minmax(0,1fr)] overflow-hidden p-2",
  listItems:
    "listItems grid min-h-0 content-start gap-1 overflow-auto",
  root: `root grid min-h-0 min-w-0 h-full flex-1 overflow-hidden ${vuiWorkspaceFillClass}`,
  searchBox: `searchBox min-w-0 flex items-center gap-1.5 ${vuiOpaqueRowClass} mb-2 px-2 py-1`,
} as const;

export default styles;
