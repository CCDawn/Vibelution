import {
  vuiOpaqueRowClass,
  vuiWorkspaceFillClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  backRow:
    "backRow flex min-w-0 items-center gap-2",
  body:
    "body min-h-0 min-w-0 whitespace-pre-wrap break-words [font-size:var(--vui-font-sm)] leading-relaxed text-[var(--fg-primary)]",
  card:
    "card min-w-0 cursor-pointer text-left grid gap-1 self-start",
  cardGrid:
    "cardGrid grid min-w-0 w-full content-start items-start gap-2 [grid-template-columns:repeat(auto-fill,minmax(220px,1fr))]",
  cardMeta:
    "cardMeta [font-size:var(--vui-font-xs)] text-[var(--fg-tertiary)]",
  cardTitle:
    "cardTitle min-w-0 truncate [font-size:var(--vui-font-md)] font-semibold text-[var(--fg-primary)]",
  entryCard:
    "entryCard min-w-0 grid gap-2 self-start",
  entryList:
    "entryList grid min-w-0 content-start gap-3",
  entryTitle:
    "entryTitle min-w-0 [font-size:var(--vui-font-md)] font-semibold text-[var(--fg-primary)]",
  fieldLabel:
    "fieldLabel min-w-0 [font-size:var(--vui-font-xs)] font-semibold uppercase tracking-[0.04em] text-[var(--fg-tertiary)]",
  fieldList:
    "fieldList grid min-w-0 content-start gap-2",
  fieldValue:
    "fieldValue min-w-0 whitespace-pre-wrap break-words [font-size:var(--vui-font-sm)] text-[var(--fg-primary)]",
  group:
    "group grid min-w-0 content-start gap-2",
  list:
    "list grid min-w-0 gap-1 pl-4 [font-size:var(--vui-font-sm)] text-[var(--fg-primary)]",
  root: `root flex min-h-0 min-w-0 h-full flex-1 flex-col content-start overflow-hidden ${vuiWorkspaceFillClass}`,
  scroll:
    "scroll grid min-h-0 min-w-0 flex-1 content-start gap-4 overflow-auto p-1 [align-content:start]",
  searchBox: `searchBox min-w-0 flex items-center gap-1.5 ${vuiOpaqueRowClass} px-2 py-1`,
  skeletonCard:
    "skeletonCard grid min-h-[4.5rem] gap-2 self-start p-3",
} as const;

export default styles;
