import { vuiStateWarningSoftClass } from "../design/vuiSurfaceRecipes";

const styles = {
  warningStrip:
    `warningStrip min-w-0 flex flex-wrap items-center gap-1.5 ${vuiStateWarningSoftClass}`,
} as const;

export default styles;
