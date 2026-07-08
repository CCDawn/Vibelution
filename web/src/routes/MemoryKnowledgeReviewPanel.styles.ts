const styles = {
  bulkActionBar:
    "bulkActionBar min-w-0 flex flex-wrap items-center gap-1.5 [&>button]:w-fit [&>button]:max-w-full",
  countPill:
    "countPill min-w-0 inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-1.5 rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 text-[var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-secondary)]",
  detailActionButton:
    "detailActionButton min-w-0 inline-flex min-h-[var(--vui-control-height-sm)] w-fit max-w-full items-center justify-center gap-1.5 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 py-1 text-[var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)] hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] disabled:cursor-default disabled:opacity-55 [&>span]:truncate",
  emptyDetail:
    "emptyDetail min-w-0 grid min-h-[96px] content-center gap-1.5 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  inlineCheck:
    "inlineCheck min-w-0",
  knowledgeFormGrid:
    "knowledgeFormGrid min-w-0 grid gap-1 grid-cols-[repeat(auto-fit,minmax(min(100%,11rem),1fr))] text-[var(--vui-font-xs)] text-[var(--fg-secondary)] [&_label]:min-w-0 [&_input]:min-h-[var(--vui-control-height-sm)] [&_select]:min-h-[var(--vui-control-height-sm)] [&_textarea]:min-h-20 [&_input]:w-full [&_select]:w-full [&_textarea]:w-full [&_textarea]:max-w-full",
  knowledgeProposalList:
    "knowledgeProposalList min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto",
  knowledgeRow:
    "knowledgeRow min-w-0 grid gap-1.5 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-2 [&>strong]:min-w-0 [&>strong]:truncate [&>span]:min-w-0 [&>span]:line-clamp-2 [&>small]:min-w-0 [&>small]:truncate",
  managementHeader:
    "managementHeader min-w-0 flex flex-wrap items-center justify-between gap-1.5 [&>div]:min-w-0 [&_h2]:truncate",
  managementPanel:
    "managementPanel min-w-0 grid min-h-0 content-start gap-1.5 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-2",
  panelEyebrow:
    "panelEyebrow min-w-0 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  primaryActionButton:
    "primaryActionButton min-w-0 inline-flex min-h-[var(--vui-control-height-sm)] w-fit max-w-full items-center justify-center gap-1.5 rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-surface-row))] px-2 py-1 text-[var(--vui-font-xs)] font-semibold leading-tight text-[var(--accent-cool)] hover:border-[var(--border-strong)] hover:bg-[var(--vui-control-muted-hover)] disabled:cursor-default disabled:opacity-55 [&>span]:truncate",
  queueToolbar:
    "queueToolbar min-w-0 !grid min-h-0 content-start justify-start gap-1.5 overflow-hidden grid-cols-[repeat(auto-fit,minmax(min(100%,11rem),max-content))] max-[620px]:grid-cols-[1fr] [&_label]:min-w-0",
  wideField:
    "wideField min-w-0 grid gap-1 text-[var(--vui-font-xs)] text-[var(--fg-secondary)] [&_input]:min-h-[var(--vui-control-height-sm)] [&_select]:min-h-[var(--vui-control-height-sm)] [&_textarea]:min-h-20 [&_input]:w-full [&_select]:w-full [&_textarea]:w-full [&_textarea]:max-w-full",
} as const;

export default styles;
