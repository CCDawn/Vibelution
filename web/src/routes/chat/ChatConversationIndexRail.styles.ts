// Wave 8C: extracted from ChatCodingRoute.styles for ChatConversationIndexRail.tsx

import {
  vuiControlQuietClass,
} from "../../design/vuiChromeRecipes";

import {
  vuiGlassPanelClass,
  vuiOpaqueRowClass,
  vuiStateCoolInfoClass,
  vuiStateCoolSoftClass,
  vuiStateSelectedRowClass,
  vuiStateSelectedRowFillClass,
} from "../../design/vuiSurfaceRecipes";

const styles: Record<string, string> = {
  agentIndexAvatar:
    `vui-routes-chatcodingroute agentIndexAvatar min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] ${vuiStateCoolInfoClass}`,
  agentIndexCard:
    "vui-routes-chatcodingroute agentIndexCard min-w-0 overflow-hidden rounded-[var(--radius-panel)] border border-[color-mix(in_srgb,var(--accent-cool)_24%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--accent-cool)_7%,var(--vui-surface-glass))] p-1.5 shadow-[var(--vui-shadow-hairline)]",
  agentIndexCopy:
    "vui-routes-chatcodingroute agentIndexCopy grid min-w-0 gap-0.5 overflow-hidden text-left [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-secondary)]",
  agentIndexDetails:
    `vui-routes-chatcodingroute agentIndexDetails min-w-0 ${vuiStateCoolInfoClass}`,
  agentIndexEmptyState:
    `vui-routes-chatcodingroute agentIndexEmptyState min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)] ${vuiStateCoolInfoClass}`,
  agentIndexExpandButton:
    `vui-routes-chatcodingroute agentIndexExpandButton min-w-0 ${vuiControlQuietClass} ${vuiStateCoolInfoClass}`,
  agentIndexHeader:
    "vui-routes-chatcodingroute agentIndexHeader min-w-0 !grid grid-cols-[18px_minmax(0,1fr)_fit-content(72px)] items-center gap-1.5",
  agentIndexList:
    `vui-routes-chatcodingroute agentIndexList min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto ${vuiStateCoolInfoClass}`,
  agentIndexMentalBlock:
    `vui-routes-chatcodingroute agentIndexMentalBlock min-w-0 ${vuiStateCoolInfoClass}`,
  agentIndexNameLine:
    "vui-routes-chatcodingroute agentIndexNameLine !flex min-w-0 max-w-full items-center gap-1.5 [font-size:var(--vui-font-xs)] font-semibold leading-tight [color:var(--fg-primary)] [&_em]:shrink-0 [&_span]:min-w-0 [&_span]:truncate",
  agentIndexOpenButton:
    "vui-routes-chatcodingroute agentIndexOpenButton min-w-0 !grid !h-auto !min-h-[34px] !w-full max-w-full grid-cols-[30px_minmax(0,1fr)] items-center justify-start gap-1.5 overflow-hidden rounded-[var(--radius-control)] border border-transparent bg-transparent px-1 py-0.5 text-left [font-size:var(--vui-font-xs)] font-semibold leading-tight [color:var(--fg-secondary)] shadow-none hover:border-[color-mix(in_srgb,var(--accent-cool)_26%,var(--vui-border-subtle))] hover:bg-[color-mix(in_srgb,var(--accent-cool)_7%,var(--vui-surface-row))] hover:text-[var(--fg-primary)] disabled:cursor-default disabled:opacity-55 [&_[data-slot=vui-button-content]]:contents [&_[data-slot=vui-button-label]]:contents",
  agentIndexRoster:
    `vui-routes-chatcodingroute agentIndexRoster min-w-0 ${vuiStateCoolInfoClass}`,
  agentIndexStatus:
    "vui-routes-chatcodingroute agentIndexStatus inline-flex min-w-0 max-w-[72px] justify-self-end overflow-hidden text-ellipsis whitespace-nowrap rounded-full border border-[color-mix(in_srgb,var(--accent-cool)_24%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] px-1.5 py-0.5 text-[10px] font-semibold leading-none text-[var(--accent-cool)]",
  agentModelLine:
    "vui-routes-chatcodingroute agentModelLine block min-w-0 truncate text-[10px] font-medium leading-tight text-[var(--fg-tertiary)]",
  agentModelTag:
    "vui-routes-chatcodingroute agentModelTag inline-flex min-h-[18px] min-w-0 max-w-[96px] shrink items-center gap-0.5 overflow-hidden rounded-full border border-[color-mix(in_srgb,var(--accent-cool)_24%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--accent-cool)_7%,transparent)] px-1.5 py-0 [font-size:var(--vui-font-xs)] font-semibold leading-none text-[var(--accent-cool)] [&_span]:min-w-0 [&_span]:truncate [&_svg]:shrink-0",
  agentOptionMeta:
    `vui-routes-chatcodingroute agentOptionMeta min-w-0 flex flex-wrap items-center gap-1.5 ${vuiStateCoolInfoClass}`,
  conversationIndexLayout:
    "vui-routes-chatcodingroute conversationIndexLayout grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)_auto] gap-2",
  conversationIndexPanelBody:
    "vui-routes-chatcodingroute conversationIndexPanelBody !overflow-hidden",
  conversationIndexScrollRegion:
    "vui-routes-chatcodingroute conversationIndexScrollRegion min-h-0 overflow-y-auto pr-1 [scrollbar-gutter:stable]",
  conversationTreeRootHeader:
    "vui-routes-chatcodingroute conversationTreeRootHeader !grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-2 px-1.5 [font-size:var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-tertiary)] [&_strong]:font-semibold [&_strong]:tabular-nums",
  createGroupButton:
    `vui-routes-chatcodingroute createGroupButton min-w-0 ${vuiControlQuietClass}`,
  groupAgentOption:
    `vui-routes-chatcodingroute groupAgentOption min-w-0 ${vuiStateCoolInfoClass} !grid grid-cols-[auto_28px_minmax(0,1fr)] items-center gap-1.5`,
  groupAgentOptionSelected:
    `vui-routes-chatcodingroute groupAgentOptionSelected min-w-0 ${vuiStateCoolSoftClass} border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)]`,
  groupAgentPicker:
    `vui-routes-chatcodingroute groupAgentPicker min-w-0 ${vuiStateCoolInfoClass}`,
  groupComposerEmpty:
    "vui-routes-chatcodingroute groupComposerEmpty min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  groupComposerField:
    "vui-routes-chatcodingroute groupComposerField min-w-0 grid gap-1 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)] [&_input]:min-h-[var(--vui-control-height-sm)] [&_select]:min-h-[var(--vui-control-height-sm)] [&_textarea]:min-h-20 [&_input]:w-full [&_select]:w-full [&_textarea]:w-full",
  groupComposerInput:
    "vui-routes-chatcodingroute groupComposerInput min-w-0 grid gap-1 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)] [&_input]:min-h-[var(--vui-control-height-sm)] [&_select]:min-h-[var(--vui-control-height-sm)] [&_textarea]:min-h-20 [&_input]:w-full [&_select]:w-full [&_textarea]:w-full",
  groupComposerPanel: `vui-routes-chatcodingroute groupComposerPanel min-w-0 ${vuiGlassPanelClass} p-2`,
  memberIndexSummary: `vui-routes-chatcodingroute memberIndexSummary min-w-0 ${vuiGlassPanelClass} p-2 !grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-1.5`,
  newGroupButton:
    "vui-routes-chatcodingroute newGroupButton !inline-flex !h-[34px] !min-h-[34px] !min-w-0 !w-full max-w-full items-center justify-center gap-1 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 py-0 ![font-size:var(--vui-font-xs)] font-semibold !leading-none [color:var(--fg-secondary)] shadow-none hover:bg-[var(--vui-control-muted-hover)] [&_[data-slot=vui-button-content]]:min-w-0 [&_[data-slot=vui-button-content]]:!leading-none [&_[data-slot=vui-button-label]]:min-w-0 [&_[data-slot=vui-button-label]]:truncate [&_[data-slot=vui-button-label]]:!leading-none",
  newSessionButton:
    `vui-routes-chatcodingroute newSessionButton !inline-flex !h-[34px] !min-h-[34px] !min-w-0 !w-full max-w-full items-center justify-center gap-1 rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--accent-cool)_34%,var(--vui-border-subtle))] ${vuiStateSelectedRowFillClass} px-2 py-0 ![font-size:var(--vui-font-xs)] font-semibold !leading-none [color:var(--accent-cool)] shadow-none hover:bg-[color-mix(in_srgb,var(--accent-cool)_14%,var(--vui-surface-row))] [&_[data-slot=vui-button-content]]:min-w-0 [&_[data-slot=vui-button-content]]:!leading-none [&_[data-slot=vui-button-label]]:min-w-0 [&_[data-slot=vui-button-label]]:truncate [&_[data-slot=vui-button-label]]:!leading-none`,
  panelBody:
    "vui-routes-chatcodingroute panelBody min-w-0 h-full p-2 [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] min-h-0 overflow-auto [scrollbar-gutter:stable]",
  panelSearch: `vui-routes-chatcodingroute panelSearch grid min-h-9 min-w-0 grid-cols-[16px_minmax(0,1fr)] items-center gap-1.5 ${vuiOpaqueRowClass} px-2 py-0 text-[var(--fg-tertiary)] shadow-none transition-colors hover:border-[color-mix(in_srgb,var(--accent-cool)_24%,var(--vui-border-subtle))] focus-within:border-[color-mix(in_srgb,var(--accent-cool)_42%,var(--vui-border-subtle))] focus-within:!bg-[var(--vui-surface-card)]`,
  panelSearchInput:
    "vui-routes-chatcodingroute panelSearchInput min-w-0 w-full !border-0 !bg-transparent px-0 py-0 text-[var(--fg-primary)] !shadow-none [&_[data-slot=input-wrapper]]:min-h-8 [&_[data-slot=input-wrapper]]:rounded-none [&_[data-slot=input-wrapper]]:!border-0 [&_[data-slot=input-wrapper]]:!bg-transparent [&_[data-slot=input-wrapper]]:px-0 [&_[data-slot=input-wrapper]]:shadow-none [&_[data-slot=input]]:[font-size:var(--vui-font-sm)] [&_[data-slot=input]]:text-[var(--fg-primary)] [&_[data-slot=input]]:placeholder:text-[var(--fg-tertiary)] [&_[data-slot=inner-wrapper]]:gap-0",
  rightIndexTab:
    `vui-routes-chatcodingroute rightIndexTab min-w-0 ${vuiControlQuietClass}`,
  rightIndexTabActive:
    `vui-routes-chatcodingroute rightIndexTabActive min-w-0 ${vuiStateSelectedRowClass}`,
  rightIndexTabs:
    "vui-routes-chatcodingroute rightIndexTabs min-w-0 !grid grid-cols-[repeat(2,minmax(0,1fr))] gap-1",
  sectionMetaLine:
    "vui-routes-chatcodingroute sectionMetaLine min-w-0 whitespace-normal [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)] [overflow-wrap:anywhere]",
  // Surface titles in the status rail (session/group name): compact but primary.,
  sessionActionRow:
    "vui-routes-chatcodingroute sessionActionRow grid min-w-0 grid-cols-2 items-center gap-2 border-0 bg-transparent p-0",
  sessionCurrentBadge:
    "vui-routes-chatcodingroute sessionCurrentBadge !inline-flex !h-[22px] !min-h-[22px] !w-fit max-w-full shrink-0 items-center justify-center gap-1 overflow-hidden border-[color-mix(in_srgb,var(--accent-cool)_36%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_10%,transparent)] px-1.5 [font-size:var(--vui-font-xs)] font-semibold leading-none text-[var(--accent-cool)] [&_span]:leading-none",
  systemEntryButton:
    "vui-routes-chatcodingroute systemEntryButton relative !grid !h-auto !min-h-[46px] !w-full grid-cols-[28px_minmax(0,1fr)] items-center justify-start gap-2 overflow-hidden rounded-[var(--radius-control)] border border-transparent bg-transparent px-1.5 py-1 text-left [color:var(--fg-secondary)] shadow-none transition-colors before:absolute before:inset-y-1.5 before:left-0 before:w-[2px] before:rounded-full before:bg-[var(--accent-cool)] before:opacity-0 hover:border-[color-mix(in_srgb,var(--accent-cool)_18%,transparent)] hover:!bg-[var(--vui-surface-card)] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)] [&_[data-slot=vui-button-content]]:contents [&_[data-slot=vui-button-label]]:contents",
  systemEntryButtonActive:
    "vui-routes-chatcodingroute systemEntryButtonActive border-[color-mix(in_srgb,var(--accent-cool)_22%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_7%,var(--vui-surface-card))] [color:var(--fg-primary)] before:absolute before:opacity-100",
  systemEntryCopy:
    "vui-routes-chatcodingroute systemEntryCopy grid min-w-0 gap-0.5 overflow-hidden text-left",
  systemEntryGroup:
    "vui-routes-chatcodingroute systemEntryGroup grid min-w-0 gap-1 border-t border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] pt-2 shadow-none",
  systemEntryIcon:
    "vui-routes-chatcodingroute systemEntryIcon grid size-7 shrink-0 place-items-center rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] [color:var(--fg-secondary)]",
  systemEntryMeta:
    "vui-routes-chatcodingroute systemEntryMeta block min-w-0 truncate [font-size:10px] font-medium leading-tight [color:var(--fg-tertiary)]",
  systemEntryTitle:
    "vui-routes-chatcodingroute systemEntryTitle block min-w-0 truncate [font-size:var(--vui-font-xs)] font-semibold leading-tight [color:var(--fg-primary)]",
  systemEntryTitleRow:
    "vui-routes-chatcodingroute systemEntryTitleRow !flex min-w-0 items-center gap-1.5",
};

export default styles;
