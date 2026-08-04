import {
  vuiFlatPanelClass,
  vuiStateDangerSoftClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  // Content surface (Radix portals; positioning owned by DropdownMenu).
  sessionContextMenu: `vui-routes-chatcodingroute sessionContextMenu z-[80] w-[188px] max-w-[calc(100vw-24px)] ${vuiFlatPanelClass} shadow-none backdrop-blur-[4px]`,
  sessionContextMenuDanger:
    `vui-routes-chatcodingroute sessionContextMenuDanger min-w-0 ${vuiStateDangerSoftClass}`,
  sessionContextMenuItem:
    "vui-routes-chatcodingroute sessionContextMenuItem min-w-0 !w-full justify-start",
} as const;

export default styles;
