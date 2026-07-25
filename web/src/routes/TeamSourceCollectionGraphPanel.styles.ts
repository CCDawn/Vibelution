import {
  vuiFlatPanelClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  empty:
    "empty min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  // Wave 6E: height from PersistedHeightListShell / pane-heights.v1, not fixed max-h.
  sourceCollectionGraphNodeListShell: `sourceCollectionGraphNodeListShell min-w-0 max-w-full grid min-h-0 content-start gap-1.5 overflow-auto rounded-[var(--radius-control)] border border-[color:var(--border-soft)] ${vuiFlatPanelClass} p-1.5 text-[var(--fg-primary)] [scrollbar-gutter:stable]`,
  sourceCollectionListResizeHandle:
    "sourceCollectionListResizeHandle",
  workflowCandidateList:
    "workflowCandidateList min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto [&_[data-vui-product=team-candidate-card]]:max-w-full [&_[data-vui=native-button]]:w-fit [&_[data-vui=native-button]]:max-w-full",
  workflowGraphStats:
    "workflowGraphStats min-w-0 grid gap-2 grid-cols-[repeat(auto-fit,minmax(9rem,1fr))]",
} as const;

export default styles;
