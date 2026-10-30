const root =
  "grid h-full grid-rows-[auto_minmax(0,1fr)] min-h-0 min-w-0 overflow-hidden bg-vui-surface-workspace text-vui-fg-primary";

const styles = {
  workspace: "!gap-0",
  columns: "grid-cols-[224px_minmax(0,1fr)] max-[1100px]:grid-cols-[208px_minmax(0,1fr)] max-[700px]:grid-cols-1 [&>[data-vui=split-sidebar]]:max-[700px]:hidden",
  main: "h-full min-h-0 min-w-0 overflow-hidden !rounded-none !border-0 !bg-vui-surface-panel !shadow-none",
  navigation:"h-full border-r border-vui-border-subtle max-[700px]:hidden",
  mobileNavigation:"h-[min(720px,70dvh)] min-h-0 overflow-hidden",
  root,
} as const;

export default styles;
