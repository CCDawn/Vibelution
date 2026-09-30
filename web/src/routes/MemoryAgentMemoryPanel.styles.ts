import { vuiFlatPanelClass, vuiRailFillClass, vuiWorkspaceFillClass } from "../design/vuiSurfaceRecipes";

const buttonContent = "[&_[data-slot=vui-button-content]]:w-full [&_[data-slot=vui-button-label]]:flex [&_[data-slot=vui-button-label]]:w-full [&_[data-slot=vui-button-label]]:min-w-0 [&_[data-slot=vui-button-label]]:items-center [&_[data-slot=vui-button-label]]:gap-3 [&_[data-slot=vui-button-label]]:whitespace-normal";
const muted = "text-[var(--fg-tertiary)]";
const avatar = "flex size-9 shrink-0 items-center justify-center rounded-xl bg-vui-surface-inset text-xs font-semibold text-[var(--accent-cool)]";
const styles = {
  agentMemoryWorkspace: "agentMemoryWorkspace flex h-full min-h-0 min-w-0 flex-1 overflow-hidden",
  workspace: `workspace h-full min-h-0 w-full overflow-hidden !gap-0 ${vuiWorkspaceFillClass} max-md:[&>[data-vui=split-sidebar]]:!hidden max-md:[&>[role=separator]]:!hidden`,
  agentRail: `flex h-full min-h-0 flex-col px-4 pb-4 pt-6 ${vuiRailFillClass}`,
  railHeading: `mb-4 px-2 text-xs font-semibold ${muted}`,
  searchBox: "searchBox focus-within:ring-2 focus-within:ring-[var(--accent-cool)] mb-6 flex min-w-0 items-center gap-2 rounded-lg border border-vui-border-subtle bg-vui-surface-panel px-3 py-2 text-[var(--fg-tertiary)] [&_input]:min-w-0 [&_input]:w-full [&_input]:!border-0 [&_input]:!bg-transparent [&_input]:!shadow-none [&_input]:!outline-none [&_input]:text-sm",
  railScroll: "min-h-0 flex-1 overflow-y-auto",
  groupHeading: `mb-3 flex items-center gap-2 px-2 text-xs ${muted}`,
  agentList: "grid gap-1.5",
  agentRow: `!h-auto !min-h-16 !w-full !justify-start !rounded-xl !border-0 !px-3 !py-3 text-left ${buttonContent}`,
  agentRowActive: "!bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-surface-row))]",
  avatar,
  avatarLarge: `${avatar} !size-11 !text-sm`,
  agentIdentity: "flex min-w-0 flex-1 flex-col gap-1.5 [&_strong]:truncate [&_strong]:text-sm [&_strong]:font-semibold [&_small]:text-xs [&_small]:font-normal [&_small]:text-[var(--fg-tertiary)]",
  selectedDot: "size-1.5 shrink-0 rounded-full bg-[var(--accent-cool)]",
  groupToggle: `!mt-5 !h-auto !w-full !justify-start !px-2 !py-3 !border-0 !bg-transparent !shadow-none text-xs ${muted} ${buttonContent} [&_[data-slot=vui-button-label]>span:last-child]:ml-auto`,
  railNote: `mt-5 flex items-start gap-2 border-t border-vui-border-subtle pt-4 text-xs leading-relaxed ${muted}`,
  emptyState: `emptyState p-3 text-sm leading-relaxed ${muted}`,
  reader: "flex h-full min-h-0 min-w-0 flex-col",
  readerTop: `flex min-h-12 shrink-0 items-center justify-between gap-3 border-b border-vui-border-subtle px-6 text-xs ${muted}`,
  breadcrumb: "hidden min-w-0 items-center gap-2 truncate md:flex",
  privateBadge: "flex shrink-0 items-center gap-1.5",
  mobileSwitch: "!h-auto !px-0 !py-2 md:!hidden [&_[data-slot=vui-button-label]]:flex [&_[data-slot=vui-button-label]]:items-center [&_[data-slot=vui-button-label]]:gap-2",
  // Tailwind translate already centers this dialog; avoid the legacy motion transform applying it twice.
  mobileDialog: "!transform-none !h-[min(80dvh,640px)] !p-0 overflow-hidden",
  readingScroll: "min-h-0 flex-1 overflow-y-auto",
  readingContent: "mx-auto w-full max-w-[1000px] px-5 py-7 lg:px-11 lg:py-9",
  agentTitle: "mb-8 flex min-w-0 items-center gap-3.5 [&>div]:min-w-0 [&_h2]:break-words [&_h2]:text-xl [&_h2]:font-semibold [&_p]:mt-2 [&_p]:text-xs [&_p]:text-[var(--fg-tertiary)]",
  collectionHeading: "mb-4 flex items-center gap-2 text-sm font-medium [&>span:last-child]:text-xs [&>span:last-child]:text-[var(--fg-tertiary)]",
  documents: "grid min-w-0 gap-5",
  document: `${vuiFlatPanelClass} min-w-0 !rounded-xl px-5 pt-6 lg:px-8 lg:pt-7`,
  documentKicker: `flex flex-wrap items-center gap-2 text-xs ${muted} [&>span:last-child]:ml-auto`,
  documentTitle: "mt-5 mb-5 break-words text-lg font-semibold leading-relaxed",
  documentBody: "min-w-0 space-y-5 border-t border-vui-border-subtle pt-5 [overflow-wrap:anywhere] [&_p]:!leading-8 [&_p]:!text-[var(--fg-secondary)] [&_dl]:!gap-5 [&_dt]:!text-sm [&_dt]:!text-[var(--fg-primary)] [&_dd]:!mt-2 [&_dd]:!leading-8 [&_dd]:!text-[var(--fg-secondary)] [&_ul]:list-disc [&_li]:leading-8",
  truncated: "mt-4 text-sm text-[var(--fg-tertiary)]",
  documentFooter: `mt-6 flex min-w-0 items-center justify-between gap-3 border-t border-vui-border-subtle py-4 text-xs ${muted} [&>span:first-child]:min-w-0 [&>span:first-child]:truncate [&>span:last-child]:shrink-0`,
  readingNote: `mt-5 flex items-start gap-2 text-xs leading-relaxed ${muted} [&_svg]:shrink-0`,
} as const;
export default styles;
