import { vuiStateSelectedRowClass } from "../../design/vuiSurfaceRecipes";

const styles = {
  shell: "vui-routes-chatsidepane shell flex h-full min-h-0 min-w-0 flex-col !overflow-hidden",
  tabs: "vui-routes-chatsidepane tabs flex shrink-0 items-center gap-1 px-2 pt-2",
  tab:
    "vui-routes-chatsidepane tab !h-auto min-h-[var(--vui-control-height-sm)] !min-w-0 !border-0 !bg-transparent !px-2 !shadow-none [font-size:var(--vui-font-xs)] font-semibold text-[var(--fg-secondary)]",
  tabActive: `vui-routes-chatsidepane tabActive min-w-0 ${vuiStateSelectedRowClass}`,
  body: "vui-routes-chatsidepane body flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden",
} as const;

export default styles;
