const styles = {
  agentSessionTab:
    "vui-routes-chatcodingroute agentSessionTab -mb-px min-w-0 inline-flex h-8 w-fit max-w-[14rem] shrink-0 items-end rounded-t-[var(--radius-control)] rounded-b-none",
  agentSessionTabActive:
    "vui-routes-chatcodingroute agentSessionTabActive min-w-0",
  agentSessionTabChild:
    "vui-routes-chatcodingroute agentSessionTabChild min-w-0",
  agentSessionTabCli:
    "vui-routes-chatcodingroute agentSessionTabCli min-w-0",
  agentSessionTabClosable:
    "vui-routes-chatcodingroute agentSessionTabClosable min-w-0 gap-0.5",
  agentSessionTabCloseButton:
    "vui-routes-chatcodingroute agentSessionTabCloseButton h-7 min-h-7 w-7 min-w-7 rounded-t-[var(--radius-control)] rounded-b-none border-transparent bg-transparent px-0 text-[var(--fg-tertiary)] hover:border-[var(--vui-border-subtle)] hover:bg-[var(--vui-control-muted-hover)] hover:text-[var(--fg-primary)]",
  agentSessionTabContextTarget:
    "vui-routes-chatcodingroute agentSessionTabContextTarget min-w-0",
  agentSessionTabCopy:
    "vui-routes-chatcodingroute agentSessionTabCopy min-w-0 flex flex-1 flex-col items-start gap-0.5 text-left [font-size:var(--vui-font-sm)] leading-tight text-[var(--fg-secondary)]",
  agentSessionTabCopyCompact:
    "vui-routes-chatcodingroute agentSessionTabCopyCompact min-w-0 [font-size:var(--vui-font-sm)] leading-tight text-[var(--fg-secondary)]",
  agentSessionTabEditActions:
    "vui-routes-chatcodingroute agentSessionTabEditActions min-w-0 flex items-center gap-1",
  agentSessionTabEditButton:
    "vui-routes-chatcodingroute agentSessionTabEditButton h-7 min-h-7 w-7 min-w-7 rounded-[var(--radius-control)] px-0",
  agentSessionTabEditing:
    "vui-routes-chatcodingroute agentSessionTabEditing min-w-[12rem] max-w-[18rem] gap-1.5 rounded-t-[var(--radius-control)] rounded-b-none border border-b-transparent border-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_8%,var(--vui-surface-row))] px-2 py-1",
  agentSessionTabGroup:
    "vui-routes-chatcodingroute agentSessionTabGroup min-w-0 flex w-full flex-1 flex-nowrap items-end gap-0 overflow-x-auto overflow-y-hidden pr-2 [scrollbar-width:thin]",
  agentSessionTabIcon:
    "vui-routes-chatcodingroute agentSessionTabIcon inline-grid h-4 w-4 shrink-0 place-items-center text-[var(--fg-tertiary)]",
  agentSessionTabKicker:
    "vui-routes-chatcodingroute agentSessionTabKicker min-w-0 text-[10px] font-semibold leading-none text-[var(--fg-tertiary)]",
  agentSessionTabMainAction:
    "vui-routes-chatcodingroute agentSessionTabMainAction h-8 min-h-8 min-w-0 max-w-full rounded-t-[var(--radius-control)] rounded-b-none border border-[var(--vui-border-subtle)] bg-[color-mix(in_srgb,var(--vui-surface-row)_78%,transparent)] px-3 text-[var(--fg-secondary)] shadow-none hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] [&_[data-slot=vui-button-content]]:max-w-full [&_[data-slot=vui-button-content]]:gap-1.5 [&_[data-slot=vui-button-label]]:flex [&_[data-slot=vui-button-label]]:min-w-0 [&_[data-slot=vui-button-label]]:items-center [&_[data-slot=vui-button-label]]:gap-1.5 [&_[data-slot=vui-button-label]]:truncate",
  agentSessionTabMainActionActive:
    "vui-routes-chatcodingroute agentSessionTabMainActionActive -mb-px border-b-transparent border-[color-mix(in_srgb,var(--accent-cool)_38%,transparent)] bg-[var(--vui-surface-panel)] text-[var(--fg-primary)]",
  agentSessionTabMainActionContextTarget:
    "vui-routes-chatcodingroute agentSessionTabMainActionContextTarget border-[color-mix(in_srgb,var(--accent-cool)_30%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_7%,var(--vui-surface-row))]",
  agentSessionTabMeta:
    "vui-routes-chatcodingroute agentSessionTabMeta min-w-0 max-w-full text-left [font-size:var(--vui-font-xs)] leading-none text-[var(--fg-tertiary)]",
  agentSessionTabRoot:
    "vui-routes-chatcodingroute agentSessionTabRoot min-w-0",
  agentSessionTabStatusDot:
    "vui-routes-chatcodingroute agentSessionTabStatusDot h-2 w-2 shrink-0 rounded-full border border-white/60 shadow-[0_0_0_1px_color-mix(in_srgb,currentColor_22%,transparent)]",
  agentSessionTabStatusDotDone:
    "vui-routes-chatcodingroute agentSessionTabStatusDotDone bg-[var(--accent-cool)] text-[var(--accent-cool)]",
  agentSessionTabStatusDotError:
    "vui-routes-chatcodingroute agentSessionTabStatusDotError bg-[var(--state-error)] text-[var(--state-error)]",
  agentSessionTabStatusDotRunning:
    "vui-routes-chatcodingroute agentSessionTabStatusDotRunning bg-[var(--state-success)] text-[var(--state-success)]",
  agentSessionTabTitle:
    "vui-routes-chatcodingroute agentSessionTabTitle min-w-0 max-w-[9.5rem] truncate text-left [font-size:var(--vui-font-sm)] font-semibold leading-none text-[var(--fg-primary)]",
  agentSessionTabTitleInput:
    "vui-routes-chatcodingroute agentSessionTabTitleInput min-w-0 grid gap-1 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)] [&_input]:min-h-7 [&_select]:min-h-7 [&_textarea]:min-h-20 [&_input]:w-full [&_select]:w-full [&_textarea]:w-full [font-size:var(--vui-font-sm)] font-semibold leading-tight text-[var(--fg-primary)]",
} as const;

export default styles;
