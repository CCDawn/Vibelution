import {
  vuiFlatPanelClass,
  vuiOpaqueRowClass,
} from "../../../../design/vuiSurfaceRecipes";

const styles = {
  sourceCollectionStageAgentCard: `sourceCollectionStageAgentCard min-w-0 ${vuiOpaqueRowClass} !grid grid-cols-[minmax(0,1fr)_auto] items-stretch gap-1.5 p-1.5 text-[var(--accent-cool)] max-[720px]:grid-cols-[minmax(0,1fr)] [&_a]:inline-flex [&_[data-vui=native-button]]:inline-flex [&_a]:min-h-[28px] [&_a]:w-fit [&_a]:max-w-full [&_a]:items-center [&_a]:justify-center [&_a]:gap-1.5 [&_a]:whitespace-nowrap [&_a]:rounded-[7px] [&_a]:border [&_a]:border-[color:color-mix(in_srgb,var(--accent-cool)_32%,var(--border-soft))] [&_a]:bg-[color:color-mix(in_srgb,var(--accent-cool)_8%,var(--vui-surface-panel))] [&_a]:px-2.5 [&_a]:font-[780] [&_a]:text-[var(--fg-primary)] [&_a]:no-underline`,
  sourceCollectionStageAgentCardStacked: "!grid-cols-[minmax(0,1fr)] gap-2 p-2.5",
  sourceCollectionStageAgentCardActions:
    "sourceCollectionStageAgentCardActions flex min-w-0 flex-wrap items-center justify-end gap-1.5 text-[var(--accent-cool)] max-[720px]:justify-start [&>span]:min-w-0 [&>span]:break-words [&>span]:text-[length:var(--vui-font-xs)] [&>span]:font-semibold [&>span]:leading-tight [&_a]:w-fit",
  sourceCollectionStageAgentCardBody:
    "sourceCollectionStageAgentCardBody !grid min-w-0 grid-cols-[repeat(3,minmax(0,1fr))] gap-1.5 p-1 text-[length:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--accent-cool)] max-[680px]:grid-cols-[minmax(0,1fr)] [&_span]:grid [&_span]:min-w-0 [&_span]:gap-0.5 [&_small]:min-w-0 [&_small]:text-[var(--fg-tertiary)] [&_strong]:min-w-0 [&_strong]:truncate [&_strong]:text-[var(--fg-primary)]",
  sourceCollectionStageAgentCardBodyStacked: "!grid-cols-[minmax(0,1fr)] gap-2 !p-0 [&_strong]:whitespace-normal [&_strong]:break-words",
  sourceCollectionStageAgentHeader:
    "sourceCollectionStageAgentHeader flex min-w-0 items-center text-[var(--accent-cool)] [&>strong]:text-[var(--fg-primary)]",
  sourceCollectionStageAgentList:
    "sourceCollectionStageAgentList grid min-h-0 min-w-0 content-start gap-1.5 overflow-auto text-[var(--accent-cool)]",
  sourceCollectionStageAgentPanel: `sourceCollectionStageAgentPanel min-w-0 [container-type:inline-size] ${vuiFlatPanelClass} p-2 text-[var(--fg-primary)]`,
} as const;

export default styles;
