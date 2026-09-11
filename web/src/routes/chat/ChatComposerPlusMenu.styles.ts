const styles: Record<string, string> = {
  popoverContent: "vui-routes-chatcomposerplusmenu popoverContent !w-80 !max-w-[calc(100vw-1.5rem)] !p-0",
  menu: "vui-routes-chatcomposerplusmenu menu grid w-full content-start gap-0 p-1.5 max-h-[min(70vh,32rem)] overflow-y-auto overscroll-contain outline-none",
  section: "vui-routes-chatcomposerplusmenu section grid gap-0.5 border-t border-[var(--vui-border-subtle)] px-0 pt-1.5 first:border-t-0 first:pt-0",
  sectionTitle: "vui-routes-chatcomposerplusmenu sectionTitle px-2.5 pb-0.5 pt-1 text-[11px] font-semibold tracking-wide text-[var(--fg-tertiary)]",
  menuItem: "vui-routes-chatcomposerplusmenu menuItem !flex min-h-9 w-full items-center !justify-start gap-2.5 rounded-[calc(var(--radius-control)-2px)] px-2.5 py-1.5 text-left text-[var(--fg-secondary)] hover:bg-[color-mix(in_srgb,var(--accent-cool)_10%,transparent)] hover:text-[var(--fg-primary)]",
  menuItemChecked: "vui-routes-chatcomposerplusmenu menuItemChecked text-[var(--fg-primary)]",
  itemIcon: "vui-routes-chatcomposerplusmenu itemIcon inline-grid size-5 shrink-0 place-items-center text-[var(--fg-tertiary)]",
  itemLabel: "vui-routes-chatcomposerplusmenu itemLabel min-w-0 flex-1 truncate text-left text-sm font-medium",
  itemCopy: "vui-routes-chatcomposerplusmenu itemCopy grid min-w-0 flex-1 gap-0.5 text-left",
  itemTitle: "vui-routes-chatcomposerplusmenu itemTitle truncate text-sm font-medium",
  itemHint: "vui-routes-chatcomposerplusmenu itemHint truncate text-[11px] font-normal text-[var(--fg-tertiary)]",
  itemCheck: "vui-routes-chatcomposerplusmenu itemCheck ml-auto inline-grid size-4 shrink-0 place-items-center text-[var(--accent-cool-2)]",
  hiddenInput: "vui-routes-chatcomposerplusmenu hiddenInput sr-only",
  referenceBody: "vui-routes-chatcomposerplusmenu referenceBody grid min-h-0 gap-3 overflow-hidden py-1",
  referenceList: "vui-routes-chatcomposerplusmenu referenceList grid max-h-[min(52vh,24rem)] gap-1 overflow-y-auto",
  referenceOption: "vui-routes-chatcomposerplusmenu referenceOption !grid min-h-11 w-full !justify-start gap-0.5 px-3 py-2 text-left",
  referenceTitle: "vui-routes-chatcomposerplusmenu referenceTitle truncate text-sm",
  referenceMeta: "vui-routes-chatcomposerplusmenu referenceMeta truncate text-xs text-[var(--fg-tertiary)]",
  referenceEmpty: "vui-routes-chatcomposerplusmenu referenceEmpty px-3 py-5 text-center text-sm text-[var(--fg-tertiary)]",
};

export default styles;
