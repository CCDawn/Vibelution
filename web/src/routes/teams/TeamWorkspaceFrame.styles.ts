export default {
  panel: "flex h-full min-h-0 min-w-0 flex-1 flex-col gap-0 overflow-hidden",
  contentPanel: "[--shell-surface:var(--vui-surface-chat)] [--vui-surface-panel:var(--vui-surface-chat)] [--vui-surface-workspace:var(--vui-surface-chat)]",
  railPanel: "!rounded-none !border-0",
  header: "h-11 shrink-0 items-center! border-b border-[var(--vui-border-subtle)] px-2 py-0 [&>div:first-child]:shrink-0 [&>div:last-child]:overflow-x-auto [&>div:last-child]:justify-start [&_h2]:whitespace-nowrap [&_h2]:font-medium [&_h2]:leading-6 [&_h2]:[font-size:var(--vui-font-sm)]",
  body: "flex min-h-0 min-w-0 flex-1 flex-col p-2",
  bodyScroll: "overflow-auto",
  bodyFixed: "overflow-hidden !p-0",
  barePane: "!border-0 !rounded-none !bg-transparent !p-0",
  page: "[--shell-surface:var(--vui-surface-rail)] !p-1",
  workspace: "[&>[data-vui=split-main]]:mx-1",
} as const;
