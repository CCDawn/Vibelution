import {
  vuiWorkspaceFillClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  // Metrics stay auto; priority queue is the primary scan surface; bottom lists stay a compact strip.
  overviewStack:
    "overviewStack grid min-h-0 min-w-0 flex-1 grid-rows-[auto_auto_minmax(12rem,1fr)_auto_minmax(10rem,0.42fr)] gap-2 overflow-hidden p-1",
  overviewGrid:
    "overviewGrid min-h-0 min-w-0 grid gap-2 overflow-hidden grid-cols-1",
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
