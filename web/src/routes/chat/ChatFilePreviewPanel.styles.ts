import {
  vuiFlatPanelClass,
} from "../../design/vuiSurfaceRecipes";

const styles = {
  emptySurface: `vui-routes-chatfilepreviewpanel emptySurface min-w-0 max-w-full break-words ${vuiFlatPanelClass} shadow-none p-2 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)] grid min-h-[96px] content-center justify-items-center px-3 py-4 text-center text-[var(--fg-secondary)] [overflow-wrap:anywhere]`,
} as const;

export default styles;
