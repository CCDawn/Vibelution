const root =
  "grid h-full grid-rows-[auto_minmax(0,1fr)] min-h-0 min-w-0 overflow-hidden bg-vui-surface-rail text-vui-fg-primary";

const styles = {
  workspace: "h-full w-full !gap-0 [&>[data-vui=split-main]]:overflow-hidden",
  columns: "grid-cols-[224px_minmax(0,1fr)] max-[1100px]:grid-cols-[208px_minmax(0,1fr)] max-[700px]:grid-cols-1 [&>[data-vui=split-sidebar]]:max-[700px]:hidden",
  navigation:"h-full max-[700px]:hidden",
  mobileNavigation:"h-[min(720px,70dvh)] min-h-0 overflow-hidden",
  root,
} as const;

export default styles;
