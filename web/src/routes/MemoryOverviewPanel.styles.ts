const styles = {
  overviewGrid:
    "overviewGrid min-w-0 grid gap-2 grid-cols-[repeat(2,minmax(0,1fr))] gap-2 max-[900px]:grid-cols-1",
  overviewPanel:
    "overviewPanel grid min-h-0 grid-rows-[auto_minmax(0,1fr)] overflow-auto",
  reviewQueuePanel:
    "reviewQueuePanel grid min-h-0 max-h-[min(280px,34vh)] content-start gap-1.5 overflow-auto",
} as const;

export default styles;
