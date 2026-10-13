const styles = {
  pane: "grid h-full min-h-0 min-w-0 grid-rows-[auto_minmax(0,1fr)]",
  tools: "mx-10 min-w-0 shrink-0 border-b border-vui-border-subtle py-2 max-sm:mx-4",
  summary: "cursor-pointer py-2 text-sm font-medium",
  body: "grid max-h-[240px] gap-4 overflow-y-auto py-4",
} as const;
export default styles;
