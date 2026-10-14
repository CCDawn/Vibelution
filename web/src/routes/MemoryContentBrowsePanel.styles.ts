const styles = {
  rail: "flex h-full min-h-0 min-w-0 flex-col gap-3 px-2 pb-2 pt-3",
  reader: "flex h-full min-h-0 min-w-0 flex-col overflow-hidden",
  readerToolbar: "flex min-h-12 shrink-0 min-w-0 items-center justify-between gap-3 px-5 py-2 text-vui-micro-13 [&>strong]:min-w-0 [&>strong]:truncate [&>strong]:font-medium max-md:[&_button]:!min-h-11",
  readerScroll: "min-h-0 min-w-0 flex-1 overflow-auto overscroll-contain px-6 pb-6 pt-3 max-md:px-4",
  cardActive: "aria-pressed:!bg-[var(--vui-selection-bg)]",
  mobileReading: "max-md:[&>[data-vui=split-sidebar]]:!hidden",
  mobileListing: "max-md:[&>[data-vui=split-main]]:!hidden max-md:[&>[data-vui=split-sidebar]]:!w-full max-md:[&>[data-vui=split-sidebar]]:!max-w-none max-md:[&>[data-vui=split-sidebar]]:!basis-full max-md:[&>[data-vui=split-sidebar]]:!min-w-0",
  backRow:
    "backRow flex min-w-0 items-center gap-2",
  body:
    "body min-w-0 whitespace-pre-wrap break-words text-vui-sm leading-7 text-vui-fg-secondary",
  card:
    "card !grid !min-h-12 min-w-0 cursor-pointer gap-1 !rounded-[var(--radius-control)] !border-0 !bg-transparent !px-3 !py-2.5 !shadow-none text-left hover:!bg-vui-surface-row-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-[var(--vui-control-focus-ring)]",
  cardGrid:
    "cardGrid grid w-full min-w-0 content-start gap-1",
  cardMeta:
    "cardMeta text-vui-2xs text-vui-fg-tertiary",
  cardTitle:
    "cardTitle min-w-0 break-words text-vui-micro-13 font-medium leading-5 text-vui-fg-primary",
  entryCard:
    "entryCard min-w-0 !grid gap-3 self-start !rounded-none !border-0 !border-b !border-vui-border-subtle !bg-transparent !px-0 !py-5 !shadow-none data-[active=true]:!bg-[var(--vui-selection-bg)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--vui-control-focus-ring)]",
  entryList:
    "entryList grid min-w-0 content-start gap-0",
  entryTitle:
    "entryTitle min-w-0 break-words text-vui-md font-medium leading-6 text-vui-fg-primary",
  fieldLabel:
    "fieldLabel min-w-0 text-vui-2xs font-medium text-vui-fg-tertiary",
  fieldList:
    "fieldList grid min-w-0 content-start gap-3",
  fieldValue:
    "fieldValue min-w-0 whitespace-pre-wrap break-words text-vui-sm leading-7 text-vui-fg-secondary",
  group:
    "group grid min-w-0 content-start gap-2 [&_[data-vui=section-header]]:px-3 [&_h3]:text-vui-2xs [&_h3]:font-medium",
  list:
    "list grid min-w-0 gap-1 pl-4 text-vui-sm leading-7 text-vui-fg-secondary",
  root: "memoryContentWorkspace h-full min-h-0 min-w-0 flex-1 !gap-0 overflow-hidden max-md:[&>[role=separator]]:!hidden",
  scroll:
    "scroll grid min-h-0 min-w-0 flex-1 content-start gap-4 overflow-auto overscroll-contain",
  searchBox: "searchBox mx-1 flex min-h-9 min-w-0 shrink-0 items-center gap-2 rounded-[var(--radius-control)] border border-vui-border-subtle bg-vui-surface-panel px-2 text-vui-fg-tertiary [&_input]:min-w-0 [&_input]:w-full [&_input]:!border-0 [&_input]:!bg-transparent [&_input]:!shadow-none [&_input]:!outline-none max-md:min-h-11",
  skeletonCard:
    "skeletonCard grid min-h-12 gap-2 self-start !border-0 !bg-transparent p-3 !shadow-none",
} as const;

export default styles;
