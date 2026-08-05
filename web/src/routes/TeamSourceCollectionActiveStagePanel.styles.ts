import {
  vuiFlatPanelClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  sourceCollectionExtractionPanels:
    "sourceCollectionExtractionPanels min-w-0 grid h-full min-h-0 grid-rows-[minmax(0,1fr)] gap-2 overflow-hidden",
  sourceCollectionExtractionScrollRegion:
    "sourceCollectionExtractionScrollRegion min-w-0 min-h-0 overflow-auto [scrollbar-gutter:stable]",
  sourceCollectionStageIntegratedRecovery:
    "sourceCollectionStageIntegratedRecovery min-w-0 max-h-[min(48dvh,360px)] overflow-auto [overscroll-behavior:contain] [&_.sourceCollectionExtractionRecoveryPanel]:border-0 [&_.sourceCollectionExtractionRecoveryPanel]:bg-transparent [&_.sourceCollectionExtractionRecoveryPanel]:p-0",
  sourceCollectionIngestionPanels:
    "sourceCollectionIngestionPanels min-w-0 grid min-h-0 content-stretch gap-2 grid-rows-[auto_minmax(0,1fr)] overflow-hidden max-[860px]:min-h-[560px] max-[860px]:grid-rows-[auto_minmax(0,1fr)] max-[860px]:overflow-hidden",
  sourceCollectionStageChatActions:
    "sourceCollectionStageChatActions min-w-0 !grid grid-cols-[repeat(2,minmax(0,1fr))] items-center gap-1.5 [&_a]:inline-flex [&_a]:w-full [&_a]:max-w-full [&_a]:items-center [&_a]:justify-center [&_a]:gap-1.5 [&_a]:min-h-[30px] [&_a]:px-2 [&_a]:rounded-[7px] [&_a]:border [&_a]:border-[color:color-mix(in_srgb,var(--accent-cool)_36%,var(--border-soft))] [&_a]:bg-[var(--vui-surface-row)] [&_a]:text-[var(--fg-primary)] [&_a]:font-[760] [&_a]:no-underline [&_a]:whitespace-nowrap [&_[data-vui=native-button]]:min-h-[30px] [&_[data-vui=native-button]]:w-full [&_[data-vui=native-button]]:max-w-full [&_[data-vui=native-button]:first-child]:col-span-2 max-[1020px]:grid-cols-[repeat(3,max-content)] max-[1020px]:justify-start max-[1020px]:[&_[data-vui=native-button]]:w-fit max-[1020px]:[&_a]:w-fit max-[1020px]:[&_[data-vui=native-button]:first-child]:col-span-1",
  sourceCollectionStageNextAction:
    "sourceCollectionStageNextAction min-w-0 grid gap-1.5 rounded-[var(--radius-panel)] border border-[var(--vui-border-strong,var(--vui-border-subtle))] bg-[var(--vui-surface-panel)] p-3 shadow-[inset_3px_0_0_0_var(--fg-primary)]",
  sourceCollectionStageNextActionLabel:
    "sourceCollectionStageNextActionLabel m-0 [font-size:var(--vui-font-xs)] font-semibold tracking-wide text-[var(--fg-tertiary)]",
  sourceCollectionStageNextActionBadge:
    "sourceCollectionStageNextActionBadge w-fit max-w-full rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] px-2 py-0.5 [font-size:var(--vui-font-xs)] font-semibold text-[var(--fg-secondary)]",
  sourceCollectionStageNextActionButton:
    "sourceCollectionStageNextActionButton !h-10 !min-h-10 !w-full !max-w-full !justify-center !px-3 ![font-size:var(--vui-font-sm)] !font-semibold",
  sourceCollectionStageNextActionHint:
    "sourceCollectionStageNextActionHint m-0 [font-size:var(--vui-font-xs)] leading-snug text-[var(--fg-secondary)]",
  sourceCollectionStageMoreActions:
    "sourceCollectionStageMoreActions min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] [&_summary]:cursor-pointer [&_summary]:list-none [&_summary]:px-2 [&_summary]:py-1.5 [&_summary]:[font-size:var(--vui-font-xs)] [&_summary]:font-semibold [&_summary]:text-[var(--fg-tertiary)] [&_summary::-webkit-details-marker]:hidden",
  sourceCollectionStageMoreActionsBody:
    "sourceCollectionStageMoreActionsBody min-w-0 grid grid-cols-1 gap-1.5 border-t border-[var(--vui-border-subtle)] p-1.5 [&_a]:inline-flex [&_a]:w-full [&_a]:items-center [&_a]:justify-center [&_a]:gap-1.5 [&_a]:min-h-[30px] [&_a]:px-2 [&_a]:rounded-[7px] [&_a]:border [&_a]:border-[var(--vui-border-subtle)] [&_a]:bg-[var(--vui-control-muted)] [&_a]:text-[var(--fg-secondary)] [&_a]:[font-size:var(--vui-font-xs)] [&_a]:no-underline [&_[data-vui=native-button]]:w-full [&_[data-vui=native-button]]:min-h-[30px] [&_[data-vui=native-button]]:justify-center [&_[data-vui=native-button]]:text-[var(--fg-secondary)]",
  sourceCollectionStageErrors:
    "sourceCollectionStageErrors min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto empty:hidden",
  sourceCollectionStageHandoff:
    "sourceCollectionStageHandoff min-w-0 grid gap-0.5 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-secondary)] [&>span]:min-w-0 [&>span]:grid [&>span]:grid-cols-[minmax(64px,0.7fr)_minmax(0,1fr)] [&>span]:gap-2 [&>span]:break-words [&>span]:[overflow-wrap:anywhere] [&>span]:border-b [&>span]:border-[var(--vui-border-subtle)] [&>span]:py-1.5 [&>span:last-child]:border-b-0 [&_b]:text-[var(--fg-tertiary)]",
  sourceCollectionStageHandoffNext:
    "sourceCollectionStageHandoffNext min-w-0 text-[var(--fg-primary)]",
  sourceCollectionStageFlowGuide:
    "sourceCollectionStageFlowGuide min-w-0 grid gap-1.5 rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--accent-cool)_28%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--accent-cool)_7%,var(--vui-surface-row))] p-2",
  sourceCollectionStageFlowSteps:
    "sourceCollectionStageFlowSteps m-0 flex list-none flex-wrap gap-1 p-0",
  sourceCollectionStageFlowStep:
    "sourceCollectionStageFlowStep inline-flex max-w-full items-center rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 py-0.5 [font-size:var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-tertiary)]",
  sourceCollectionStageFlowStepCurrent:
    "sourceCollectionStageFlowStepCurrent border-[color-mix(in_srgb,var(--accent-cool)_48%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--accent-cool)_16%,var(--vui-surface-panel))] text-[var(--fg-primary)]",
  sourceCollectionStageFlowStepDone:
    "sourceCollectionStageFlowStepDone border-[color-mix(in_srgb,var(--state-success)_40%,var(--vui-border-subtle))] text-[var(--fg-secondary)]",
  sourceCollectionStageFlowHints:
    "sourceCollectionStageFlowHints min-w-0 grid gap-0.5 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-secondary)] [&>span]:min-w-0 [&>span]:grid [&>span]:grid-cols-[minmax(48px,auto)_minmax(0,1fr)] [&>span]:gap-1.5 [&>span]:break-words [&_b]:text-[var(--fg-tertiary)]",
  sourceCollectionStageFlowNow:
    "sourceCollectionStageFlowNow text-[var(--fg-primary)] font-semibold",
  sourceCollectionStagePrimaryAction:
    "sourceCollectionStagePrimaryAction !min-h-9 !w-full !max-w-full !justify-center",
  sourceCollectionStageResult:
    "sourceCollectionStageResult min-w-0 grid h-full min-h-0 overflow-hidden",
  sourceCollectionStageSecondaryAction:
    "sourceCollectionStageSecondaryAction !min-h-9 !w-fit !max-w-full",
  /** Host for resizable center/right stage columns. */
  sourceCollectionStageWorkspace:
    "sourceCollectionStageWorkspace min-w-0 flex h-full min-h-[360px] max-w-full flex-col overflow-hidden",
  sourceCollectionStageWorkspaceCompact:
    "sourceCollectionStageWorkspace sourceCollectionStageWorkspaceCompact min-w-0 flex h-full min-h-0 max-w-full flex-col overflow-hidden",
  sourceCollectionStageWorkspaceSplit:
    "sourceCollectionStageWorkspaceSplit min-h-0 min-w-0 flex-1",
  sourceCollectionStageResultHost:
    "sourceCollectionStageResultHost flex h-full min-h-0 min-w-0 flex-1 flex-col overflow-hidden p-0.5",
  sourceCollectionStageAsideHost:
    "sourceCollectionStageAsideHost flex h-full min-h-0 min-w-0 flex-col overflow-hidden p-0.5",
  sourceCollectionStageWorkspaceHeader: `sourceCollectionStageWorkspaceHeader min-w-0 !grid grid-cols-[minmax(0,1fr)] content-start items-start gap-2 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] ${vuiFlatPanelClass} p-2 h-full min-h-0 overflow-y-auto [scrollbar-gutter:stable] [&>div]:min-w-0 [&>div:first-child]:grid [&>div:first-child]:gap-0.5 [&>div>strong]:min-w-0 [&>div>strong]:truncate [&>div>span]:min-w-0 [&>div>span]:break-words`,
  /** Compact project-reset actions under the stage card (buttons only, no copy wall). */
  sourceCollectionStageProjectReset:
    "sourceCollectionStageProjectReset min-w-0 grid gap-1.5 border-t border-[var(--vui-border-subtle)] pt-2 mt-0.5 empty:hidden [&_[data-vui=button]]:!w-full [&_[data-vui=button]]:!justify-center",
} as const;

export default styles;
