import {
  vuiFlatPanelClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  empty:
    "empty min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  workflowCandidateList:
    "workflowCandidateList min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto [&_[data-vui-product=team-candidate-card]]:max-w-full",
  workflowCandidateListHeader:
    "workflowCandidateListHeader min-w-0 flex min-h-0 items-center justify-between gap-2",
  workflowCandidateListActions:
    "workflowCandidateListActions flex min-w-0 shrink-0 items-center justify-end gap-1.5",
  workflowCandidateListPanel: `workflowCandidateListPanel min-w-0 ${vuiFlatPanelClass} p-2 grid min-h-0 content-start gap-1.5 overflow-hidden`,
  workflowCandidateListScroll:
    "workflowCandidateListScroll min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto [scrollbar-gutter:stable]",
  workflowCandidateListScrollCue:
    "workflowCandidateListScrollCue pointer-events-none sticky bottom-0 block h-4 bg-gradient-to-t from-[var(--vui-surface-panel)] to-transparent",
} as const;

export default styles;
