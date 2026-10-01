const root =
  "grid h-full grid-rows-[auto_minmax(0,1fr)] min-h-0 min-w-0 overflow-hidden bg-vui-surface-panel text-vui-fg-primary";

const styles = {
  workspace: "!gap-0",
  columns: "grid-cols-[176px_minmax(0,1fr)] max-[700px]:grid-cols-1 max-[700px]:grid-rows-[auto_minmax(0,1fr)]",
  main: "h-full min-h-0 min-w-0 overflow-hidden",
  root,
} as const;

export default styles;
