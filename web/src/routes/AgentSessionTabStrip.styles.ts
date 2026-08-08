const styles = {
  // Card chrome lives on the outer tab shell so close control sits inside the same surface.
  agentSessionTab:
    "vui-routes-chatcodingroute agentSessionTab -mb-px min-w-0 inline-flex h-9 w-fit max-w-[16rem] shrink-0 items-center gap-0 rounded-t-[var(--radius-control)] rounded-b-none border border-transparent bg-transparent pr-0.5 text-[var(--fg-secondary)] hover:border-[var(--vui-border-subtle)] hover:bg-[var(--vui-control-muted-hover)] hover:text-[var(--vui-control-hover-fg)]",
  agentSessionTabActive:
    "vui-routes-chatcodingroute agentSessionTabActive min-w-0 z-[1] border-[color-mix(in_srgb,var(--accent-cool)_42%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--accent-cool)_9%,var(--vui-surface-panel))] data-[selected=true]:!bg-[color-mix(in_srgb,var(--accent-cool)_9%,var(--vui-surface-panel))] text-[var(--fg-primary)] opacity-100 hover:border-[color-mix(in_srgb,var(--accent-cool)_42%,var(--vui-border-subtle))] hover:bg-[color-mix(in_srgb,var(--accent-cool)_9%,var(--vui-surface-panel))] hover:text-[var(--fg-primary)]",
  agentSessionTabChild:
    "vui-routes-chatcodingroute agentSessionTabChild min-w-0",
  agentSessionTabCli:
    "vui-routes-chatcodingroute agentSessionTabCli min-w-0",
  agentSessionTabClosable:
    "vui-routes-chatcodingroute agentSessionTabClosable min-w-0",
  // Override VButton secondary border so the close control is icon-only (no chip outline).
  agentSessionTabCloseButton:
    "vui-routes-chatcodingroute agentSessionTabCloseButton h-6 min-h-6 w-6 min-w-6 shrink-0 rounded-[var(--radius-control)] !border-0 border-transparent bg-transparent px-0 text-[var(--fg-tertiary)] shadow-none hover:!border-transparent hover:bg-[var(--vui-control-muted-hover)] hover:text-[var(--fg-primary)] hover:shadow-none",
  agentSessionTabCreateButton:
    "vui-routes-chatcodingroute agentSessionTabCreateButton h-8 min-h-8 w-8 min-w-8 shrink-0 rounded-[var(--radius-control)] !border-0 border-transparent bg-transparent px-0 text-[var(--fg-secondary)] shadow-none hover:!border-transparent hover:bg-[var(--vui-control-muted-hover)] hover:text-[var(--fg-primary)] hover:shadow-none",
  agentSessionTabContextTarget:
    "vui-routes-chatcodingroute agentSessionTabContextTarget min-w-0 border-[color-mix(in_srgb,var(--accent-cool)_40%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-surface-row))] opacity-100",
  agentSessionTabCopy:
    "vui-routes-chatcodingroute agentSessionTabCopy min-w-0 flex flex-1 flex-col items-start gap-0.5 text-left [font-size:var(--vui-font-sm)] leading-tight text-[var(--fg-secondary)]",
  agentSessionTabCopyCompact:
    "vui-routes-chatcodingroute agentSessionTabCopyCompact min-w-0 [font-size:var(--vui-font-sm)] leading-tight text-[var(--fg-secondary)]",
  agentSessionTabEditActions:
    "vui-routes-chatcodingroute agentSessionTabEditActions flex shrink-0 items-center gap-0.5",
  agentSessionTabEditButton:
    "vui-routes-chatcodingroute agentSessionTabEditButton h-6 min-h-6 w-6 min-w-6 shrink-0 rounded-[var(--radius-control)] !border-0 border-transparent bg-transparent px-0 text-[var(--fg-tertiary)] shadow-none hover:!border-transparent hover:bg-[var(--vui-control-muted-hover)] hover:text-[var(--fg-primary)] hover:shadow-none",
  // Single-row rename chrome: matches normal tab height, no stacked kicker.
  agentSessionTabEditing:
    "vui-routes-chatcodingroute agentSessionTabEditing h-9 min-w-[11rem] max-w-[16rem] gap-1 rounded-t-[var(--radius-control)] rounded-b-none border border-b-transparent border-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_8%,var(--vui-surface-row))] px-1.5 py-0 opacity-100",
  agentSessionTabGroup:
    "vui-routes-chatcodingroute agentSessionTabGroup min-w-0 flex w-fit flex-none flex-nowrap items-end gap-0.5",
  agentSessionTabRail:
    "vui-routes-chatcodingroute agentSessionTabRail min-w-0 flex w-fit max-w-full flex-[0_1_auto] flex-nowrap items-end gap-0.5 overflow-x-auto overflow-y-hidden pr-2 [scrollbar-width:thin]",
  agentSessionTabIcon:
    "vui-routes-chatcodingroute agentSessionTabIcon inline-grid h-4 w-4 shrink-0 place-items-center text-[var(--fg-tertiary)]",
  agentSessionTabIconActive:
    "vui-routes-chatcodingroute agentSessionTabIconActive text-[var(--accent-cool)]",
  agentSessionTabKicker:
    "vui-routes-chatcodingroute agentSessionTabKicker min-w-0 text-[10px] font-semibold leading-none text-[var(--fg-tertiary)]",
  // Content hit target only — selection chrome is on the outer agentSessionTab card.
  // Fixed row: [icon] [title flex] [status slot] — status always occupies the same 14px cell.
  agentSessionTabMainAction: `vui-routes-chatcodingroute agentSessionTabMainAction !inline-flex !h-9 !min-h-9 min-w-0 max-w-full flex-1 items-center !gap-1.5 !rounded-none !border-0 !bg-transparent !px-2 !py-0 !text-inherit !shadow-none hover:!border-transparent hover:!bg-transparent hover:!text-inherit`,
  agentSessionTabMainActionActive: `vui-routes-chatcodingroute agentSessionTabMainActionActive !text-[var(--fg-primary)] !shadow-none`,
  agentSessionTabMainActionContextTarget:
    "vui-routes-chatcodingroute agentSessionTabMainActionContextTarget",
  agentSessionTabMeta:
    "vui-routes-chatcodingroute agentSessionTabMeta min-w-0 max-w-full text-left [font-size:var(--vui-font-xs)] leading-none text-[var(--fg-tertiary)]",
  agentSessionTabRoot:
    "vui-routes-chatcodingroute agentSessionTabRoot min-w-0",
  agentSessionTabTitleBlock:
    "vui-routes-chatcodingroute agentSessionTabTitleBlock min-w-0 max-w-[11rem] flex-1 overflow-hidden",
  // Fixed status slot between title and close: keeps tab geometry stable with/without activity.
  agentSessionTabStatusSlot:
    "vui-routes-chatcodingroute agentSessionTabStatusSlot inline-grid h-3.5 w-3.5 shrink-0 place-items-center self-center",
  agentSessionTabStatus:
    "vui-routes-chatcodingroute agentSessionTabStatus inline-grid h-3.5 w-3.5 shrink-0 place-items-center",
  agentSessionTabStatusIndicator:
    "vui-routes-chatcodingroute agentSessionTabStatusIndicator inline-grid h-2.5 w-2.5 shrink-0 place-items-center",
  agentSessionTabStatusSpinner:
    "vui-routes-chatcodingroute agentSessionTabStatusSpinner animate-spin",
  agentSessionTabStatusRunning:
    "vui-routes-chatcodingroute agentSessionTabStatusRunning h-3 w-3 text-[var(--state-success)]",
  agentSessionTabStatusApproval:
    "vui-routes-chatcodingroute agentSessionTabStatusApproval h-3 w-3 text-[var(--state-warning)]",
  agentSessionTabStatusError:
    "vui-routes-chatcodingroute agentSessionTabStatusError h-2.5 w-2.5 rounded-full bg-[var(--state-error)]",
  agentSessionTabStatusCompleted:
    "vui-routes-chatcodingroute agentSessionTabStatusCompleted h-2.5 w-2.5 rounded-full bg-[var(--accent-cool)]",
  // Legacy class names kept so layout source tests that still mention dots do not hard-fail mid-migration.
  agentSessionTabStatusDot:
    "vui-routes-chatcodingroute agentSessionTabStatusDot h-2.5 w-2.5 shrink-0 rounded-full",
  agentSessionTabStatusDotIdle:
    "vui-routes-chatcodingroute agentSessionTabStatusDotIdle bg-[color-mix(in_srgb,var(--fg-tertiary)_55%,transparent)] text-[var(--fg-tertiary)]",
  agentSessionTabStatusDotError:
    "vui-routes-chatcodingroute agentSessionTabStatusDotError bg-[var(--state-error)] text-[var(--state-error)]",
  agentSessionTabStatusDotRunning:
    "vui-routes-chatcodingroute agentSessionTabStatusDotRunning bg-[var(--state-success)] text-[var(--state-success)]",
  agentSessionTabStatusDotApproval:
    "vui-routes-chatcodingroute agentSessionTabStatusDotApproval bg-[var(--state-warning)] text-[var(--state-warning)]",
  agentSessionTabTitle:
    "vui-routes-chatcodingroute agentSessionTabTitle block min-w-0 max-w-full truncate text-left [font-size:var(--vui-font-sm)] font-semibold leading-none text-[var(--fg-secondary)]",
  agentSessionTabTitleActive:
    "vui-routes-chatcodingroute agentSessionTabTitleActive !text-[var(--fg-primary)]",
  // Inline tab rename field: strip dense form chrome so it reads as a tab title, not a dialog.
  agentSessionTabTitleInput:
    "vui-routes-chatcodingroute agentSessionTabTitleInput min-w-0 flex-1 !h-7 !min-h-7 !w-[8.5rem] max-w-[10rem] !rounded-[var(--radius-control)] !border-0 !bg-transparent !px-1.5 !py-0 ![font-size:var(--vui-font-sm)] !font-semibold !leading-none !text-[var(--fg-primary)] !shadow-none placeholder:!font-normal placeholder:!text-[var(--fg-tertiary)] focus-visible:!outline-none focus-visible:!ring-1 focus-visible:!ring-[color-mix(in_srgb,var(--accent-cool)_55%,transparent)]",
} as const;

export default styles;
