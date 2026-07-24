import {
  vuiFlatPanelClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  sourceCollectionConversationHeader:
    "sourceCollectionConversationHeader min-w-0 flex flex-wrap items-center gap-1.5",
  sourceCollectionConversationPanel: `sourceCollectionConversationPanel min-w-0 ${vuiFlatPanelClass} p-[var(--team-workbench-gap)] grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)] content-stretch gap-[var(--team-workbench-gap)] overflow-hidden max-[760px]:!h-auto max-[760px]:grid-rows-[auto_auto] max-[760px]:content-start max-[760px]:overflow-visible`,
  sourceCollectionConversationPanelCompact: `sourceCollectionConversationPanel sourceCollectionConversationPanelCompact min-w-0 shrink-0 ${vuiFlatPanelClass} p-[var(--team-workbench-gap)] grid h-auto min-h-0 grid-rows-[auto_auto] content-start gap-[var(--team-workbench-gap)] overflow-visible`,
  sourceCollectionResultWarning:
    "sourceCollectionResultWarning min-w-0 border-[color-mix(in_srgb,var(--state-warning)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-warning)_10%,transparent)] text-[var(--state-warning)]",
  sourceCollectionResultsHeader:
    "sourceCollectionResultsHeader min-w-0 flex flex-wrap items-center gap-1.5",
  sourceCollectionResultsPanel: `sourceCollectionResultsPanel min-w-0 ${vuiFlatPanelClass} p-[var(--team-workbench-gap)] !flex min-h-0 flex-col gap-[var(--team-workbench-gap)] overflow-hidden max-[760px]:!h-auto max-[760px]:min-h-0 max-[760px]:overflow-visible`,
  sourceCollectionResultsPanelCompact: `sourceCollectionResultsPanel sourceCollectionResultsPanelCompact min-w-0 self-start shrink-0 ${vuiFlatPanelClass} p-[var(--team-workbench-gap)] !flex min-h-0 flex-col gap-[var(--team-workbench-gap)] overflow-visible max-[760px]:min-h-0`,
} as const;

export default styles;
