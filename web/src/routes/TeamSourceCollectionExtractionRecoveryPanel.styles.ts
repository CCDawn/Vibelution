import { vuiOpaqueRowClass } from "../design/vuiSurfaceRecipes";

const rowDescendant = vuiOpaqueRowClass
  .split(/\s+/)
  .filter(Boolean)
  .map((token) => `[&_span]:${token}`)
  .join(" ");

const styles = {
  sourceCollectionExtractionRecoveryActions:
    "sourceCollectionExtractionRecoveryActions min-w-0 flex flex-wrap items-center justify-end gap-1.5 self-start [&_[data-vui=native-button]]:w-fit [&_[data-vui=native-button]]:max-w-full",
  sourceCollectionExtractionRecoveryBody:
    "sourceCollectionExtractionRecoveryBody min-w-0 grid content-start gap-1.5 [&_p]:m-0 [&_p]:[font-size:var(--vui-font-sm)] [&_p]:leading-[var(--vui-line-readable)] [&_p]:text-[var(--fg-secondary)]",
  sourceCollectionExtractionRecoveryPanel:
    "sourceCollectionExtractionRecoveryPanel min-w-0 !grid grid-cols-[minmax(0,1fr)_auto] items-start gap-2 rounded-[var(--radius-control)] border p-2 text-[var(--fg-secondary)] max-[760px]:grid-cols-[1fr]",
  sourceCollectionExtractionRecoveryPanelDanger:
    "sourceCollectionExtractionRecoveryPanelDanger border-[color-mix(in_srgb,var(--state-error)_34%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--state-error)_7%,var(--source-workbench-card))] [&_svg]:text-[var(--state-error)]",
  sourceCollectionExtractionRecoveryPanelProgressable:
    "sourceCollectionExtractionRecoveryPanelProgressable border-[color-mix(in_srgb,var(--state-warning)_38%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--state-warning)_8%,var(--source-workbench-card))] [&_svg]:text-[var(--state-warning)]",
  sourceCollectionExtractionRecoveryStats:
    `sourceCollectionExtractionRecoveryStats min-w-0 grid gap-1.5 grid-cols-[repeat(auto-fit,minmax(7rem,1fr))] [&_span]:grid [&_span]:min-w-0 [&_span]:gap-0.5 ${rowDescendant} [&_span]:px-2 [&_span]:py-1 [&_span]:[font-size:var(--vui-font-xs)] [&_strong]:text-[var(--fg-primary)]`,
  sourceCollectionResultsHeader:
    "sourceCollectionResultsHeader min-w-0 flex flex-wrap items-center gap-1.5",
  sourceCollectionRunBadge:
    "sourceCollectionRunBadge min-w-0 inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-1.5 rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 [font-size:var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-secondary)]",
} as const;

export default styles;
