const root =
  "grid h-full grid-rows-[auto_minmax(0,1fr)] min-h-0 min-w-0 overflow-hidden bg-vui-surface-workspace text-vui-fg-primary";

const styles = {
  workspace: "!gap-0",
  columns: "grid-cols-[208px_minmax(0,1fr)] max-[1100px]:grid-cols-[184px_minmax(0,1fr)] max-[700px]:grid-cols-1 max-[700px]:grid-rows-[auto_minmax(0,1fr)]",
  main: "mr-1.5 mb-1.5 h-[calc(100%_-_6px)] min-h-0 min-w-0 overflow-hidden !rounded-[12px] border-[color-mix(in_srgb,var(--fg-primary)_5%,transparent)] shadow-[0_1px_3px_color-mix(in_srgb,var(--fg-primary)_3%,transparent)] max-[700px]:mx-1 max-[700px]:mb-1 max-[700px]:h-[calc(100%_-_4px)]",
  root,
} as const;

export default styles;
