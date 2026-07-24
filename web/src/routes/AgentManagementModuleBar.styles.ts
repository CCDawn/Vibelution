import {
  vuiToolbarFillClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  moduleBar: `flex h-[52px] min-w-0 items-stretch justify-between gap-4 border-b border-[var(--vui-border-subtle)] ${vuiToolbarFillClass} px-4`,
  managementNav: "m-0 min-w-0",
  moduleActions:
    "flex min-w-0 shrink-0 items-center justify-end gap-2 [&_[data-vui=button]]:w-fit max-[560px]:[&_[data-vui=button]_[data-slot=vui-button-label]]:hidden",
} as const;

export default styles;
