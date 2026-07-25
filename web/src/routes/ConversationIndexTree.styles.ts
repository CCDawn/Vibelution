import {
  vuiOpaqueRowClass,
} from "../design/vuiSurfaceRecipes";

// Wave 8D: team tree keys owned here after ChatCodingRoute dead prune.
const styles = {
  teamTreeChild:
    "vui-routes-chatcodingroute teamTreeChild min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto",
  teamTreeChildren:
    "vui-routes-chatcodingroute teamTreeChildren min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto",
  teamTreeGroup:
    "vui-routes-chatcodingroute teamTreeGroup min-w-0 grid min-h-0 content-start gap-1.5 overflow-hidden",
  teamTreeItem:
    "vui-routes-chatcodingroute teamTreeItem min-w-0 overflow-hidden border-transparent bg-transparent shadow-none",
  teamTreeLabelRow: `vui-routes-chatcodingroute teamTreeLabelRow min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto ${vuiOpaqueRowClass} p-2 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]`,
} as const;

export default styles;
