const styles: Record<string, string> = {
  artifactDialog:
    "vui-routes-chat-artifact-dialog min-w-0 w-[min(820px,calc(100vw_-_32px))] max-h-[min(760px,calc(100dvh_-_40px))]",
  body:
    "min-w-0 grid max-h-[min(620px,calc(100dvh_-_220px))] content-start gap-3 overflow-auto pr-1 [scrollbar-gutter:stable]",
  previewBody:
    "min-w-0 min-h-0 grid h-[min(520px,calc(100dvh_-_260px))] grid-rows-[minmax(0,1fr)] overflow-hidden",
  backButton:
    "max-[600px]:min-h-11",
  task:
    "min-w-0 grid gap-2 border-b border-[var(--vui-border-subtle)] pb-3 last:border-b-0 last:pb-0",
  taskHeading:
    "min-w-0 flex flex-wrap items-baseline justify-between gap-x-2 gap-y-0.5 text-[var(--fg-primary)] [font-size:var(--vui-font-sm)] font-semibold",
  taskId:
    "min-w-0 break-all font-mono [font-size:var(--vui-font-2xs)] font-normal text-[var(--fg-tertiary)]",
  state:
    "m-0 min-w-0 py-1 [font-size:var(--vui-font-xs)] leading-snug text-[var(--fg-tertiary)]",
  fileList: "min-w-0 grid gap-1",
  fileRow:
    "min-w-0 grid grid-cols-[auto_minmax(0,1fr)] items-baseline gap-x-2 rounded-[var(--radius-control)] px-2 py-1.5 text-[var(--fg-secondary)] hover:bg-[var(--vui-surface-row-hover)]",
  fileButton:
    "w-full max-w-full !h-auto min-w-0 justify-start rounded-[var(--radius-control)] px-1.5 py-1 text-left whitespace-normal",
  fileStatus:
    "min-w-[4.5rem] rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-1.5 py-0.5 text-center [font-size:var(--vui-font-2xs)] leading-tight text-[var(--fg-tertiary)]",
  filePath:
    "min-w-0 break-all font-mono [font-size:var(--vui-font-xs)] leading-snug text-[var(--fg-secondary)]",
  note:
    "m-0 min-w-0 [font-size:var(--vui-font-xs)] leading-snug text-[var(--fg-tertiary)]",
};

export default styles;
