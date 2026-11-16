const styles = {
  sessionHeader: "flex min-w-0 max-w-full items-center gap-1",
  // Card chrome lives on the outer tab shell so close control sits inside the same surface.
  agentSessionTab:
    "vui-routes-chatcodingroute agentSessionTab min-w-0 inline-flex h-7 w-fit max-w-[14rem] shrink-0 items-center gap-0 rounded-[6px] border-0 bg-transparent pr-0.5 text-[var(--fg-secondary)] hover:bg-[var(--vui-control-muted-hover)] hover:text-[var(--vui-control-hover-fg)]",
  agentSessionTabActive:
    "vui-routes-chatcodingroute agentSessionTabActive min-w-0 !bg-[color-mix(in_srgb,var(--accent-cool)_12%,var(--vui-surface-chat))] data-[selected=true]:!bg-[color-mix(in_srgb,var(--accent-cool)_12%,var(--vui-surface-chat))] !ring-1 !ring-[color-mix(in_srgb,var(--accent-cool)_55%,transparent)] text-[var(--fg-primary)] opacity-100 hover:text-[var(--fg-primary)]",
  agentSessionTabChild:
    "vui-routes-chatcodingroute agentSessionTabChild min-w-0",
  agentSessionTabCli:
    "vui-routes-chatcodingroute agentSessionTabCli min-w-0",
  agentSessionTabClosable:
    "vui-routes-chatcodingroute agentSessionTabClosable min-w-0",
  // Override VButton secondary border so the close control is icon-only (no chip outline).
  agentSessionTabCloseButton:
    "vui-routes-chatcodingroute agentSessionTabCloseButton h-6 min-h-6 w-6 min-w-6 shrink-0 rounded-[var(--radius-control)] !border-0 border-transparent bg-transparent !bg-none px-0 text-[var(--fg-tertiary)] shadow-none hover:!border-transparent hover:bg-[var(--vui-control-muted-hover)] hover:text-[var(--fg-primary)] hover:shadow-none",
  // Armed (two-stage confirm) close: same icon-only geometry, danger tone so the pending state reads instantly.
  agentSessionTabCloseButtonArmed:
    // Color tint lives in AgentSessionTabStrip.armed.css: tailwind does not
    // generate the important+color-mix arbitrary combo, and the plain variant
    // loses to the base tab utilities by stylesheet order.
    "vui-routes-chatcodingroute agentSessionTabCloseButtonArmed !border-0 px-0 shadow-none hover:!border-transparent hover:shadow-none",
  agentSessionTabCreateButton:
    "vui-routes-chatcodingroute agentSessionTabCreateButton h-8 min-h-8 w-8 min-w-8 shrink-0 rounded-[var(--radius-control)] !border-0 border-transparent bg-transparent !bg-none px-0 text-[var(--fg-secondary)] shadow-none hover:!border-transparent hover:bg-[var(--vui-control-muted-hover)] hover:text-[var(--fg-primary)] hover:shadow-none",
  agentSessionTabContextTarget:
    "vui-routes-chatcodingroute agentSessionTabContextTarget min-w-0 border-[color-mix(in_srgb,var(--accent-cool)_40%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-surface-row))] opacity-100",
  agentSessionTabCopy:
    "vui-routes-chatcodingroute agentSessionTabCopy min-w-0 flex flex-1 flex-col items-start gap-0.5 text-left [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-secondary)]",
  agentSessionTabCopyCompact:
    "vui-routes-chatcodingroute agentSessionTabCopyCompact min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-secondary)]",
  agentSessionTabEditActions:
    "vui-routes-chatcodingroute agentSessionTabEditActions flex shrink-0 items-center gap-0.5",
  agentSessionTabEditButton:
    "vui-routes-chatcodingroute agentSessionTabEditButton h-6 min-h-6 w-6 min-w-6 shrink-0 rounded-[var(--radius-control)] !border-0 border-transparent bg-transparent px-0 text-[var(--fg-tertiary)] shadow-none hover:!border-transparent hover:bg-[var(--vui-control-muted-hover)] hover:text-[var(--fg-primary)] hover:shadow-none",
  // Single-row rename chrome: matches normal tab height, no stacked kicker.
  agentSessionTabEditing:
    "vui-routes-chatcodingroute agentSessionTabEditing h-7 min-w-[11rem] max-w-[14rem] gap-1 rounded-[6px] border-0 !bg-[color-mix(in_srgb,var(--fg-primary)_6%,var(--vui-surface-chat))] px-1.5 py-0 opacity-100",
  agentSessionTabGroup:
    "vui-routes-chatcodingroute agentSessionTabGroup min-w-0 flex w-fit flex-none flex-nowrap items-center gap-0.5",
  agentSessionTabRail:
    "vui-routes-chatcodingroute agentSessionTabRail min-w-0 flex w-fit max-w-full flex-[0_1_auto] flex-nowrap items-center gap-0.5 overflow-x-auto overflow-y-hidden pr-2 [scrollbar-width:thin]",
  agentSessionTabIcon:
    "vui-routes-chatcodingroute agentSessionTabIcon inline-grid h-3.5 w-3.5 shrink-0 place-items-center text-[var(--fg-tertiary)]",
  agentSessionTabIconActive:
    "vui-routes-chatcodingroute agentSessionTabIconActive text-[var(--fg-secondary)]",
  agentSessionTabKicker:
    "vui-routes-chatcodingroute agentSessionTabKicker min-w-0 text-vui-micro-10 font-semibold leading-none text-[var(--fg-tertiary)]",
  // Content hit target only — selection chrome is on the outer agentSessionTab card.
  // Fixed row: [icon] [title flex] [status slot] — status always occupies the same 14px cell.
  agentSessionTabMainAction: `vui-routes-chatcodingroute agentSessionTabMainAction !inline-flex !h-7 !min-h-7 min-w-0 max-w-full flex-1 items-center !gap-1.5 !rounded-none !border-0 !bg-transparent !bg-none !px-2 !py-0 !text-inherit !shadow-none hover:!border-transparent hover:!bg-transparent hover:!text-inherit`,
  agentSessionTabMainActionActive: `vui-routes-chatcodingroute agentSessionTabMainActionActive !text-[var(--fg-primary)] !shadow-none`,
  agentSessionTabMainActionContextTarget:
    "vui-routes-chatcodingroute agentSessionTabMainActionContextTarget",
  agentSessionTabMeta:
    "vui-routes-chatcodingroute agentSessionTabMeta min-w-0 max-w-full text-left [font-size:var(--vui-font-xs)] leading-none text-[var(--fg-tertiary)]",
  agentSessionTabRoot:
    "vui-routes-chatcodingroute agentSessionTabRoot min-w-0",
  agentSessionTabTitleBlock:
    "vui-routes-chatcodingroute agentSessionTabTitleBlock min-w-0 max-w-[9.5rem] flex-1 overflow-hidden",
  // Fixed status slot between title and close: keeps tab geometry stable with/without activity.
  agentSessionTabDragHandle:
    "shrink-0 cursor-grab self-stretch -ml-0.5 px-1 text-[color:var(--fg-tertiary)] opacity-60 transition-opacity duration-150 hover:opacity-100 focus-visible:opacity-100 active:cursor-grabbing",
  agentSessionTabDragging:
    "vui-routes-chatcodingroute agentSessionTabDragging opacity-40 transition-opacity duration-150",
  // Inset shadows draw the insertion line, so no positioned parent is required.
  agentSessionTabDropBefore:
    "vui-routes-chatcodingroute agentSessionTabDropBefore shadow-[inset_2px_0_0_0_var(--accent-cool)]",
  agentSessionTabDropAfter:
    "vui-routes-chatcodingroute agentSessionTabDropAfter shadow-[inset_-2px_0_0_0_var(--accent-cool)]",
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
    "vui-routes-chatcodingroute agentSessionTabTitle block min-w-0 max-w-full truncate text-left [font-size:var(--vui-font-xs)] font-normal leading-none text-[var(--fg-secondary)]",
  agentSessionTabTitleActive:
    "vui-routes-chatcodingroute agentSessionTabTitleActive !font-normal !text-[var(--fg-primary)]",
  // Inline tab rename field: strip dense form chrome so it reads as a tab title, not a dialog.
  agentSessionTabTitleInput:
    "vui-routes-chatcodingroute agentSessionTabTitleInput min-w-0 flex-1 !h-7 !min-h-7 !w-[8.5rem] max-w-[10rem] !rounded-[var(--radius-control)] !border-0 !bg-transparent !px-1.5 !py-0 ![font-size:var(--vui-font-xs)] !font-medium !leading-none !text-[var(--fg-primary)] !shadow-none placeholder:!font-normal placeholder:!text-[var(--fg-tertiary)] focus-visible:!outline-none focus-visible:!ring-1 focus-visible:!ring-[color-mix(in_srgb,var(--accent-cool)_55%,transparent)]",
  agentSessionTabGroupSection:
    "vui-routes-chatcodingroute agentSessionTabGroupSection inline-flex min-w-0 shrink-0 items-center",
  agentSessionTabGroupSectionCollapsed:
    "vui-routes-chatcodingroute agentSessionTabGroupSectionCollapsed",
  agentSessionTabGroupSectionDropTarget:
    "vui-routes-chatcodingroute agentSessionTabGroupSectionDropTarget bg-[color-mix(in_srgb,var(--accent-cool)_10%,transparent)] ring-1 ring-[color-mix(in_srgb,var(--accent-cool)_50%,transparent)]",
  // Panel member row: whole row drags, and the remove control only shows on hover.
  // Row owns the hover surface; the member button stays chrome-less so the row
  // reads as one line instead of a stack of bordered boxes.
  agentSessionTabGroupPanelRow:
    "vui-routes-chatcodingroute agentSessionTabGroupPanelRow group/row relative flex min-w-0 items-center rounded-[7px] hover:bg-[color-mix(in_srgb,var(--fg-primary)_8%,transparent)]",
  agentSessionTabGroupPanelRemove:
    "vui-routes-chatcodingroute agentSessionTabGroupPanelRemove absolute right-1 top-1/2 -translate-y-1/2 shrink-0 opacity-0 transition-opacity group-hover/row:opacity-100",
  agentSessionTabGroupHeader:
    "vui-routes-chatcodingroute agentSessionTabGroupHeader group/tabgroup inline-flex h-7 min-w-0 shrink-0 cursor-pointer items-center gap-1.5 rounded-[6px] px-1.5 text-[var(--vui-font-xs)] font-medium text-[var(--fg-secondary)] transition-colors hover:bg-[var(--vui-control-muted-hover)] hover:text-[var(--vui-control-hover-fg)]",
  agentSessionTabGroupHeaderActive:
    "vui-routes-chatcodingroute agentSessionTabGroupHeaderActive bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] ring-1 ring-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)]",
  agentSessionTabGroupHeaderOpen:
    "vui-routes-chatcodingroute agentSessionTabGroupHeaderOpen [&_[data-group-chevron]]:opacity-100",
  agentSessionTabGroupChevron:
    "vui-routes-chatcodingroute agentSessionTabGroupChevron inline-flex shrink-0 items-center opacity-0 transition-opacity duration-150 group-hover/tabgroup:opacity-100",
  // A collapsed chip must advertise that it opens: hiding the chevron there
  // left an unexplained empty-looking chip. Only the open state stays quiet
  // until hover.
  agentSessionTabGroupChevronCollapsed:
    "vui-routes-chatcodingroute agentSessionTabGroupChevronCollapsed !opacity-100",
  agentSessionTabGroupDot:
    "vui-routes-chatcodingroute agentSessionTabGroupDot inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--fg-tertiary)]",
  agentSessionTabGroupDotGray:
    "vui-routes-chatcodingroute agentSessionTabGroupDotGray bg-[hsl(220_10%_55%)]",
  agentSessionTabGroupDotBlue:
    "vui-routes-chatcodingroute agentSessionTabGroupDotBlue bg-[hsl(212_72%_55%)]",
  agentSessionTabGroupDotGreen:
    "vui-routes-chatcodingroute agentSessionTabGroupDotGreen bg-[hsl(148_55%_45%)]",
  agentSessionTabGroupDotAmber:
    "vui-routes-chatcodingroute agentSessionTabGroupDotAmber bg-[hsl(38_85%_52%)]",
  agentSessionTabGroupDotViolet:
    "vui-routes-chatcodingroute agentSessionTabGroupDotViolet bg-[hsl(268_60%_58%)]",
  agentSessionTabGroupDotRose:
    "vui-routes-chatcodingroute agentSessionTabGroupDotRose bg-[hsl(340_70%_56%)]",
  agentSessionTabGroupTintGray:
    "vui-routes-chatcodingroute bg-[hsl(220_10%_55%/0.16)] hover:bg-[hsl(220_10%_55%/0.24)]",
  agentSessionTabGroupTintBlue:
    "vui-routes-chatcodingroute bg-[hsl(212_72%_55%/0.16)] hover:bg-[hsl(212_72%_55%/0.24)]",
  agentSessionTabGroupTintGreen:
    "vui-routes-chatcodingroute bg-[hsl(148_55%_45%/0.16)] hover:bg-[hsl(148_55%_45%/0.24)]",
  agentSessionTabGroupTintAmber:
    "vui-routes-chatcodingroute bg-[hsl(38_85%_52%/0.18)] hover:bg-[hsl(38_85%_52%/0.26)]",
  agentSessionTabGroupTintViolet:
    "vui-routes-chatcodingroute bg-[hsl(268_60%_58%/0.16)] hover:bg-[hsl(268_60%_58%/0.24)]",
  agentSessionTabGroupTintRose:
    "vui-routes-chatcodingroute bg-[hsl(340_70%_56%/0.16)] hover:bg-[hsl(340_70%_56%/0.24)]",
  agentSessionTabGroupPanelList:
    "vui-routes-chatcodingroute agentSessionTabGroupPanelList m-0 flex max-h-[22rem] w-[15rem] list-none flex-col gap-0.5 overflow-y-auto rounded-[10px] p-1",
  agentSessionTabGroupPanelItem:
    "vui-routes-chatcodingroute agentSessionTabGroupPanelItem flex w-full min-w-0 items-center gap-1.5 !rounded-[7px] !border-0 !bg-transparent px-2 py-1.5 pr-7 text-left text-[12px] leading-tight text-[var(--fg-primary)] !shadow-none",
  agentSessionTabGroupPanelItemActive:
    "vui-routes-chatcodingroute agentSessionTabGroupPanelItemActive bg-[color-mix(in_srgb,var(--accent-cool)_12%,transparent)] ring-1 ring-[color-mix(in_srgb,var(--accent-cool)_45%,transparent)]",
  agentSessionTabGroupPanelTitle:
    "vui-routes-chatcodingroute agentSessionTabGroupPanelTitle min-w-0 flex-1 truncate",
  agentSessionTabGroupPanelEmpty:
    "vui-routes-chatcodingroute agentSessionTabGroupPanelEmpty m-0 px-2 py-1.5 text-[11px] text-[var(--fg-tertiary)]",
  agentSessionTabGroupHeaderDropTarget:
    "vui-routes-chatcodingroute agentSessionTabGroupHeaderDropTarget bg-[color-mix(in_srgb,var(--fg-primary)_10%,transparent)] ring-1 ring-[color-mix(in_srgb,var(--fg-primary)_35%,transparent)]",
  agentSessionTabGroupName:
    "vui-routes-chatcodingroute agentSessionTabGroupName max-w-[9rem] truncate font-medium",
  agentSessionTabGroupNameInput:
    "vui-routes-chatcodingroute agentSessionTabGroupNameInput h-6 w-[7.5rem] min-w-0 text-[11px]",
  agentSessionTabGroupCount:
    "vui-routes-chatcodingroute agentSessionTabGroupCount inline-flex h-4 min-w-4 shrink-0 items-center justify-center rounded-full bg-[color-mix(in_srgb,var(--fg-primary)_8%,transparent)] px-1 tabular-nums text-[10px] font-medium leading-none text-[var(--fg-tertiary)]",
  agentSessionTabGroupAction:
    "vui-routes-chatcodingroute agentSessionTabGroupAction h-6 w-5 shrink-0",
  agentSessionTabGroupCreateButton:
    "vui-routes-chatcodingroute agentSessionTabGroupCreateButton h-6 w-6 shrink-0",
  agentSessionTabGroupPeekHeading:
    "vui-routes-chatcodingroute agentSessionTabGroupPeekHeading m-0 truncate px-1.5 pb-0.5 text-[10px] font-medium uppercase tracking-wide text-[var(--fg-tertiary)]",
  agentSessionTabGroupMenuItem:
    "vui-routes-chatcodingroute agentSessionTabGroupMenuItem inline-flex min-w-0 flex-1 items-center gap-2",
  agentSessionTabGroupMenu:
    "vui-routes-chatcodingroute agentSessionTabGroupMenu w-[10.5rem] min-w-[10.5rem] p-1",
  agentSessionTabGroupMenuRow:
    "vui-routes-chatcodingroute agentSessionTabGroupMenuRow gap-1.5 px-1.5 py-1 text-[12px]",
  agentSessionTabGroupMenuLabel:
    "vui-routes-chatcodingroute agentSessionTabGroupMenuLabel min-w-0 flex-1 truncate",
  agentSessionTabGroupMenuCheck:
    "vui-routes-chatcodingroute agentSessionTabGroupMenuCheck shrink-0 text-[var(--accent-cool)]",
  agentSessionTabGroupPeek:
    "vui-routes-chatcodingroute agentSessionTabGroupPeek flex w-[16rem] flex-col gap-2 p-0.5",
  agentSessionTabGroupPalette:
    "vui-routes-chatcodingroute agentSessionTabGroupPalette flex items-center gap-1.5",
  agentSessionTabGroupSwatch:
    "vui-routes-chatcodingroute agentSessionTabGroupSwatch h-3.5 min-h-3.5 w-3.5 min-w-3.5 shrink-0 rounded-full border border-[color-mix(in_srgb,var(--fg-primary)_20%,transparent)] p-0 shadow-none",
  agentSessionTabGroupSwatchActive:
    "vui-routes-chatcodingroute agentSessionTabGroupSwatchActive ring-2 ring-[var(--accent-cool)] ring-offset-1 ring-offset-[var(--vui-surface-chat)]",
  agentSessionTabGroupSwatchGray:
    "vui-routes-chatcodingroute agentSessionTabGroupSwatchGray !bg-[hsl(220_10%_55%)]",
  agentSessionTabGroupSwatchBlue:
    "vui-routes-chatcodingroute agentSessionTabGroupSwatchBlue !bg-[hsl(212_72%_55%)]",
  agentSessionTabGroupSwatchGreen:
    "vui-routes-chatcodingroute agentSessionTabGroupSwatchGreen !bg-[hsl(148_55%_45%)]",
  agentSessionTabGroupSwatchAmber:
    "vui-routes-chatcodingroute agentSessionTabGroupSwatchAmber !bg-[hsl(38_85%_52%)]",
  agentSessionTabGroupSwatchViolet:
    "vui-routes-chatcodingroute agentSessionTabGroupSwatchViolet !bg-[hsl(268_60%_58%)]",
  agentSessionTabGroupSwatchRose:
    "vui-routes-chatcodingroute agentSessionTabGroupSwatchRose !bg-[hsl(340_70%_56%)]",
  agentSessionTabGroupPeekList:
    "vui-routes-chatcodingroute agentSessionTabGroupPeekList m-0 flex max-h-[14rem] list-none flex-col gap-0.5 overflow-y-auto p-0",
  agentSessionTabGroupPeekItem:
    "vui-routes-chatcodingroute agentSessionTabGroupPeekItem flex w-full min-w-0 items-center justify-start rounded-[var(--radius-control)] px-1.5 py-1 text-left text-[12px] text-[var(--fg-secondary)] hover:bg-[var(--vui-control-muted-hover)] hover:text-[var(--fg-primary)]",
  agentSessionTabGroupPeekTitle:
    "vui-routes-chatcodingroute agentSessionTabGroupPeekTitle truncate",
  agentSessionTabGroupPeekHint:
    "vui-routes-chatcodingroute agentSessionTabGroupPeekHint m-0 text-[11px] leading-snug text-[var(--fg-tertiary)]",
} as const;

export default styles;
