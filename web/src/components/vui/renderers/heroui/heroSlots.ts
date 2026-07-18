/**
 * Backward-compatible re-exports.
 * Visual slots live in `renderers/shared/buttonSlots.ts` so shadcn/HeroUI
 * renderers share one token contract.
 */
export {
  vuiButtonBaseClass,
  vuiButtonDangerClass,
  vuiButtonHoverClass,
  vuiButtonPrimaryClass,
} from "../shared/buttonSlots";

export { vuiChipBaseClass } from "../shared/chipSlots";
