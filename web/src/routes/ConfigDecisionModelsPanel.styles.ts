const styles = {
  section: "vui-routes-configdecisionmodelspanel section !gap-0",
  header: "vui-routes-configdecisionmodelspanel header min-h-16 items-center border-b border-vui-border-subtle px-4 py-3 md:px-7",
  editorHeader: "vui-routes-configdecisionmodelspanel editorHeader !grid-cols-[auto_minmax(0,1fr)] [&>div:first-child]:col-start-2 [&>div:first-child]:row-start-1 [&>div:last-child]:col-start-1 [&>div:last-child]:row-start-1 [&>div:last-child]:justify-self-start",
  content: "vui-routes-configdecisionmodelspanel content grid min-w-0 gap-5 px-4 py-5 md:px-7",
  hold:
    "vui-routes-configdecisionmodelspanel hold m-0 text-vui-xs text-vui-fg-secondary",
  actions: "vui-routes-configdecisionmodelspanel actions flex min-w-0 flex-wrap items-center gap-2",
  field: "vui-routes-configdecisionmodelspanel field grid min-w-0 content-start gap-2 text-vui-xs text-vui-fg-secondary [&_input]:min-h-10",
  narrow: "vui-routes-configdecisionmodelspanel narrow grid max-w-md min-w-0 content-start gap-2 text-vui-xs text-vui-fg-secondary [&_input]:min-h-10",
  list: "vui-routes-configdecisionmodelspanel list m-0 grid min-w-0 list-none p-0",
  row: "vui-routes-configdecisionmodelspanel row min-w-0 border-b border-vui-border-subtle",
  rowButton: "vui-routes-configdecisionmodelspanel rowButton !flex !h-auto !min-h-[76px] !w-full !justify-start gap-3 !rounded-none !px-1 !py-3 text-left",
  rowIcon: "vui-routes-configdecisionmodelspanel rowIcon shrink-0 text-vui-fg-tertiary",
  summary: "vui-routes-configdecisionmodelspanel summary grid min-w-0 flex-1 gap-1",
  summaryHeading: "vui-routes-configdecisionmodelspanel summaryHeading flex min-w-0 flex-wrap items-center gap-2",
  modelId: "vui-routes-configdecisionmodelspanel modelId m-0 break-all text-vui-xs text-vui-fg-tertiary",
  editor: "vui-routes-configdecisionmodelspanel editor grid min-w-0 max-w-3xl content-start gap-6 px-4 py-5 md:px-7",
  formGrid: "vui-routes-configdecisionmodelspanel formGrid grid min-w-0 gap-5 sm:grid-cols-2",
  cardTitle: "vui-routes-configdecisionmodelspanel cardTitle min-w-0 break-all text-vui-sm font-medium text-vui-fg-primary",
  note: "vui-routes-configdecisionmodelspanel note m-0 text-vui-xs leading-relaxed text-vui-fg-tertiary",
  probe: "vui-routes-configdecisionmodelspanel probe m-0 break-words text-vui-xs text-vui-fg-primary",
} as const;

export default styles;
