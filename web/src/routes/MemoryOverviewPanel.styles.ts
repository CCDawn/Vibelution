import {
  vuiWorkspaceFillClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  // Full overview column: metrics → queues → dual lists, no section paint-through.
  overviewStack:
    "overviewStack grid min-h-0 min-w-0 flex-1 grid-rows-[auto_auto_minmax(0,0.42fr)_auto_minmax(0,1fr)] gap-2 overflow-hidden p-1",
  overviewGrid:
    "overviewGrid min-h-0 min-w-0 grid gap-2 overflow-hidden grid-cols-[repeat(2,minmax(0,1fr))] max-[900px]:grid-cols-1",
  overviewPanel:
    "overviewPanel grid min-h-0 min-w-0 grid-rows-[auto_minmax(0,1fr)] overflow-hidden",
  // Clip at the panel edge; only the list scrolls. Avoid max-h without a real scrollport.
  reviewQueuePanel:
    "reviewQueuePanel relative z-0 grid min-h-0 min-w-0 grid-rows-[auto_minmax(0,1fr)] gap-1.5 overflow-hidden",
  reviewQueueScroll:
    "reviewQueueScroll min-h-0 min-w-0 overflow-y-auto overflow-x-hidden overscroll-contain pr-0.5 [scrollbar-gutter:stable]",
  projectMemorySlot: `projectMemorySlot relative z-[1] min-h-0 min-w-0 shrink-0 overflow-hidden ${vuiWorkspaceFillClass}`,
} as const;

export default styles;
